"""Harmonised 2016-2020 province units and the crosswalks into them.

COD-AB is current-boundary (finding 7). The harmonised units are the COD-AB ADM2 units with three post-2020 changes
undone:
  Maguindanao del Norte + Maguindanao del Sur  -> Maguindanao (split in 2022)
  Special Geographic Area                      -> Cotabato    (its 63 barangays were in Cotabato until 2024)
  City of Isabela                              -> Basilan     (geographically in Basilan)
NCR stays as its 4 COD-AB districts. HUC / component cities in the dengue file fold into the unit that contains them
(finding 1). The crosswalks are written once to data/crosswalks/ and every later stage reads them from there.
"""

import re
import unicodedata

import pandas as pd
import geopandas as gpd

from .config import RAW, CROSSWALKS, PROCESSED, have, record, missing

COD_ZIP = RAW / "cod_ab" / "phl_admin_boundaries.gdb.zip"
ADM2_XW = CROSSWALKS / "adm2_to_unit.csv"
DENGUE_XW = CROSSWALKS / "dengue_loc_to_unit.csv"
UNITS_GPKG = PROCESSED / "units.gpkg"

# COD-AB ADM2 name prefix -> harmonised unit name
MERGE = {"Maguindanao del Norte": "Maguindanao", "Maguindanao del Sur": "Maguindanao",
         "Special Geographic Area": "Cotabato (North Cotabato)", "City of Isabela": "Basilan"}
# id for units with no single COD-AB parent (PSGC-style, documented in the crosswalk header)
SYNTHETIC_ID = {"Maguindanao": "PH_MAGUINDANAO_2016"}

# dengue spellings / old units -> normalised COD-AB names (finding 1). NAGA CITY is listed under Region V, so Camarines Sur.
DENGUE_FIX = {"NUEVAVISCAYA": "NUEVAVIZCAYA", "SISQUIJOR": "SIQUIJOR", "NORTHCOTABATO": "COTABATO", "BASILIG": "BISLIG",
              "MAGUINDANAO": "MAGUINDANAODELNORTE", "MANILA": "METROPOLITANMANILAFIRSTDISTRICT"}
DENGUE_CITY_PROVINCE = {"NAGA CITY": "Camarines Sur"}


def norm(s):
    """Upper-case ASCII letters only, without 'City of' / 'City' and parentheticals (Las Piñas -> LASPINAS)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^A-Z]", "", s.replace("CITY OF ", "").replace(" CITY", ""))


def read_adm(level, geometry=True):
    if not COD_ZIP.exists():
        return missing("cod_ab", f"{COD_ZIP.name} not found")
    record("cod_ab", True, COD_ZIP.name)
    return gpd.read_file(f"zip://{COD_ZIP.as_posix()}", layer=f"phl_admin{level}", read_geometry=geometry)


def _unit_name(adm2_name):
    for prefix, unit in MERGE.items():
        if adm2_name.startswith(prefix):
            return unit, f"merged: {prefix} -> {unit}"
    return adm2_name, "same as COD-AB ADM2"


def build_adm2_crosswalk(adm2):
    xw = adm2[["adm2_pcode", "adm2_name"]].copy()
    xw[["unit_name", "rule"]] = [_unit_name(n) for n in xw.adm2_name]
    # unit_id: the ADM2 pcode of the member with the unit's own name, else a synthetic id
    own = xw[xw.adm2_name == xw.unit_name].set_index("unit_name").adm2_pcode
    xw["unit_id"] = xw.unit_name.map(own).fillna(xw.unit_name.map(SYNTHETIC_ID))
    assert xw.unit_id.notna().all(), xw[xw.unit_id.isna()]
    return xw[["adm2_pcode", "adm2_name", "unit_id", "unit_name", "rule"]].sort_values("unit_id")


def build_dengue_crosswalk(dengue_locs, adm2, adm3, adm2_xw):
    """Name match of the 126 dengue units to COD-AB (the notebook section 5 logic), then ADM2 -> unit."""
    cities = {l for l in dengue_locs if "CITY" in l or l in ("PATEROS", "TACLOBAN")}
    a2 = {norm(n): n for n in adm2.adm2_name if not n.startswith("City of Isabela")}  # else collides with Isabela
    a3 = adm3.assign(k=adm3.adm3_name.map(norm), city=adm3.adm3_name.str.contains("City"))
    rows = []
    for l in sorted(dengue_locs):
        k = DENGUE_FIX.get(norm(l), norm(l))
        cand = a3[a3.k == k].sort_values("city", ascending=False, kind="stable")  # a city beats a same-name town
        if l in DENGUE_CITY_PROVINCE:
            cand = cand[cand.adm2_name == DENGUE_CITY_PROVINCE[l]]
        if l in cities and len(cand):
            rows.append((l, "ADM3 city -> ADM2", cand.adm2_name.iloc[0], cand.adm3_name.iloc[0], len(cand[cand.city])))
        elif k in a2:
            rows.append((l, "ADM2", a2[k], None, 1))
        elif len(cand):
            rows.append((l, "ADM3 -> ADM2", cand.adm2_name.iloc[0], cand.adm3_name.iloc[0], len(cand)))
        else:
            rows.append((l, "UNMATCHED", None, None, 0))
    m = pd.DataFrame(rows, columns=["dengue_loc", "match", "adm2_name", "adm3_name", "n_candidates"])
    m = m.merge(adm2_xw[["adm2_name", "unit_id", "unit_name"]], on="adm2_name", how="left")
    m["note"] = ""
    m.loc[m.n_candidates > 1, "note"] = "ambiguous name, resolved city-first / by region"
    m.loc[m.dengue_loc.isin(DENGUE_CITY_PROVINCE), "note"] = "ambiguous (Camarines Sur vs Cebu); Region V -> Camarines Sur"
    return m.drop(columns="n_candidates")


def write_csv_with_header(df, path, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        for line in header.strip().splitlines():
            f.write(f"# {line}\n")
        df.to_csv(f, index=False)


def read_crosswalk(path):
    return pd.read_csv(path, comment="#", dtype=str)


def build_crosswalks(force=False):
    """Write data/crosswalks/adm2_to_unit.csv and dengue_loc_to_unit.csv (once; reused unless force)."""
    if ADM2_XW.exists() and DENGUE_XW.exists() and not force:
        print(f"  reuse {ADM2_XW.name}, {DENGUE_XW.name}")
        return read_crosswalk(ADM2_XW), read_crosswalk(DENGUE_XW)
    adm2 = read_adm(2, geometry=False)
    adm3 = read_adm(3, geometry=False)
    if adm2 is None:
        return None, None
    from .dengue import load_dengue  # local import: dengue imports this module

    dg = load_dengue()
    if dg is None:  # recorded as missing by load_dengue; no crosswalk can be written without the reporting units
        return None, None
    xw2 = build_adm2_crosswalk(adm2)
    xwd = build_dengue_crosswalk(dg["loc"].unique(), adm2, adm3, xw2)
    src = f"COD-AB {adm2.version.iloc[0] if 'version' in adm2 else ''} ({COD_ZIP.name})"
    write_csv_with_header(xw2, ADM2_XW, f"""
