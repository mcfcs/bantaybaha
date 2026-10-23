"""Priority scenarios: R (surge probability) x A (access loss) per unit, for each backtest typhoon and shifted tracks.

For a storm, the forecast origin is the DOH week containing landfall (data to the end of that week, i.e. "immediately
after"). Models are fit on data up to that week (never past 2019-12-29; 2020 storms use the 2019 model, and their R is
flagged because 2020 surveillance collapsed). Every track (the unshifted one too) gets its origin-week storm features
(gale hit, wind, distance, storm x hazard over the 4 weeks to the origin) rebuilt the way training builds them, with this
storm's fixes moved and other storms' fixes kept, so tracks differ only by the shift; observed rain is left as it was.

Action tiers are provisional rules (TIERS), to be reviewed with the target users:
  deploy mobile clinics  R >= 0.5 and A >= 0.10
  pre-position supplies  R >= 0.3, or A >= 0.10 and R >= 0.15
  monitor sentinel sites otherwise
"""

import json

import numpy as np
import pandas as pd
import geopandas as gpd
from scipy import stats

from .config import STORMS, APP_DATA, MODEL_END, CRS_M, week_ending, record, missing
from . import storms as S, access as AC, forecast as F, flood as FL

SHIFTS = [(dlat, dlon) for dlat in (-1.0, -0.5, 0.0, 0.5, 1.0) for dlon in (-1.0, 0.0, 1.0)]
TIERS = dict(deploy=(0.5, 0.10), preposition_R=0.3, preposition_A=(0.10, 0.15))
TIER_LABELS = {3: "Deploy mobile clinics before roads and ferries close",
               2: "Pre-position doxycycline and vector-control supplies",
               1: "Monitor sentinel sites"}


def tier(R, A):
    R, A = np.asarray(R, float), np.nan_to_num(np.asarray(A, float))
    t = np.ones(len(R), int)
    t[(R >= TIERS["preposition_R"]) | ((A >= TIERS["preposition_A"][0]) & (R >= TIERS["preposition_A"][1]))] = 2
    t[(R >= TIERS["deploy"][0]) & (A >= TIERS["deploy"][1])] = 3
    return t


def overrides_for(units, ib, key, dlat, dlon, origin, hazard, fixed_km):
    """Origin-week storm features for this storm moved by (dlat, dlon), built like the training features (see
    storms.origin_exposure). Used for every track, the unshifted one included, so differences between tracks come from
    the shift alone; the unshifted track reproduces the panel's own values."""
    o = S.origin_exposure(units, S.shift_storm(ib, key, dlat, dlon), origin, fixed_km)
    if hazard is not None:  # panel: storm_hazard_exposure = gale hit x hazard_any_25yr (static), so its 4-week max is this
        o["storm_hazard_4w"] = o.storm_gale_4w * o.unit_id.map(hazard.set_index("unit_id").hazard_any_25yr)
    return o


