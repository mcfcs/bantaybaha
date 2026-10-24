"""Priority scenarios: R (surge probability) x A (access loss) per unit, for each backtest typhoon and shifted tracks.

For a storm, the forecast origin is the DOH week containing landfall (data to the end of that week, i.e. "immediately
after"). Models are fit on data up to that week (never past 2019-12-29; 2020 storms use the 2019 model, and their R is
flagged because 2020 surveillance collapsed). Every track (the unshifted one too) gets its origin-week storm features
(gale hit, wind, distance, storm x hazard over the 4 weeks to the origin) rebuilt the way training builds them, with this
storm's fixes moved and other storms' fixes kept, so tracks differ only by the shift; observed rain is left as it was.

Access loss A comes from two methods run on every track (bantay/access.py): the road + RoRo network (primary: A, P,
tier) and the MAP friction raster (A_raster); A_lo / A_hi and P_lo / P_hi = R x A_lo / A_hi are the range between them.
Under-5 and 60+ people (Meta HRSL) and those cut off are added per unit and municipality. `run_catalog` scores the
unshifted track of every other 2016-2020 storm whose gale swath meets PHL land (NOAH proxy flood, leak-free fits).

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
    """Network + baseline + per-edge hazard, reused across scenarios; plus the raster (MAP friction) method when the
    friction GeoTIFF is on disk (`raster` is None otherwise)."""

    def __init__(self, cells, speed_factor=1.0, units=None):
        self.roads = AC.build_road_graph()
        self.hosp, self.hosp_source = AC.load_hospitals()
        self.ferries = AC.load_ferries()
        self.cells = cells
        self.raster = None
        self.ok = self.roads is not None and self.hosp is not None and cells is not None
        if not self.ok:
            missing("access", "road graph, hospitals or population cells missing: access loss A is NaN")
            return
        record("access", True, f"road graph + {len(self.hosp)} hospitals ({self.hosp_source}) + population cells")
        self.net = AC.Network(self.roads, self.ferries, self.hosp, cells, speed_factor)
        self.base = self.net.solve(self.net.road_hours())
        self.haz = AC.hazard_at(self.roads)
        self.ems = FL.ems_observed_flood("EMSR312")
        if units is not None:
            f_ok = self.net.f_ok if self.ferries is not None else None
            self.raster = AC.friction_grid(units, self.hosp, cells, self.ferries, f_ok)
        if self.raster is not None:
            self.base_r = self.raster.solve()

    def observed_flood(self, storm, where="roads"):
        """Observed flood for an unshifted historical storm at road-edge midpoints (`where="roads"`) or at friction-cell
        centres ("grid"): Sentinel-1 if on disk, else EMS (Ompong AOIs). Cached: sensitivity asks for a storm many times."""
        if not hasattr(self, "_obs"):
            self._obs = {}
        if (storm, where) not in self._obs:
            if where == "roads":
                lon, lat = self.roads["mid_lon"], self.roads["mid_lat"]
            else:
                lon, lat = self.raster.lon, self.raster.lat
            self._obs[storm, where] = self._observed_flood(storm, lon, lat)
        return self._obs[storm, where]

    def _observed_flood(self, storm, lon, lat):
        look = FL.s1_flood_lookup(storm)
        if look is not None:
            return look(lon, lat) == 1, "sentinel1"
        if storm == "ompong" and self.ems is not None:
            import shapely

            geom = self.ems.union_all()
            shapely.prepare(geom)
            return shapely.contains_xy(geom, lon, lat), "ems_aoi"
        return None, None

    def _multiplier(self, pts, in_sw, haz, storm, shifted, slow, where):
        """Speed multiplier (0 = cut) per road edge or friction cell, and the flood source; same rule for both methods."""
        mult, src = AC.road_multiplier(pts, in_sw, haz, None, slow)
        if not shifted and storm is not None:
            obs, osrc = self.observed_flood(storm, where)
            if obs is not None and osrc == "sentinel1":
                mult, _ = AC.road_multiplier(pts, in_sw, None, obs, slow)
                src = "sentinel1"
            elif obs is not None:  # EMS covers a few AOIs only: add it to the hazard proxy
                mult = np.where(obs, 0.0, mult)
                src = f"{src}+{osrc}"
        return mult, src

    def run(self, swath_m, storm=None, shifted=False, ferry_rule="crosses", slow=0.5, cut_ratio=2.0, speed_factor=None):
        keep = AC.ferry_keep_mask(self.ferries, swath_m, ferry_rule) if self.ferries is not None else None
        in_sw = AC.edges_in(swath_m, self.roads)
        mult, src = self._multiplier(self.roads, in_sw, self.haz, storm, shifted, slow, "roads")
        hours = self.net.road_hours(mult)
        base = self.base
        if speed_factor is not None:
            hours, base = hours / speed_factor, self.net.solve(self.net.road_hours() / speed_factor)
        storm_t = self.net.solve(hours, keep)
        cut = AC.cut_off(base, storm_t, cut_ratio)
        n_cancel = int((~keep & self.net.f_ok).sum()) if keep is not None else 0
        return base, storm_t, cut, src, n_cancel, keep

    def run_raster(self, swath_m, storm=None, shifted=False, keep=None, slow=0.5, cut_ratio=2.0, speed_factor=None):
        """Raster method for the same scenario as `run`: same swath, same cancelled ferries (`keep` from run), same
        flood rule on the friction cells. Returns (base, storm, cut) per population cell, or None without the raster."""
        if self.raster is None:
            return None
        g = self.raster
        pts = {"u": g.lon}
        mult, _ = self._multiplier(pts, g.in_swath(swath_m), g.hazard(), storm, shifted, slow, "grid")
        sf = 1.0 if speed_factor is None else speed_factor
        base = self.base_r if speed_factor is None else g.solve(speed_factor=sf)
        st = g.solve(mult, keep, sf)
        return base, st, AC.cut_off(base, st, cut_ratio)


VULNERABLE = ("pop_u5", "pop_60")  # Meta HRSL 2020 under-5 and 60+ (grids.build_vulnerable_cells), when on the cells


def access_tables(cells, net, ras, level):
    """Access summary per `level` (unit_id or adm3_pcode). Network method = primary (A, pop_cut, base_hours, as before);
    raster method = A_raster, pop_cut_raster, base_hours_raster, pop_no_access_base_raster; A_lo / A_hi = min / max of
    the two (NaN when the raster is missing); under-5 / 60+ people and those cut off (network cut-off)."""
    base, st, cut = net
    acc = AC.summarise(cells, base, st, cut, level)
    for v in VULNERABLE:
        if v in cells:
            w = cells[v].to_numpy()
            g = pd.DataFrame({level: cells[level].to_numpy(), v: w, f"pop_cut_{v[4:]}": np.where(cut, w, 0.0)}).groupby(level).sum()
            acc = acc.merge(g.reset_index(), on=level, how="left")
        else:
            acc[v], acc[f"pop_cut_{v[4:]}"] = np.nan, np.nan
    rc = ["pop_cut", "A", "base_hours", "pop_no_access_base"]
    if ras is not None:
        r = AC.summarise(cells, *ras, level)[[level] + rc]
        acc = acc.merge(r.rename(columns={c: f"{c}_raster" for c in rc}), on=level, how="left")
    else:
        for c in rc:
            acc[f"{c}_raster"] = np.nan
    acc["A_lo"] = np.minimum(acc.A, acc.A_raster)  # NaN-propagating: no interval without both methods
    acc["A_hi"] = np.maximum(acc.A, acc.A_raster)
    return acc


def track_access(am, sw, storm, shifted, cells, **kw):
    """Both access methods for one track: (unit table, ADM3 table, flood source, ferries cancelled, keep, method row)."""
    base, st, cut, src, n_cancel, keep = am.run(sw, storm, shifted, **kw)
    kr = {k: v for k, v in kw.items() if k != "ferry_rule"}
    ras = am.run_raster(sw, storm, shifted, keep, **kr)
    acc = access_tables(cells, (base, st, cut), ras, "unit_id")
    a3 = access_tables(cells, (base, st, cut), ras, "adm3_pcode")
    a3 = a3.merge(cells[["adm3_pcode", "adm3_name", "unit_id"]].drop_duplicates("adm3_pcode"), on="adm3_pcode", how="left")
    w = cells["pop"].to_numpy()
    both = acc.A.notna() & acc.A_raster.notna()
    row = dict(flood_source=src, mean_A_network=acc.A.mean(), mean_A_raster=acc.A_raster.mean(),
               pop_cut_network=float(w[cut].sum()), pop_cut_raster=float(w[ras[2]].sum()) if ras else np.nan,
               spearman_A_units=stats.spearmanr(acc.A[both], acc.A_raster[both]).statistic if both.sum() > 5 else np.nan,
               n_units=int(both.sum()))
    return acc, a3, src, n_cancel, keep, row


def baseline_agreement(am):
    """Normal-day travel time to the nearest hospital, network vs raster method: one row for access_methods.csv."""
    if not am.ok or am.raster is None:
        return None
    b, r = am.base, am.base_r
    w = am.cells["pop"].to_numpy()
    ok = np.isfinite(b) & np.isfinite(r)
    u = AC.summarise(am.cells, b, b, np.zeros(len(b), bool), "unit_id").set_index("unit_id").base_hours
    ur = AC.summarise(am.cells, r, r, np.zeros(len(r), bool), "unit_id").set_index("unit_id").base_hours.reindex(u.index)
    k = u.notna() & ur.notna()
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = r[ok] / b[ok]
        pos = ok & (b > 0) & (r > 0)
    return dict(kind="baseline", storm="baseline", cells_both_reach=int(ok.sum()), cells=len(b),
                pop_reach_network=float(w[np.isfinite(b)].sum() / w.sum()), pop_reach_raster=float(w[np.isfinite(r)].sum() / w.sum()),
                popw_mean_hours_network=float(np.average(b[np.isfinite(b)], weights=w[np.isfinite(b)])),
                popw_mean_hours_raster=float(np.average(r[np.isfinite(r)], weights=w[np.isfinite(r)])),
                pearson_log_hours_cells=float(np.corrcoef(np.log(b[pos]), np.log(r[pos]))[0, 1]),
                spearman_hours_cells=float(stats.spearmanr(b[ok], r[ok]).statistic),
                median_ratio_raster_network=float(np.median(ratio[np.isfinite(ratio)])),
                popw_median_ratio_raster_network=float(_wmedian(ratio[np.isfinite(ratio)], w[ok][np.isfinite(ratio)])),
                spearman_unit_base_hours=float(stats.spearmanr(u[k], ur[k]).statistic),
                pearson_unit_base_hours=float(np.corrcoef(u[k], ur[k])[0, 1]), n_units=int(k.sum()))


def _wmedian(x, w):
    o = np.argsort(x)
    c = np.cumsum(w[o])
    return x[o][np.searchsorted(c, c[-1] / 2)]


def case_columns(fc):
    """Median and 90% range of cases over the next 4 weeks from the cumulative quantiles; drops the quantile lists."""
    q = np.vstack(fc.q_cum4)
    cases = F.to_cases(q, fc["pop"].to_numpy())
    fc["cases4_med"], fc["cases4_lo90"], fc["cases4_hi90"] = cases[:, F.IQ50], cases[:, 2], cases[:, -3]
    return fc.drop(columns=[c for c in fc.columns if c.startswith("q_")])


def scenario_rows(fc, acc, nodes_final, units, **cols):
    """One storm track: forecast rows + access + priority P = R x A (network), P_lo / P_hi (method range) and tier."""
    if acc is None:
        acc = pd.DataFrame({"unit_id": units.unit_id, "A": np.nan, "pop_cut": np.nan})
    r = fc.merge(acc, on="unit_id", how="left", suffixes=("", "_cells"))
    r["P"] = r.R * r.A
    r["P_lo"], r["P_hi"] = r.R * r.get("A_lo", np.nan), r.R * r.get("A_hi", np.nan)
    r["tier"] = tier(r.R, r.A)
    r = r.merge(nodes_final[["unit_id", "is_sentinel", "sentinel_rank", "community"]], on="unit_id", how="left")
    return r.assign(**cols)


def adm3_priority(a3, fc):
    """Municipal rows get their unit's R; P, P_lo, P_hi = unit R x municipal A (network / min / max of the methods)."""
    R = a3.unit_id.map(fc.set_index("unit_id").R)
    return a3.assign(R=R, P=R * a3.A, P_lo=R * a3.A_lo, P_hi=R * a3.A_hi)


