"""scripts/make_results.py on the real build outputs: stats() and the report / 20-slide builders, on the full build and
on a minimal build (optional columns, the catalogue, benchmarks, raster method, leptospirosis and calibration removed in
memory). No figure is drawn and nothing is written: the builders get placeholder figure paths, and the status registry
(stats() records the EMS check) goes to a temporary file."""

import copy

import pytest

from conftest import APP_DATA, PROCESSED, need

pytestmark = [pytest.mark.data, pytest.mark.usefixtures("isolated_status")]

FIGS = ["timeline", "coverage", "wis", "rel", "fan", "leadlag", "priority", "access", "scatter", "valid", "s1", "s1ems",
        "network", "rolling", "methods", "catalog", "lepto"]
# scenario columns that stats() itself treats as optional (raster method, HRSL, calibration)
OPTIONAL_COLS = ["A_lo", "A_hi", "A_raster", "R_raw", "pop_cut_raster", "pop_cut_u5", "pop_cut_60", "pop_cells"]
OPTIONAL_FILES = ["methods", "methods_cat", "models", "bench_summary", "scen_cat", "cat_storms", "s1_adm3", "lepto_city",
                  "lepto_nat", "lepto_did", "lepto_events"]


@pytest.fixture(scope="module")
def built():
    """make_results with its raw-file readers (IBTrACS, DOH CSV, census, S1 tiles, eval quantiles) memoised for this
    module: they do not depend on the in-memory variants, and re-reading them for every variant costs ~3 s each."""
    need(PROCESSED / "panel.parquet", APP_DATA / "scenarios.parquet", APP_DATA / "eval_summary.csv", PROCESSED / "status.json",
         APP_DATA / "ferries.parquet", APP_DATA / "leadlag_meta.json")
    import functools

    import make_results as M

    data_keys = {}

    def stats_data(d, k, _real=M.stats_data):
        if not data_keys:
            k0 = {}
            _real(d, k0)
            data_keys.update(k0)
        k.update(data_keys)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(M, "s1_ems_agreement", functools.cache(M.s1_ems_agreement))
        mp.setattr(M, "census_age", functools.cache(M.census_age))
        split = functools.cache(lambda bench, _real=M.median_wis_split: _real(list(bench)))
        mp.setattr(M, "median_wis_split", lambda bench, _s=split: _s(tuple(bench)))
        mp.setattr(M, "stats_data", stats_data)
        yield M, M.load()


def without(full, *keys, cols=False, cal=False):
    """A shallow copy of the loaded outputs with optional parts removed (as if that build part never ran)."""
    d = copy.copy(full)
    for key in keys:
        d[key] = {} if key == "models_meta" else None
    if cols:
        d["scen"] = full["scen"].drop(columns=[c for c in OPTIONAL_COLS if c in full["scen"]])
    if cal:
        d["cal"] = {m: full["cal"][m] for m in ("xgb", "xgb_nograph")}
        d["rel"] = full["rel"][[c for c in full["rel"].columns if not c.endswith("_cal")]]
    return d


def figs():
    return {f: f"../figures/{f}.png" for f in FIGS}


def slides(M, d):
    import results_slides as RS

    k = M.stats(d)
    return k, RS.slides_html(d, k, figs())


def report(M, d, k):
    import results_pages as RP

    return RP.report_html(d, k, figs())


def test_full_build_stats_and_documents(built):
    M, d = built
    k, s = slides(M, copy.copy(d))
    r = report(M, d, k)
    assert k["n_units"] == 85 and k["n_weeks"] == 262
    assert k["relwis"] > 0 and k["n_scored"] > 0
    assert k["raster_ok"] and k["cat_ok"] and k["lepto_ok"] and k["models_ok"] and k["cal_ok"]
    assert s.count("<section class='s") == 20
    assert r.count("<section class='page") >= 10


def test_minimal_build_still_produces_20_slides(built):
    M, full = built
    d = without(full, *OPTIONAL_FILES, "models_meta", cols=True, cal=True)
    k, s = slides(M, d)
    assert not (k["raster_ok"] or k["cat_ok"] or k["lepto_ok"] or k["models_ok"] or k["cal_ok"])
    assert k["bench_missing"] == list(M.BENCH_LABEL)
    assert s.count("<section class='s") == 20
    assert "Not run in this build" in s  # the leptospirosis slide says so instead of failing




@pytest.mark.parametrize("part", OPTIONAL_FILES + ["models_meta", "columns", "calibration"])
def test_documents_without_one_optional_part(built, part):
    M, full = built
    d = without(full, cols=part == "columns", cal=part == "calibration") if part in ("columns", "calibration") else without(full, part)
    k, s = slides(M, d)
    assert s.count("<section class='s") == 20
    assert report(M, d, k).count("<section class='page") >= 10
