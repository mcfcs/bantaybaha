# Panel data card

`data/processed/panel.parquet`: 85 harmonised units x 262 weeks (2016-01-10 to 2021-01-10, weeks end Sunday). Built by `python scripts/build.py panel`.

Units: COD-AB ADM2 with Maguindanao del Norte/Sur merged, Special Geographic Area -> Cotabato, City of Isabela -> Basilan (`data/crosswalks/adm2_to_unit.csv`). 2020 is COVID-depressed: used for access scenarios only, never as a forecast target.

| column | source | non-null | meaning |
|---|---|---|---|
| `cases` | dengue_hdx | 99% | dengue cases in the week; NaN unless every member reporting unit reported |
| `n_reporting` | dengue_hdx | 100% | member reporting units with a row that week |
| `n_members` | dengue_hdx | 100% | member reporting units (provinces + cities folded in) |
| `pop` | census2020 / worldpop | 100% | 2020 population (census; WorldPop if the census table is missing) |
| `incidence` | derived | 99% | cases per 100,000 |
| `storm_min_dist_km` | ibtracs | 100% | distance from the nearest WP track fix that week to the unit polygon (2000 = none within 300 km of PHL) |
| `storm_gale_hit` | ibtracs | 100% | 1 if the unit was inside a gale-radius swath that week (R34 / TOKYO_R30 / 150 km fallback) |
| `storm_max_wind_near_kt` | ibtracs | 100% | max wind of fixes within 300 km of the unit |
| `storm_n` | ibtracs | 100% | distinct storms within 300 km |
| `chirps_7d` | chirps | 99% | area-mean rainfall, Mon-Sun sum (mm) |
| `chirps_3d` | chirps | 99% | area-mean rainfall, Fri-Sun sum (mm) |
| `chirps_max1d` | chirps | 100% | wettest day of the week (mm) |
| `imerg_7d` | imerg (GEE) | 99% | as chirps_7d, from GPM IMERG V07 |
| `imerg_3d` | imerg (GEE) | 99% | as chirps_3d, from GPM IMERG V07 |
| `imerg_max1d` | imerg (GEE) | 100% | as chirps_max1d, from GPM IMERG V07 |
| `river_up_7d` | hydrorivers + chirps | 99% | discharge-weighted upstream-mean weekly rain over the unit's reaches (mm) |
| `river_excess_7d` | hydrorivers + chirps | 99% | river_up_7d minus chirps_7d: rain arriving from upstream |
| `hazard_any_5yr` | noah | 82% | share of population in any 5-yr flood hazard class (NaN = no NOAH map) |
| `hazard_high_5yr` | noah | 82% | share of population in the high 5-yr class |
| `hazard_any_25yr` | noah | 87% | share of population in any 25-yr flood hazard class (NaN = no NOAH map) |
| `hazard_high_25yr` | noah | 87% | share of population in the high 25-yr class |
| `storm_hazard_exposure` | ibtracs x noah | 87% | storm_gale_hit x hazard_any_25yr |
| `s1_flood_frac` | sentinel-1 (GEE) | 3% | observed new-flood share of land, on the 4 weeks from the one containing landfall + S1_AFTER_DAYS (when the map is known); NaN otherwise |
| `s1_flood_pop` | sentinel-1 (GEE) | 3% | people in observed new flood (WorldPop), same weeks |

## Input status

| input | available | detail |
|---|---|---|
| access | yes | road graph + 2199 hospitals (osm+noah_fallback) + population cells |
| access_network | yes | 2198 hospital nodes, 340,114/369,121 cells within 5 km of a road, 108 ferry routes snapped |
| benchmark | yes | NCR share cut off 29.7% |
| census2020 | yes | data\raw\census2020\2020_CPH_SexAge_Popn_Mun_Admin3.xlsx |
| census_population | yes | 108.67 M people in 85 units |
| chirps | yes | data\raw\chirps |
| cod_ab | yes | phl_admin_boundaries.gdb.zip |
| dengue_hdx | yes | 126 reporting units, 261 weeks |
| dengue_unit_week | yes | 215 NaN unit-weeks of 22270 |
| ems_EMSR312 | yes | 12 packages |
| forecast_eval | yes | relWIS xgb/naive = 0.544, cov90 = 0.852 |
| hospitals | yes | fallback: 2199 hospitals ({'osm': 1679, 'noah': 520}), duplicates < 300 m dropped |
| hydrorivers | yes | data\raw\hydrorivers\HydroRIVERS_v10_au_shp.zip |
| ibtracs | yes | 137 storms 2016-2020 |
| imerg | yes | data\raw\imerg |
| nhfr | **missing** | NHFR manual download not in data/raw/nhfr/; using HOT OSM + NOAH facilities (fallback) |
| noah_25yr | yes | 72 zips |
| noah_5yr | yes | 67 zips |
| noah_hazard_shares | yes | 74/85 units have a 25-yr hazard share (others NaN = no map) |
| osm | yes | data\raw\osm\philippines-latest.osm.pbf |
| panel | yes | 85 units x 262 weeks |
| psgc | **missing** | data\raw\psgc not found |
| road_graph | yes | 1,717,666 nodes, 2,132,776 edges from 1,084,312 OSM ways |
| roroph | yes | data\raw\roroph\roro_routes.rda |
| s1_flood_ompong | yes | 48 tiles |
| s1_flood_rolly | yes | 68 tiles |
| s1_flood_tisoy | yes | 80 tiles |
| s1_flood_ulysses | yes | 55 tiles |
| scenarios | yes | 4 storms x 15 tracks; access on |
| sensitivity | yes | 9 variants x 4 storms |
| worldpop | yes | data\raw\worldpop\phl_ppp_2020_UNadj.tif |