def write_scenario_outputs(suffix, rows, adm3_rows, tracks, swaths, ferry_rows, am=None, methods=None):
    """scenarios{suffix}.parquet and companions in data/processed/app/ (suffix "" = backtests, "_catalog")."""
    APP_DATA.mkdir(parents=True, exist_ok=True)
    out = pd.concat(rows, ignore_index=True)
    out.to_parquet(APP_DATA / f"scenarios{suffix}.parquet")
    pd.concat(tracks).to_parquet(APP_DATA / f"tracks{suffix}.parquet")
    pd.DataFrame(swaths).to_parquet(APP_DATA / f"swaths{suffix}.parquet")
    if adm3_rows:
        pd.concat(adm3_rows).to_parquet(APP_DATA / f"scenarios{suffix}_adm3.parquet")
    if ferry_rows:
        pd.concat(ferry_rows).to_parquet(APP_DATA / f"ferries_status{suffix}.parquet")
    if methods is not None:
        methods.to_csv(APP_DATA / f"access_methods{suffix}.csv", index=False)
    return out


def run_all(panel, units, cells, hazard, edges_final, nodes_final, fixed_km=150.0, log=print):
    ib = S.load_ibtracs()
    am = AccessModel(cells, units=units)
    rows, adm3_rows, tracks, ferry_rows, swaths, methods = [], [], [], [], [], []
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
            # R_raw = model probability; R (used for P and tiers) = calibrated on past rolling-origin forecasts only
            fc = case_columns(F.calibrate_R(F.predict_at(fitted, overrides_for(units, ib, key, dlat, dlon, origin, hazard, fixed_km)), cals[end]))
            acc, src, n_cancel = None, "none", 0
            if am.ok:
                acc, a3, src, n_cancel, keep, mrow = track_access(am, sw, key, shifted, cells)
                adm3_rows.append(adm3_priority(a3, fc).assign(storm=key, dlat=dlat, dlon=dlon))
                methods.append(dict(kind="scenario", storm=key, dlat=dlat, dlon=dlon, **mrow))
                if am.ferries is not None:
                    ferry_rows.append(pd.DataFrame({"route": am.ferries.route_name, "storm": key, "dlat": dlat, "dlon": dlon,
                                                    "cancelled": ~keep & am.net.f_ok, "snapped": am.net.f_ok}))
            rows.append(scenario_rows(fc, acc, nodes_final, units, storm=key, dlat=dlat, dlon=dlon, flood_source=src,
                                      ferries_cancelled=n_cancel, origin=origin, train_end=fitted["train_end"],
                                      hospital_source=getattr(am, "hosp_source", None), flag_2020=s["season"] >= 2020))
            tracks.append(t2[["LAT", "LON", "time", "wind_kt"]].assign(storm=key, dlat=dlat, dlon=dlon))
            if sw is not None:
                g = gpd.GeoSeries([sw], crs=CRS_M).to_crs(4326).simplify(0.02).iloc[0]
                swaths.append(dict(storm=key, dlat=dlat, dlon=dlon, wkt=g.wkt))
        log(f"    {len(SHIFTS)} scenarios done")
    base_row = baseline_agreement(am)
    m = pd.DataFrame(([base_row] if base_row else []) + methods) if am.ok else None
    out = write_scenario_outputs("", rows, adm3_rows, tracks, swaths, ferry_rows, am, m)
    if ferry_rows:
        am.ferries.assign(wkt=am.ferries.geometry.to_wkt()).drop(columns="geometry").to_parquet(APP_DATA / "ferries.parquet")
    if am.ok:
        am.hosp.assign(lon=am.hosp.geometry.x, lat=am.hosp.geometry.y).drop(columns="geometry").to_parquet(APP_DATA / "hospitals.parquet")
    record("scenarios", True, f"{out.storm.nunique()} storms x {len(SHIFTS)} tracks; access {'on' if am.ok else 'MISSING'}; "
                              f"raster method {'on' if am.ok and am.raster is not None else 'MISSING'}")
    return out, am


