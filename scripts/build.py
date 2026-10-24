"""Build everything the Bantay-Baha dashboard reads, from data/raw/ to data/processed/.

Usage:
    python scripts/build.py                 # all stages
    python scripts/build.py panel forecast  # selected stages
    python scripts/build.py --force crosswalk   # rebuild the crosswalks (normally written once and reused)

Stages (in order):
  crosswalk  harmonised 2016-2020 units: data/crosswalks/*.csv, data/processed/units.gpkg
  panel      unit x week panel + data card: data/processed/panel.parquet, panel_card.md
  leadlag    final lead-lag graph (PCMCI+, bootstrap) and the cross-correlation baseline
  forecast   rolling-origin evaluation 2018-2019: WIS, coverage, relative WIS, ablation, surge calibration (raw and
             isotonic-recalibrated R); persists the full quantiles and cum4 forecasts, then runs `ensemble`
  ensemble   re-score without refitting: xgb / naive + any bench_<model>.parquet + their median ensemble
  scenarios  access loss (network + raster methods) + priority for the 4 typhoons x shifted tracks, validation,
             sensitivity, benchmark, Sentinel-1 flood per municipality
  catalog    unshifted scenario for every other 2016-2020 storm whose gale swath meets PHL land (*_catalog files)
  app        small files for the map (simplified units)
  lepto      leptospirosis lag analysis: national (Mendeley) + 12 CCHAIN cities, typhoon event study (stretch goal)

Inputs that are not on disk (GEE sources, PSGC, NHFR, or anything still downloading) are skipped with a warning and
their outputs are NaN / marked missing in data/processed/status.json. Re-run after they arrive; no code changes needed.
"""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bantay import config as C  # noqa: E402
from bantay import units as U, panel as PN, leadlag as LL, forecast as F, scenarios as SC, grids, flood  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", message="In analysis mode")  # tigramite shape notice (T < N is expected)
STAGES = ["crosswalk", "panel", "leadlag", "forecast", "ensemble", "scenarios", "catalog", "app", "lepto"]


def stage_crosswalk(a):
    xw2, _ = U.build_crosswalks(force=a.force)
    if xw2 is None:
        raise SystemExit("COD-AB and the dengue file are needed to write the crosswalks, which every later stage reads (see warnings above)")
    U.check_psgc(xw2)
    U.build_units_geometry(force=a.force)


def stage_panel(a):
    p = PN.build_panel()
    print(f"  panel {p.shape}, cases non-null {p.cases.notna().mean():.1%}; card: {PN.CARD.relative_to(ROOT)}")


def stage_leadlag(a):
    p = PN.load_panel()
    out = []
    for method, boot in (("pcmciplus", a.boot), ("xcorr", 0)):
        edges, nodes, meta = LL.learn(p, C.MODEL_END, method=method, boot=boot)
        print(f"  {method}: {meta}")
        edges.to_parquet(C.APP_DATA / f"leadlag_edges_{method}.parquet")
        nodes.to_parquet(C.APP_DATA / f"leadlag_nodes_{method}.parquet")
        out.append(meta)
    (C.APP_DATA / "leadlag_meta.json").write_text(json.dumps(out, indent=1))