class AccessModel:
    """Network + baseline + per-edge hazard, reused across scenarios."""

    def __init__(self, cells, speed_factor=1.0):
        self.roads = AC.build_road_graph()
        self.hosp, self.hosp_source = AC.load_hospitals()
        self.ferries = AC.load_ferries()
        self.cells = cells
        self.ok = self.roads is not None and self.hosp is not None and cells is not None
        if not self.ok:
            missing("access", "road graph, hospitals or population cells missing: access loss A is NaN")
            return
        record("access", True, f"road graph + {len(self.hosp)} hospitals ({self.hosp_source}) + population cells")
        self.net = AC.Network(self.roads, self.ferries, self.hosp, cells, speed_factor)
        self.base = self.net.solve(self.net.road_hours())
        self.haz = AC.hazard_at(self.roads)
        self.ems = FL.ems_observed_flood("EMSR312")

    def observed_flood(self, storm):
        """Edges in observed flood for an unshifted historical storm: Sentinel-1 if on disk, else EMS (Ompong AOIs).
        Cached per storm: the sensitivity analysis asks for the same storm many times."""
        if not hasattr(self, "_obs"):
            self._obs = {}
        if storm not in self._obs:
            self._obs[storm] = self._observed_flood(storm)
        return self._obs[storm]

    def _observed_flood(self, storm):
        look = FL.s1_flood_lookup(storm)
        if look is not None:
            return look(self.roads["mid_lon"], self.roads["mid_lat"]) == 1, "sentinel1"
        if storm == "ompong" and self.ems is not None:
            import shapely

            geom = self.ems.union_all()
            shapely.prepare(geom)
            return shapely.contains_xy(geom, self.roads["mid_lon"], self.roads["mid_lat"]), "ems_aoi"
        return None, None

    def run(self, swath_m, storm=None, shifted=False, ferry_rule="crosses", slow=0.5, cut_ratio=2.0, speed_factor=None):
        keep = AC.ferry_keep_mask(self.ferries, swath_m, ferry_rule) if self.ferries is not None else None
        in_sw = AC.edges_in(swath_m, self.roads)
        mult, src = AC.road_multiplier(self.roads, in_sw, self.haz, None, slow)
        if not shifted and storm is not None:
            obs, osrc = self.observed_flood(storm)
            if obs is not None and osrc == "sentinel1":
                mult, _ = AC.road_multiplier(self.roads, in_sw, None, obs, slow)
                src = "sentinel1"
            elif obs is not None:  # EMS covers a few AOIs only: add it to the hazard proxy
                mult = np.where(obs, 0.0, mult)
                src = f"{src}+{osrc}"
        hours = self.net.road_hours(mult)
        base = self.base
        if speed_factor is not None:
            hours, base = hours / speed_factor, self.net.solve(self.net.road_hours() / speed_factor)
        storm_t = self.net.solve(hours, keep)
        cut = AC.cut_off(base, storm_t, cut_ratio)
        n_cancel = int((~keep & self.net.f_ok).sum()) if keep is not None else 0
        return base, storm_t, cut, src, n_cancel, keep