# ---------------------------------------------------------------- any historical track (catalogue)

CATALOG_MIN_WIND_KT = 34  # a storm qualifies only if some fix reaches gale strength (34 kt) ...
CATALOG_MIN_HISTORY_WEEKS = 52  # ... and its model's training window has at least this many panel weeks
CATALOG_REFIT_WEEKS = 13  # fits are cached on the rolling-origin refit grid (forecast.refit_dates), extended back


def catalog_train_ends(panel, refit_weeks=CATALOG_REFIT_WEEKS):
    """Training ends the catalogue may use: the forecast's refit grid (anchored at its first refit) extended back to
    the panel start, up to MODEL_END, plus MODEL_END itself (the fit 2020 storms use)."""
    grid = F.refit_dates(refit_weeks=refit_weeks)
    step, first = pd.Timedelta(weeks=refit_weeks), panel.week.min()
    back = [grid[0] - k * step for k in range(1, 1000) if grid[0] - k * step >= first]
    return sorted({*back, *grid, pd.Timestamp(MODEL_END)})


def catalog_storms(ib, units, fixed_km=150.0):
    """Every WP IBTrACS storm 2016-2020 whose whole-track gale swath meets PHL land: SID, name, season, max wind,
    closest approach (hourly track, km to the nearest unit polygon; ties -> earliest) and its DOH week (= origin).
    IBTrACS times are UTC, as in the panel's storm features."""
    land = units.to_crs(CRS_M).union_all()
    land_s = land.simplify(1000)
    rows, sw = [], {}
    for sid, tr in ib.groupby("SID", sort=False):
        tr = tr.sort_values("time").reset_index(drop=True)
        wmax = tr.wind_kt.max()
        pts = gpd.GeoSeries(gpd.points_from_xy(tr.LON, tr.LAT), crs=4326).to_crs(CRS_M)
        if pts.distance(land_s).min() > 1500e3:
            continue
        g = S.swath(tr, fixed_km) if wmax >= CATALOG_MIN_WIND_KT else None
        hit = g is not None and g.intersects(land)
        it = S.interpolate(S.gale_radius(tr, fixed_km))
        d = gpd.GeoSeries(gpd.points_from_xy(it.LON, it.LAT), crs=4326).to_crs(CRS_M).distance(land_s).to_numpy() / 1000
        i = int(np.argmin(d))
        rows.append(dict(sid=sid, name=str(tr.NAME.iloc[0]), season=int(tr.SEASON.iloc[0]), max_wind_kt=wmax,
                         closest_time=it.time.iloc[i], closest_km=float(d[i]), origin=week_ending(it.time.iloc[i]),
                         swath_hits_land=bool(hit)))
        if hit:
            sw[sid] = g
    return pd.DataFrame(rows), sw


