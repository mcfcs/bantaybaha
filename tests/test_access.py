"""bantay.access: the cut-off rule, unit summaries, storm speed multipliers, the road + ferry network solver on a
four-node road, ferry cancellation, and the MAP friction raster method on a 5 x 5 GeoTIFF."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from bantay import access as AC
from bantay.config import CRS_M

pytestmark = [pytest.mark.usefixtures("isolated_status"),
              # cut_off computes inf - inf for cells with no route in both runs; the result is still correct
              pytest.mark.filterwarnings("ignore:invalid value encountered in subtract:RuntimeWarning")]
INF = np.inf


# ---------------------------------------------------------------- rules

def test_cut_off_rule():
    base = np.array([1.0, 1.0, 1.5, 0.2, 3.0, INF, 2.0, 0.5])
    storm = np.array([INF, 2.0, 3.0, 5.0, 5.9, INF, 2.0, 1.4])
    #                 no route  x2 +1h  x2 +1.5h  x25  x1.97  never reached  same  x2.8 +0.9h
    assert AC.cut_off(base, storm).tolist() == [True, False, True, True, False, False, False, False]
    assert AC.cut_off(np.array([3.0]), np.array([5.9]), ratio=1.9)[0]  # ratio 1.97 >= 1.9 and +2.9 h > 1 h
    assert not AC.cut_off(np.array([1.5]), np.array([3.0]), extra_h=1.5)[0]  # the extra time must exceed extra_h


def test_summarise_access_loss():
    cells = pd.DataFrame({"unit_id": ["A", "A", "A", "B", "B", "C"], "pop": [100.0, 300.0, 600.0, 50.0, 50.0, 10.0]})
    base = np.array([1.0, 2.0, INF, 0.5, 1.5, INF])
    storm = np.array([INF, 2.0, INF, 0.5, 1.5, INF])
    cut = AC.cut_off(base, storm)
    s = AC.summarise(cells, base, storm, cut).set_index("unit_id")
    assert s.loc["A", "pop"] == 1000 and s.loc["A", "pop_cut"] == 100
    assert s.loc["A", "A"] == pytest.approx(0.1)  # A = pop_cut / pop (people with no baseline route stay in pop)
    assert s.loc["A", "pop_no_access_base"] == 600
    assert s.loc["A", "base_hours"] == pytest.approx((1 * 100 + 2 * 300) / 400)  # population-weighted, finite only
    assert s.loc["B", "pop_cut"] == 0 and s.loc["B", "A"] == 0  # no cut cell -> 0, not NaN
    assert s.loc["B", "base_hours"] == pytest.approx(1.0)
    assert np.isnan(s.loc["C", "base_hours"]) and s.loc["C", "A"] == 0
    adm3 = AC.summarise(cells.assign(adm3_pcode=["m1", "m1", "m2", "m3", "m3", "m4"]), base, storm, cut, "adm3_pcode")
    assert adm3.set_index("adm3_pcode").A.to_dict() == {"m1": 0.25, "m2": 0.0, "m3": 0.0, "m4": 0.0}


def test_road_multiplier():
    roads = {"u": np.zeros(5)}
    in_sw = np.array([True, True, True, False, True])
    haz = np.array([3, 2, 1, 3, 255], "uint8")  # high, medium, low, high outside the swath, no map
    m, src = AC.road_multiplier(roads, in_sw, haz)
    assert m.tolist() == [0.0, 0.5, 1.0, 1.0, 1.0] and src == "noah_25yr_proxy"
    m, _ = AC.road_multiplier(roads, in_sw, haz, slow=0.25)
    assert m[1] == 0.25
    obs = np.array([False, False, True, True, False])
    m, src = AC.road_multiplier(roads, in_sw, haz, observed=obs)
    assert m.tolist() == [1.0, 1.0, 0.0, 0.0, 1.0] and src == "observed"  # observed flood wins, swath or not
    m, src = AC.road_multiplier(roads, in_sw, None)
    assert (m == 1).all() and src == "none"


# ---------------------------------------------------------------- network

LON = np.array([121.0, 121.1, 121.2, 121.3, 122.0])  # node 4: an island, reachable by ferry only
LAT = np.full(5, 14.0)


def roads():
    return dict(lon=LON, lat=LAT, u=np.array([0, 1, 2, 1]), v=np.array([1, 2, 3, 2]), km=np.array([10.0, 10.0, 10.0, 10.0]),
                speed=np.array([50.0, 50.0, 50.0, 10.0]),  # edge 3 is a slow parallel road 1-2
                mid_lon=np.array([121.05, 121.15, 121.25, 121.15]), mid_lat=np.full(4, 14.0))


def pts(lon, lat):
    return gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=4326)


def ferries(hours=2.0):
    f = pd.DataFrame({"from_lon": [121.3], "from_lat": [14.0], "to_lon": [122.0], "to_lat": [14.0], "hours": [hours],
                      "route_name": ["R1"]})
    return gpd.GeoDataFrame(f, geometry=[LineString([(121.3, 14.0), (122.0, 14.0)])], crs=4326)


@pytest.fixture
def net():
    cells = pts([121.0, 121.3, 122.0, 121.0], [14.0, 14.0, 14.0, 15.0])  # last cell is > 100 km from any road
    return AC.Network(roads(), ferries(), pts([121.0], [14.0]), cells)


def test_network_solve_hours(net):
    t = net.solve(net.road_hours())
    assert t[0] == pytest.approx(0.0)  # at the hospital
    assert t[1] == pytest.approx(0.6)  # 3 x 10 km at 50 km/h; the slow parallel edge is ignored
    assert t[2] == pytest.approx(0.6 + 2.0, rel=1e-6)  # + ferry crossing (ports on road nodes: no port access time)
    assert t[3] == INF  # no road within MAX_SNAP_KM
    assert net.solve(net.road_hours() * 2)[1] == pytest.approx(1.2)


def test_network_cut_edge_and_cancelled_ferry(net):
    base = net.solve(net.road_hours())
    m = np.array([1.0, 0.0, 1.0, 1.0])  # main 1-2 road cut: traffic takes the slow parallel road
    t = net.solve(net.road_hours(m))
    assert t[1] == pytest.approx(0.2 + 1.0 + 0.2)
    m = np.array([1.0, 0.0, 1.0, 0.0])  # both 1-2 roads cut
    t = net.solve(net.road_hours(m))
    assert t[1] == INF and t[2] == INF
    assert AC.cut_off(base, t).tolist() == [False, True, True, False]
    t = net.solve(net.road_hours(), ferry_keep=np.array([False]))
    assert t[1] == pytest.approx(0.6) and t[2] == INF
    t = net.solve(net.road_hours(np.array([0.5, 1, 1, 1])))
    assert t[1] == pytest.approx(0.4 + 0.2 + 0.2)  # slowed edge: half speed


def test_network_speed_factor():
    n = AC.Network(roads(), None, pts([121.0], [14.0]), pts([121.3], [14.0]), speed_factor=2.0)
    assert n.solve(n.road_hours())[0] == pytest.approx(0.3)


def test_ferry_keep_mask_and_edges_in():
    f = pd.concat([ferries(), ferries()], ignore_index=True)
    f.loc[1, ["from_lon", "to_lon"]] = [124.0, 125.0]
    f = gpd.GeoDataFrame(f, geometry=[LineString([(121.3, 14.0), (122.0, 14.0)]), LineString([(124.0, 14.0), (125.0, 14.0)])], crs=4326)
    sw = gpd.GeoSeries([Point(121.65, 14.0)], crs=4326).to_crs(CRS_M).buffer(20_000).iloc[0]  # covers mid-route only
    assert AC.ferry_keep_mask(f, sw).tolist() == [False, True]
    assert AC.ferry_keep_mask(f, sw, rule="ports").tolist() == [True, True]  # no port inside
    assert AC.ferry_keep_mask(f, None).tolist() == [True, True]
    port = gpd.GeoSeries([Point(121.3, 14.0)], crs=4326).to_crs(CRS_M).buffer(5_000).iloc[0]
    assert AC.ferry_keep_mask(f, port, rule="ports").tolist() == [False, True]
    r = roads()
    assert AC.edges_in(port, r).tolist() == [False, False, False, False]
    big = gpd.GeoSeries([Point(121.0, 14.0)], crs=4326).to_crs(CRS_M).buffer(8_000).iloc[0]
    assert AC.edges_in(big, r).tolist() == [True, False, False, False]
    assert not AC.edges_in(None, r).any()


def test_speeds_are_positive_and_links_not_faster():
    assert all(v > 0 for v in AC.SPEED.values())
    assert all(AC.SPEED[f"{k}_link"] <= AC.SPEED[k] for k in AC.SPEED if f"{k}_link" in AC.SPEED)


# ---------------------------------------------------------------- raster method (MAP friction) on a 5 x 5 grid

RES = 0.01  # degrees per cell
X0, Y0 = 121.0, 14.05  # top-left corner
LAND_MIN_PER_M = 0.001


def cell_centre(r, c):
    return X0 + (c + 0.5) * RES, Y0 - (r + 0.5) * RES


@pytest.fixture
def grid(tmp_path, monkeypatch):
    """5 x 5 friction GeoTIFF: land in columns 0-2 (unit L) and column 4 (unit R), sea (MAP's constant) in column 3."""
    import rasterio
    from rasterio.transform import from_origin

    fr = np.full((5, 5), LAND_MIN_PER_M, "float32")
    fr[:, 3] = AC.SEA_MIN_PER_M
    p = tmp_path / "friction.tif"
    with rasterio.open(p, "w", driver="GTiff", height=5, width=5, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(X0, Y0, RES, RES), nodata=-9999) as dst:
        dst.write(fr, 1)
    monkeypatch.setattr(AC, "FRICTION", p)
    units = gpd.GeoDataFrame({"unit_id": ["L", "R"]}, crs=4326, geometry=[
        box(X0 + 0.0005, Y0 - 5 * RES + 0.0005, X0 + 3 * RES - 0.0005, Y0 - 0.0005),
        box(X0 + 4 * RES + 0.0005, Y0 - 5 * RES + 0.0005, X0 + 5 * RES - 0.0005, Y0 - 0.0005)])
    hosp = pts(*zip(cell_centre(2, 0)))
    cells = pts(*zip(cell_centre(2, 2), cell_centre(2, 4), cell_centre(0, 3)))  # land L, land R, a sea cell
    return units, hosp, cells


def cell_hours(lat):
    return LAND_MIN_PER_M * RES * 111320.0 * np.sqrt(np.cos(np.radians(lat))) / 60.0


def test_friction_grid_cost_distance(grid):
    units, hosp, cells = grid
    g = AC.friction_grid(units, hosp, cells)
    assert len(g.land_idx) == 20  # 4 land columns x 5 rows; the sea column is impassable
    assert g.n_snapped == 1  # the population cell on the sea moves to the nearest land cell
    t = g.solve()
    c = cell_hours(cell_centre(2, 0)[1])
    assert t[0] == pytest.approx(2 * c, rel=1e-3)  # two orthogonal steps of equal cost
    assert t[1] == INF  # island R: no ferry
    assert g.c_ok[2] and g.c_idx[2] in set(g.land_idx)  # the sea cell's people sit on a land cell
    assert g.solve(speed_factor=2.0)[0] == pytest.approx(c, rel=1e-3)


def test_friction_grid_flood_rules(grid):
    units, hosp, cells = grid
    g = AC.friction_grid(units, hosp, cells)
    rr, cc = np.divmod(g.land_idx, 5)
    c = cell_hours(cell_centre(2, 0)[1])
    mult = np.where((rr == 2) & (cc == 1), 0.0, 1.0)  # flood the cell between hospital and people
    assert g.solve(mult)[0] == pytest.approx(2 * np.sqrt(2) * c, rel=1e-3)  # detour on two diagonals
    mult = np.where(cc == 1, 0.0, 1.0)  # the whole column flooded
    base, storm = g.solve(), g.solve(mult)
    assert storm[0] == INF and AC.cut_off(base, storm)[0]
    mult = np.where((rr == 2) & (cc == 2), 0.0, 1.0)  # the people's own cell flooded
    assert g.solve(mult)[0] == INF
    slowed = np.where(cc == 1, 0.5, 1.0)
    assert g.solve(slowed)[0] == pytest.approx((c + 2 * c) / 2 * 2, rel=1e-3)  # column 1 costs 2c per cell at half speed


def test_friction_grid_flooded_hospital_is_not_a_start(grid):
    units, hosp, cells = grid
    two = pts(*zip(cell_centre(2, 0), cell_centre(0, 0)))
    g = AC.friction_grid(units, two, cells)
    rr, cc = np.divmod(g.land_idx, 5)
    c = cell_hours(cell_centre(2, 0)[1])
    t = g.solve(np.where((rr == 2) & (cc == 0), 0.0, 1.0))  # the nearer hospital is flooded
    assert t[0] == pytest.approx(2 * np.sqrt(2) * c, rel=1e-3)  # people go to the other one, two diagonals away


def test_friction_grid_every_hospital_flooded(grid):
    g = AC.friction_grid(*grid)
    rr, cc = np.divmod(g.land_idx, 5)
    assert (g.solve(np.where((rr == 2) & (cc == 0), 0.0, 1.0)) == INF).all()


def test_friction_grid_ferry_line(grid):
    units, hosp, cells = grid
    f = gpd.GeoDataFrame({"from_lon": [cell_centre(2, 2)[0]], "from_lat": [cell_centre(2, 2)[1]],
                          "to_lon": [cell_centre(2, 4)[0]], "to_lat": [cell_centre(2, 4)[1]], "hours": [3.0]},
                         geometry=[LineString([cell_centre(2, 2), cell_centre(2, 4)])], crs=4326)
    g = AC.friction_grid(units, hosp, cells, f)
    t = g.solve()
    assert np.isfinite(t[1]) and t[1] > t[0] + 1.5  # the sea cell costs 3 h / 2-cell line
    assert g.solve(ferry_keep=np.array([False]))[1] == INF  # cancelled route closes the sea again
    g2 = AC.friction_grid(units, hosp, cells, f, ferry_ok=np.array([False]))  # a route that never snapped
    assert g2.solve()[1] == INF


def test_friction_grid_missing_raster(grid, monkeypatch, tmp_path):
    from bantay import config

    monkeypatch.setattr(AC, "FRICTION", tmp_path / "absent.tif")
    assert AC.friction_grid(*grid) is None
    assert config.status()["map_friction"]["available"] is False