def run_all(panel, units, cells, hazard, edges_final, nodes_final, fixed_km=150.0, log=print):
    ib = S.load_ibtracs()
    am = AccessModel(cells)
    rows, adm3_rows, tracks, ferry_rows, swaths = [], [], [], [], []
    fits = {}  # by training end: Rolly and Ulysses both train to MODEL_END, so they share one fit
    cals = {}  # R calibration hook (forecast.surge_calibrator): isotonic on rolling-origin forecasts with target week <= train end
    for key, s in STORMS.items():
        tr = S.storm_track(key, ib=ib)
        origin = week_ending(s["landfall"])
        end = min(origin, pd.Timestamp(MODEL_END))
        if end not in fits:
            fits[end] = F.fit_at(panel, origin)
            cals[end] = F.surge_calibrator(end)
        fitted = dict(fits[end], origin=origin)
        log(f"  {s['local']}: origin {origin.date()}, model trained to {fitted['train_end'].date()}")
        for dlat, dlon in SHIFTS:
            shifted = (dlat, dlon) != (0.0, 0.0)
            t2 = S.shift_track(tr, dlat, dlon)
            sw = S.swath(t2, fixed_km)
            fc = F.predict_at(fitted, overrides_for(units, ib, key, dlat, dlon, origin, hazard, fixed_km))
            fc = F.calibrate_R(fc, cals[end])  # R_raw = model probability; R (used for P and tiers) = calibrated
            q = np.vstack(fc.q_cum4)
            pop = fc["pop"].to_numpy()
            fc["cases4_med"] = F.to_cases(q, pop)[:, F.IQ50]
            fc["cases4_lo90"] = F.to_cases(q, pop)[:, 2]
            fc["cases4_hi90"] = F.to_cases(q, pop)[:, -3]
            fc = fc.drop(columns=[c for c in fc.columns if c.startswith("q_")])
            if am.ok:
                base, st, cut, src, n_cancel, keep = am.run(sw, key, shifted)
                acc = AC.summarise(cells, base, st, cut, "unit_id")
                a3 = AC.summarise(cells, base, st, cut, "adm3_pcode")
                a3 = a3.merge(cells[["adm3_pcode", "adm3_name", "unit_id"]].drop_duplicates("adm3_pcode"), on="adm3_pcode", how="left")
                adm3_rows.append(a3.assign(storm=key, dlat=dlat, dlon=dlon))
                if am.ferries is not None:
                    ferry_rows.append(pd.DataFrame({"route": am.ferries.route_name, "storm": key, "dlat": dlat, "dlon": dlon,
                                                    "cancelled": ~keep & am.net.f_ok, "snapped": am.net.f_ok}))
            else:
                acc = pd.DataFrame({"unit_id": units.unit_id, "A": np.nan, "pop_cut": np.nan})
                src, n_cancel = "none", 0
            r = fc.merge(acc, on="unit_id", how="left", suffixes=("", "_cells"))
            r["P"] = r.R * r.A
            r["tier"] = tier(r.R, r.A)
            r = r.merge(nodes_final[["unit_id", "is_sentinel", "sentinel_rank", "community"]], on="unit_id", how="left")
            r = r.assign(storm=key, dlat=dlat, dlon=dlon, flood_source=src, ferries_cancelled=n_cancel,
                         origin=origin, train_end=fitted["train_end"], hospital_source=getattr(am, "hosp_source", None),
                         flag_2020=s["season"] >= 2020)
            rows.append(r)
            tracks.append(t2[["LAT", "LON", "time", "wind_kt"]].assign(storm=key, dlat=dlat, dlon=dlon))
            if sw is not None:
                g = gpd.GeoSeries([sw], crs=CRS_M).to_crs(4326).simplify(0.02).iloc[0]
                swaths.append(dict(storm=key, dlat=dlat, dlon=dlon, wkt=g.wkt))
        log(f"    {len(SHIFTS)} scenarios done")
    out = pd.concat(rows, ignore_index=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)
    out.to_parquet(APP_DATA / "scenarios.parquet")
    pd.concat(tracks).to_parquet(APP_DATA / "tracks.parquet")
    pd.DataFrame(swaths).to_parquet(APP_DATA / "swaths.parquet")
    if adm3_rows:
        pd.concat(adm3_rows).to_parquet(APP_DATA / "scenarios_adm3.parquet")
    if ferry_rows:
        pd.concat(ferry_rows).to_parquet(APP_DATA / "ferries_status.parquet")
        am.ferries.assign(wkt=am.ferries.geometry.to_wkt()).drop(columns="geometry").to_parquet(APP_DATA / "ferries.parquet")
    if am.ok:
        am.hosp.assign(lon=am.hosp.geometry.x, lat=am.hosp.geometry.y).drop(columns="geometry").to_parquet(APP_DATA / "hospitals.parquet")
    record("scenarios", True, f"{out.storm.nunique()} storms x {len(SHIFTS)} tracks; access {'on' if am.ok else 'MISSING'}")
    return out, am


def validate(panel, scen):
    """Did high-priority units see more cases in the 4 weeks after landfall? (unshifted tracks only)"""
    p = panel.sort_values(["unit_id", "week"])
    rows = []
    for key, s in STORMS.items():
        d = scen[(scen.storm == key) & (scen.dlat == 0) & (scen.dlon == 0)].copy()
        if d.empty:
            continue
        o = d.origin.iloc[0]
        nxt = p[(p.week > o) & (p.week <= o + pd.Timedelta(weeks=4))].groupby("unit_id").incidence.sum(min_count=4)
        d["obs4"] = d.unit_id.map(nxt)
        d["obs_ratio"] = d.obs4 / d.surge_thr
        d["obs_surge"] = (d.obs4 > d.surge_thr).astype(float).where(d.obs4.notna())
        v = d.dropna(subset=["obs4"])
        top = v.nlargest(10, "P") if v.P.notna().any() else v.nlargest(10, "R")
        rows.append(dict(
            storm=s["local"], origin=str(o.date()), units=len(v), surge_rate=v.obs_surge.mean(),
            spearman_R_obs=stats.spearmanr(v.R, v.obs_ratio).statistic if len(v) > 5 else np.nan,
            spearman_P_obs=stats.spearmanr(v.P, v.obs_ratio).statistic if v.P.notna().sum() > 5 else np.nan,
            top10_surge_rate=top.obs_surge.mean(), brier_R=((v.R - v.obs_surge) ** 2).mean(),
            note="2020: COVID-depressed reporting, indicative only" if s["season"] >= 2020 else ""))
    return pd.DataFrame(rows)