def run_catalog(panel, units, cells, nodes_final, am=None, fixed_km=150.0, log=print):
    """Unshifted scenario for every catalogue storm (see catalog_storms), the 4 backtest storms excluded. The forecast
    origin is the DOH week of closest approach; the model is the latest catalog_train_ends fit <= origin (never past
    MODEL_END), so no training target is after the origin; storms whose fit has < CATALOG_MIN_HISTORY_WEEKS panel weeks
    are skipped and listed. Flood on roads and friction cells: NOAH 25-yr proxy inside the gale swath (there is no
    Sentinel-1 map for these storms). Columns as scenarios.parquet plus sid, name, season (storm = sid)."""
    import time

    t0 = time.time()
    ib = S.load_ibtracs()
    if ib is None:
        return missing("catalog", "IBTrACS missing"), am
    cat, sw_by = catalog_storms(ib, units, fixed_km)
    back = {f"{s['name']}_{s['season']}" for s in STORMS.values()}
    cat["backtest"] = (cat["name"] + "_" + cat.season.astype(str)).isin(back)
    ends = catalog_train_ends(panel)
    weeks = np.sort(panel.week.unique())
    cat["train_end"] = [max([e for e in ends if e <= o], default=pd.NaT) for o in cat.origin]
    cat["history_weeks"] = [int((weeks <= e).sum()) if pd.notna(e) else 0 for e in cat.train_end]
    reason = np.select([~cat.swath_hits_land, cat.backtest, cat.origin > weeks.max(),
                        cat.history_weeks < CATALOG_MIN_HISTORY_WEEKS],
                       ["gale swath misses PHL land", "backtest storm (in scenarios.parquet)", "origin after the panel",
                        f"< {CATALOG_MIN_HISTORY_WEEKS} weeks of history"], "")
    cat["status"] = np.where(reason == "", "included", "skipped")
    cat["reason"] = reason
    cat = cat.sort_values("closest_time").reset_index(drop=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)
    cat.drop(columns=["backtest"]).to_csv(APP_DATA / "catalog_storms.csv", index=False)
    todo = cat[cat.status == "included"]
    hits = cat[cat.swath_hits_land & ~cat.backtest]
    sk = hits[hits.status == "skipped"]
    log(f"  {len(hits)} storms 2016-2020 with a gale swath on PHL land (backtests excluded): {len(todo)} included, "
        f"{len(hits) - len(todo)} skipped: {', '.join(sk['name'] + ' ' + sk.season.astype(str) + ' (' + sk.reason + ')')}")
    if am is None:
        am = AccessModel(cells, units=units)
    fits, cals = {}, {}  # by training end (R calibrated as in run_all)
    rows, adm3_rows, tracks, ferry_rows, swaths, methods = [], [], [], [], [], []
    for _, c in todo.iterrows():
        end = c.train_end
        if end not in fits:
            t = time.time()
            fits[end] = F.fit_at(panel, end)
            cals[end] = F.surge_calibrator(end)  # None before enough past outcomes: R stays raw (flagged)
            log(f"  fit to {end.date()} ({time.time() - t:.0f}s, graph {fits[end]['meta']['n_edges']} edges)")
        fitted = dict(fits[end], origin=c.origin)
        assert fitted["train_end"] <= c.origin and fitted["train_end"] <= pd.Timestamp(MODEL_END)
        tr = ib[ib.SID == c.sid].sort_values("time").reset_index(drop=True)
        sw = sw_by[c.sid]
        fc = case_columns(F.calibrate_R(F.predict_at(fitted), cals[end]))  # unshifted: the panel's own origin-week features
        acc, src, n_cancel = None, "none", 0
        if am.ok:
            acc, a3, src, n_cancel, keep, mrow = track_access(am, sw, None, True, cells)
            adm3_rows.append(adm3_priority(a3, fc).assign(storm=c.sid, dlat=0.0, dlon=0.0, sid=c.sid, name=c["name"], season=c.season))
            methods.append(dict(kind="scenario", storm=c.sid, dlat=0.0, dlon=0.0, name=c["name"], season=c.season, **mrow))
            if am.ferries is not None:
                ferry_rows.append(pd.DataFrame({"route": am.ferries.route_name, "storm": c.sid, "dlat": 0.0, "dlon": 0.0,
                                                "cancelled": ~keep & am.net.f_ok, "snapped": am.net.f_ok}))
        rows.append(scenario_rows(fc, acc, nodes_final, units, storm=c.sid, dlat=0.0, dlon=0.0, flood_source=src,
                                  ferries_cancelled=n_cancel, origin=c.origin, train_end=fitted["train_end"],
                                  hospital_source=getattr(am, "hosp_source", None), flag_2020=c.origin > pd.Timestamp(MODEL_END),
                                  sid=c.sid, name=c["name"], season=c.season, closest_time=c.closest_time,
                                  closest_km=c.closest_km, graph_edges=fitted["meta"]["n_edges"]))
        tracks.append(tr[["LAT", "LON", "time", "wind_kt"]].assign(storm=c.sid, dlat=0.0, dlon=0.0, sid=c.sid, name=c["name"], season=c.season))
        g = gpd.GeoSeries([sw], crs=CRS_M).to_crs(4326).simplify(0.02).iloc[0]
        swaths.append(dict(storm=c.sid, dlat=0.0, dlon=0.0, sid=c.sid, name=c["name"], season=c.season, wkt=g.wkt))
    if not rows:
        return missing("catalog", "no catalogue storm could be scored"), am
    m = pd.DataFrame(methods) if methods else None
    out = write_scenario_outputs("_catalog", rows, adm3_rows, tracks, swaths, ferry_rows, am, m)
    record("catalog", True, f"{out.storm.nunique()} storms ({len(fits)} fits), {len(hits) - len(todo)} skipped; "
                            f"{time.time() - t0:.0f}s")
    log(f"  catalogue: {out.storm.nunique()} storms, {len(fits)} fits, {time.time() - t0:.0f}s")
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