def stage_forecast(a):
    p = PN.load_panel()
    t = time.time()
    fc, graphs = F.rolling_origin(p, refit_weeks=a.refit_weeks)
    sc = F.score(fc)
    summ = F.summarise(sc)
    cal, rel, cum4 = F.surge_calibration(fc)
    print(f"  rolling origin done in {time.time() - t:.0f}s, {len(sc):,} scored forecasts")
    print(summ[["n", "WIS xgb", "WIS naive", "relWIS xgb/naive", "relWIS xgb/nograph", "relWIS xgb/noenv", "cov50 xgb", "cov90 xgb", "cov90 conformal"]].round(3).to_string())
    print("  surge R calibration:", json.dumps({k: cal[k] for k in ("xgb", "xgb_nograph")}))
    cb = cal["calibrated"]
    print(f"  recalibrated R (isotonic, past forecasts only): {cb['n_uncalibrated']} of {cb['n_scored']} scored rows left raw "
          f"(< {cb['min_rows']} past outcomes); Brier {cb['all_rows']['brier_raw']:.4f} -> {cb['all_rows']['brier_cal']:.4f}")
    print(rel.round(3).to_string(index=False))
    cum4.to_parquet(C.APP_DATA / F.CUM4_FILE)  # read by scenarios (forecast.surge_calibrator)
    F.eval_quantiles(fc).to_parquet(C.APP_DATA / "eval_quantiles.parquet")  # read by the ensemble stage
    summ.to_csv(C.APP_DATA / "eval_summary.csv")
    rel.to_csv(C.APP_DATA / "surge_reliability.csv", index=False)
    (C.APP_DATA / "surge_calibration.json").write_text(json.dumps(cal, indent=1))
    sc.to_parquet(C.APP_DATA / "eval_scores.parquet")
    # compact forecasts for fan charts: 5/25/50/75/95% for each model
    keep = {"q05": 2, "q25": 6, "q50": F.IQ50, "q75": 16, "q95": 20}
    fcp = fc[fc.horizon != "cum4"].copy()
    pop = fcp["pop"].to_numpy()
    for m in F.MODELS:
        cases = F.to_cases(pd.DataFrame(fcp[m].tolist()).to_numpy(), pop)
        for k, i in keep.items():
            fcp[f"{m}_{k}"] = cases[:, i]
    fcp["cases"] = np.expm1(fcp.target) * pop / 1e5
    fcp.drop(columns=list(F.MODELS)).assign(horizon=lambda d: d.horizon.astype(int)).to_parquet(C.APP_DATA / "eval_forecasts.parquet")
    pd.DataFrame([g[2] for g in graphs]).to_csv(C.APP_DATA / "eval_graphs.csv", index=False)
    C.record("forecast_eval", True, f"relWIS xgb/naive = {summ.loc['all', 'relWIS xgb/naive']:.3f}, "
                                    f"cov90 = {summ.loc['all', 'cov90 xgb']:.3f}")
    if "ensemble" not in a.stages:
        stage_ensemble(a)


def stage_ensemble(a):
    qf = C.APP_DATA / "eval_quantiles.parquet"
    if not qf.exists():
        return C.missing("forecast_eval", f"{qf.relative_to(ROOT)} not found: run `build.py forecast` first")
    tab, bands, meta = F.evaluate_models(pd.read_parquet(qf))
    tab.to_csv(C.APP_DATA / "eval_models.csv", index=False)
    (C.APP_DATA / "eval_models.json").write_text(json.dumps(meta, indent=1, default=str))
    out = C.APP_DATA / "eval_forecasts_models.parquet"
    if bands is not None:
        bands.to_parquet(out)
    elif out.exists():
        out.unlink()  # no benchmark files any more: drop stale bands
    print(tab[tab.horizon == "all"].round(3).to_string(index=False))
    nb = len(meta["benchmarks"])
    ok = [m for m, v in meta["benchmarks"].items() if "error" not in v and "ignored" not in v]  # variants are not benchmarks
    if ok:
        C.record("bench_models", True, f"{', '.join(ok)}; ensemble {F.ENSEMBLE} = median of {meta['ensemble']['members']}")
    else:
        C.missing("bench_models", f"no usable {F.BENCH_GLOB} in data/processed/app ({nb} found): no benchmark or ensemble yet")


def population_cells(u, adm3):
    """1 km WorldPop cells with Meta HRSL under-5 / 60+ people attached (NaN columns if HRSL is missing)."""
    cells = grids.build_pop_cells(u, adm3)
    v = grids.build_vulnerable_cells(cells)
    if v is not None:
        for c in SC.VULNERABLE:
            cells[c] = v[c].to_numpy()
    return cells