def sensitivity(am, scen, units, fixed_km=150.0, ib=None):
    """Rank stability of P (Kendall's tau vs the base settings) for each storm's unshifted track."""
    if not am.ok:
        return missing("sensitivity", "access model unavailable")
    ib = S.load_ibtracs() if ib is None else ib
    variants = {"speed x0.8": dict(speed_factor=0.8), "speed x1.2": dict(speed_factor=1.2),
                "ferry rule: port in swath": dict(ferry_rule="ports"), "medium hazard slow x0.25": dict(slow=0.25),
                "medium hazard slow x0.75": dict(slow=0.75), "cut-off ratio 1.5": dict(cut_ratio=1.5),
                "cut-off ratio 3": dict(cut_ratio=3.0), "gale fallback 100 km": dict(fixed=100.0),
                "gale fallback 200 km": dict(fixed=200.0)}
    rows = []
    for key in STORMS:
        base = scen[(scen.storm == key) & (scen.dlat == 0) & (scen.dlon == 0)].set_index("unit_id")
        tr = S.storm_track(key, ib=ib)
        for name, kw in variants.items():
            kw = dict(kw)
            sw = S.swath(tr, kw.pop("fixed", fixed_km))
            b, st, cut, *_ = am.run(sw, key, False, **kw)
            A = AC.summarise(am.cells, b, st, cut, "unit_id").set_index("unit_id").A
            P = base.R * A.reindex(base.index)
            ok = base.P.notna() & P.notna()
            tau = stats.kendalltau(base.P[ok], P[ok]).statistic if ok.sum() > 5 else np.nan
            top10 = len(set(base.P[ok].nlargest(10).index) & set(P[ok].nlargest(10).index))
            rows.append(dict(storm=STORMS[key]["local"], variant=name, kendall_tau=tau, top10_overlap=top10,
                             mean_A=float(A.mean())))
    record("sensitivity", True, f"{len(variants)} variants x {len(STORMS)} storms")
    return pd.DataFrame(rows)


def metro_manila_benchmark(am, units):
    """NCR with every road edge in NOAH 25-yr medium/high hazard cut (no storm swath): share of NCR population cut off.
    Compared with Tariverdi et al. (2023): ~22% of Metro Manila residents lose access to higher-level care at a 15 cm
    flood. Different flood definition and facility set: an order-of-magnitude check, not a replication."""
    if not am.ok or am.haz is None:
        return missing("benchmark", "access model or NOAH hazard raster unavailable")
    mult = np.where(np.isin(am.haz, [2, 3]), 0.0, 1.0)
    st = am.net.solve(am.net.road_hours(mult))
    cut = AC.cut_off(am.base, st)
    acc = AC.summarise(am.cells, am.base, st, cut, "unit_id")
    ncr = acc[acc.unit_id.isin(units[units.unit_name.str.startswith("Metropolitan Manila")].unit_id)]
    share = ncr.pop_cut.sum() / ncr["pop"].sum() if len(ncr) else np.nan
    record("benchmark", True, f"NCR share cut off {share:.1%}")
    return pd.DataFrame([dict(scenario="NCR, all NOAH 25-yr medium/high hazard roads cut", ncr_pop=ncr["pop"].sum(),
                              pop_cut=ncr.pop_cut.sum(), share_cut=share, tariverdi_2023="~22% (15 cm flood, higher-level care)")])