def _rank_change(R, P0, A):
    """Kendall's tau and top-10 overlap of P = R x A against the base P0 (indexed by unit)."""
    P = R * A.reindex(P0.index)
    ok = P0.notna() & P.notna()
    tau = stats.kendalltau(P0[ok], P[ok]).statistic if ok.sum() > 5 else np.nan
    return dict(kendall_tau=tau, top10_overlap=len(set(P0[ok].nlargest(10).index) & set(P[ok].nlargest(10).index)))


def sensitivity(am, scen, units, fixed_km=150.0, ib=None):
    """Rank stability of P (Kendall's tau vs the base settings) for each storm's unshifted track; the *_raster columns
    run the same variant on the raster method, against the raster method's own base P (R x A_raster)."""
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
        if "A_raster" in base:
            base = base.assign(P_raster=base.R * base.A_raster)
        tr = S.storm_track(key, ib=ib)
        for name, kw in variants.items():
            kw = dict(kw)
            sw = S.swath(tr, kw.pop("fixed", fixed_km))
            b, st, cut, _, _, keep = am.run(sw, key, False, **kw)
            A = AC.summarise(am.cells, b, st, cut, "unit_id").set_index("unit_id").A
            row = dict(storm=STORMS[key]["local"], variant=name, **_rank_change(base.R, base.P, A), mean_A=float(A.mean()))
            ras = am.run_raster(sw, key, False, keep, **{k: v for k, v in kw.items() if k != "ferry_rule"})
            if ras is not None and "P_raster" in base:  # the same variant on the raster method, against its own base
                Ar = AC.summarise(am.cells, *ras, "unit_id").set_index("unit_id").A
                rr = _rank_change(base.R, base.P_raster, Ar)
                row |= dict(kendall_tau_raster=rr["kendall_tau"], top10_overlap_raster=rr["top10_overlap"], mean_A_raster=float(Ar.mean()))
            rows.append(row)
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