def stage_scenarios(a):
    p = PN.load_panel()
    u = U.load_units()
    adm3 = U.adm3_with_units()
    cells = population_cells(u, adm3)
    hz = flood.unit_hazard_shares(u)
    nodes = pd.read_parquet(C.APP_DATA / "leadlag_nodes_pcmciplus.parquet")
    edges = pd.read_parquet(C.APP_DATA / "leadlag_edges_pcmciplus.parquet")
    scen, am = SC.run_all(p, u, cells, hz, edges, nodes)
    m = C.APP_DATA / "access_methods.csv"
    if m.exists():  # network vs raster method: baseline agreement, then the observed tracks
        m = pd.read_csv(m)
        print(m[m.kind == "baseline"].dropna(axis=1).round(3).T.to_string(header=False))
        obs = m[(m.kind == "scenario") & (m.dlat == 0) & (m.dlon == 0)]
        print(obs[["storm", "flood_source", "mean_A_network", "mean_A_raster", "pop_cut_network", "pop_cut_raster",
                   "spearman_A_units"]].round(3).to_string(index=False))
    s1 = flood.s1_adm3_flood(adm3)
    if s1 is not None:
        s1.to_parquet(C.APP_DATA / "s1_adm3.parquet")
        print(f"  s1_adm3: {len(s1):,} rows; flooded people per storm (M):", (s1.groupby("storm").s1_flood_pop.sum() / 1e6).round(2).to_dict())
    v = SC.validate(p, scen)
    print(v.round(3).to_string())
    v.to_csv(C.APP_DATA / "validation.csv", index=False)
    if am.ok:
        s = SC.sensitivity(am, scen, u)
        if s is not None:
            print(s.groupby("variant")[["kendall_tau", "top10_overlap"]].mean().round(2).to_string())
            s.to_csv(C.APP_DATA / "sensitivity.csv", index=False)
        b = SC.metro_manila_benchmark(am, u)
        if b is not None:
            print(b.to_string())
            b.to_csv(C.APP_DATA / "benchmark_ncr.csv", index=False)


def stage_catalog(a):
    p = PN.load_panel()
    u = U.load_units()
    adm3 = U.adm3_with_units()
    cells = population_cells(u, adm3)
    nodes = pd.read_parquet(C.APP_DATA / "leadlag_nodes_pcmciplus.parquet")
    SC.run_catalog(p, u, cells, nodes)


def stage_app(a):
    u = U.load_units()
    s = u.copy()
    s["geometry"] = s.geometry.simplify(0.01)
    s.to_file(C.APP_DATA / "units_simplified.geojson", driver="GeoJSON")


def stage_lepto(a):
    from bantay import lepto

    nat, city, ev = lepto.run()
    for name, t in (("national", nat), ("city", city)):
        if t is not None:
            r = t[(t.exposure == "rain_7d") & (t.model == "joint") & (t.variant == t.variant.iloc[0])]
            print(f"  {name} rain lag profile (joint, IRR per {lepto.RAIN_PER:g} mm/week): "
                  + ", ".join(f"{'sum' if np.isnan(x.lag) else int(x.lag)}: {x.irr:.2f}" for x in r.itertuples()))
    print(f"  summary: {lepto.SUMMARY.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stages", nargs="*", default=STAGES, help=" ".join(STAGES))
    ap.add_argument("--force", action="store_true", help="rebuild crosswalks and unit geometry")
    ap.add_argument("--boot", type=int, default=20, help="PCMCI+ bootstrap samples for the final graph (0 = off)")
    ap.add_argument("--refit-weeks", type=int, default=13, help="rolling-origin refit interval")
    a = ap.parse_args()
    if set(a.stages) - set(STAGES):
        ap.error(f"unknown stage(s) {sorted(set(a.stages) - set(STAGES))}; choose from {STAGES}")
    C.ensure_dirs()
    for st in [s for s in STAGES if s in a.stages]:
        t = time.time()
        print(f"[{st}]")
        globals()[f"stage_{st}"](a)
        print(f"  ({time.time() - t:.0f}s)")
    missing = {k: v["detail"] for k, v in C.status().items() if not v["available"]}
    if missing:
        print("\nMissing inputs (outputs marked missing / NaN):")
        for k, v in sorted(missing.items()):
            print(f"  {k}: {v}")