Harmonised 2016-2020 province units <- COD-AB ADM2 (current boundaries). Source: {src}.
Generated by `python scripts/build.py crosswalk`, then reviewed. Rules: Maguindanao del Norte/Sur -> Maguindanao
(split 2022; synthetic id {SYNTHETIC_ID["Maguindanao"]}); Special Geographic Area ->
Cotabato (created 2024 from Cotabato barangays); City of Isabela -> Basilan. NCR kept as its 4 districts.""")
    write_csv_with_header(xwd, DENGUE_XW, f"""
DOH-Epi dengue reporting units (126, HDX doh-epi-dengue-data-2016-2021.csv) -> harmonised units. Source: {src}.
Generated by `python scripts/build.py crosswalk`, then reviewed. City units are matched as cities first
(Quezon City != Quezon), misspellings fixed (NUEVA VISCAYA, SISQUIJOR, NORTH COTABATO, BASILIG CITY = Bislig City,
CARAGA), MAGUINDANAO -> Maguindanao del Norte -> Maguindanao, NAGA CITY -> Camarines Sur (Region V).""")
    n_un = (xwd.match == "UNMATCHED").sum()
    record("crosswalk", n_un == 0, f"{len(xwd)} dengue units -> {xwd.unit_id.nunique()} harmonised units; {n_un} unmatched")
    print(f"  wrote {ADM2_XW.name} ({xw2.unit_id.nunique()} units), {DENGUE_XW.name} ({len(xwd)} rows, {n_un} unmatched)")
    return xw2, xwd


def check_psgc(xw2):
    """If the manual PSA PSGC file is present, check every COD-AB pcode in the crosswalk against it."""
    d = RAW / "psgc"
    if not have("psgc", d, pattern="*.xlsx"):
        return None
    f = sorted(d.glob("*.xlsx"))[-1]
    xl = pd.ExcelFile(f)
    sheet = next((s for s in xl.sheet_names if "PSGC" in s.upper()), xl.sheet_names[0])
    ps = pd.read_excel(xl, sheet, dtype=str)
    code_col = next(c for c in ps.columns if "code" in str(c).lower())
    codes = set(ps[code_col].str.strip().str.zfill(10))
    pc = xw2.adm2_pcode.str.replace("PH", "", regex=False).str.ljust(10, "0")
    ok = pc.isin(codes)
    record("psgc_check", bool(ok.all()), f"{ok.sum()}/{len(ok)} COD-AB ADM2 pcodes found in {f.name}")
    return xw2.assign(in_psgc=ok.values)


def build_units_geometry(force=False):
    """Dissolve COD-AB ADM2 into harmonised unit polygons (EPSG:4326) -> data/processed/units.gpkg."""
    if UNITS_GPKG.exists() and not force:
        return gpd.read_file(UNITS_GPKG)
    adm2 = read_adm(2)
    if adm2 is None:
        return None
    xw2 = read_crosswalk(ADM2_XW)
    g = adm2[["adm2_pcode", "adm1_name", "geometry"]].merge(xw2[["adm2_pcode", "unit_id", "unit_name"]], on="adm2_pcode")
    u = g.dissolve(by=["unit_id", "unit_name"], aggfunc={"adm1_name": "first"}).reset_index()
    u = u.rename(columns={"adm1_name": "region"}).to_crs(4326)
    u["geometry"] = u.geometry.make_valid().simplify(0.0005)  # ~50 m, below the 100 m raster cells used downstream
    UNITS_GPKG.parent.mkdir(parents=True, exist_ok=True)
    UNITS_GPKG.unlink(missing_ok=True)  # GeoPackage keeps the old pages otherwise
    u.to_file(UNITS_GPKG, driver="GPKG")
    return u


def load_units():
    if not UNITS_GPKG.exists():
        return build_units_geometry()
    return gpd.read_file(UNITS_GPKG)


def adm3_with_units():
    """ADM3 polygons with their harmonised unit (municipality / city level, for access summaries)."""
    adm3 = read_adm(3)
    if adm3 is None:
        return None
    xw2 = read_crosswalk(ADM2_XW)
    return adm3[["adm3_pcode", "adm3_name", "adm2_pcode", "geometry"]].merge(xw2[["adm2_pcode", "unit_id", "unit_name"]], on="adm2_pcode")
