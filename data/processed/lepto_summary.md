# Leptospirosis: lagged rain and typhoon association (stretch goal)

_Written by `python scripts/build.py lepto` (`bantay/lepto.py`). Retrospective association, not a forecast; every number below is from the files in `data/processed/app/lepto_*`._

## Key findings

- **Cities (12, 2016-2020): rain is followed by leptospirosis (2-5 weeks later, 95% CI above 1).** Joint distributed-lag peak at lag 4: IRR 1.40 (1.29-1.52) per +50 mm/week; cumulative lags 0-6 2.45 (2.05-2.92). Peak with city-specific seasonality: lag 4, 1.41 (1.29-1.54); with the literal CCHAIN week label: lag 3 (1.39 (1.28-1.51)). A heavy-rain week (>= city p90) peaks at lag 4: 2.00 (1.61-2.48). The peak is 2 weeks later than the ~2-week peak of Matsushita et al. (2018); the week-label uncertainty (above) and any onset-to-report delay in PIDSR (not checked here) bear on that comparison.
- **National (2019-2020, 80 weeks): same direction.** Joint peak at lag 5: 1.68 (1.28-2.22) per +50 mm/week, cumulative 4.12 (2.41-7.03); with 2019 alone (52 weeks) the cumulative effect is 1.51 (0.76-3.00) (peak lag 5: 1.40 (1.00-1.96)), so much of the national signal comes from 2020 (COVID-era reporting): treat it as indicative.
- **Typhoon event study: mixed.** Rolly + Ulysses (2020): inside-swath cities had 4.31 (1.72-10.85) times the outside cities' obs/exp in weeks +1..+4 (pre-landfall placebo 1.20 (0.32-4.53), passes). Ompong + Tisoy: inside-swath cities had 0.81 (0.55-1.20) times the outside cities' obs/exp in weeks +1..+4 (pre-landfall placebo 2.36 (1.55-3.61), fails); weeks of heavy monsoon rain from late July 2018 had already raised Luzon/NCR cases. All four pooled: 1.22 (0.74-2.03); no general storm effect can be claimed.
- **Sentinel-1 flood vs cases: not estimable.** Few city-storm pairs show any observed flood (see section 3), so the flood-mediation step stays a literature assumption here.

## Data and week labels

- **National** (Mendeley Parreno, PIDSR national weekly): 80 weeks with both cases and CHIRPS rain (52 in 2019, 28 in 2020); 4,705 cases. 2020 has 24 unreported weeks and the COVID reporting collapse (a `covid` term from 2020-03-15). 5 weeks look incompletely reported (same-file dengue < 50% of the HDX national dengue that week) and are dropped in one sensitivity fit. Rain data stop in 2020, so 2021-2023 cannot be used.
- **Week labels** (`lepto_alignment.csv`): Mendeley MW w = week ending firstSunday + 7(w-1) days; its dengue column vs the HDX national sum r = 0.956 (vs 0.917 / 0.944 one week off). CCHAIN Monday date D -> DOH week ending D + 13 d: best shift for 7 cities at +13 d, 2 cities at +6 d, 1 city at +20 d on levels (mean r {'+13 d': 0.827, '+20 d': 0.749, '+6 d': 0.814, '-1 d': 0.733}; the median favours +6 d), and 7 cities at +13 d, 2 cities at +6 d, 1 city at -1 d on week-to-week differences, the sharper timing test (mean r {'+13 d': 0.382, '+20 d': 0.014, '+6 d': 0.255, '-1 d': 0.061}). The literal reading (D + 6) is a sensitivity fit; it shortens every lag by one week.
- **Cities** (Project CCHAIN PIDSR city-week, 12 cities, weeks 2016-01-03 to 2021-01-03): 1,698 cases; Iloilo City 646, Dagupan City 282, Davao City 204, City of Navotas 121, Cagayan de Oro City 114, Zamboanga City 89, City of Mandaluyong 82, City of Muntinlupa 62, Tacloban City 44, Legazpi City 28, Palayan City 13, Mandaue City 13. 77% of city-weeks are zero. **These 12 cities are not a sample of provinces; nothing here is extrapolated to provinces.**

## 1. National weekly lag analysis (2019-2020)

Spec: `cases_t ~ NB2(const + covid_t + sin/cos(2pi k doy/365.25), k=1,2 + rain_{t-l})`, HAC(4) SE. 'single' fits one lag at a time; 'joint' fits lags 0-6 together (distributed lag).

**Rain (+50 mm/week national area-mean CHIRPS), 2019-2020:**

| lag (weeks) | single-lag IRR (95% CI) | p | joint DLM IRR (95% CI) | p |
|---|---|---|---|---|
| 0 | 1.24 (0.96-1.60) | 0.102 | 1.11 (0.85-1.46) | 0.426 |
| 1 | 1.03 (0.83-1.27) | 0.803 | 1.06 (0.87-1.31) | 0.553 |
| 2 | 0.84 (0.64-1.09) | 0.185 | 1.04 (0.84-1.27) | 0.724 |
| 3 | 1.32 (1.03-1.69) | 0.027 | 1.27 (1.10-1.46) | 0.001 |
| 4 | 1.26 (0.89-1.77) | 0.193 | 1.03 (0.81-1.31) | 0.797 |
| 5 | 2.10 (1.56-2.81) | 0.000 | 1.68 (1.28-2.22) | 0.000 |
| 6 | 1.82 (1.30-2.55) | 0.000 | 1.52 (1.05-2.20) | 0.027 |
| sum 0-6 | | | 4.12 (2.41-7.03) | 0.000 |

n = 80 weeks, 4,705 cases; IRR per +50 mm/week national rain; NB alpha (joint) = 0.34.

- 2019 only: single-lag IRR by lag 0-6 = 0: 1.24 (0.99-1.54), 1: 0.99 (0.82-1.18), 2: 0.94 (0.76-1.15), 3: 0.95 (0.78-1.17), 4: 0.83 (0.62-1.12), 5: 1.36 (1.10-1.68), 6: 1.13 (0.88-1.46)
- 2019-2020, complete weeks: single-lag IRR by lag 0-6 = 0: 1.24 (0.88-1.75), 1: 1.05 (0.85-1.31), 2: 0.82 (0.63-1.08), 3: 1.40 (1.11-1.76), 4: 1.30 (0.88-1.93), 5: 2.10 (1.54-2.89), 6: 1.88 (1.31-2.69)
- 2019-2020, no seasonality: single-lag IRR by lag 0-6 = 0: 1.82 (1.26-2.62), 1: 1.74 (1.21-2.49), 2: 1.43 (0.96-2.14), 3: 2.02 (1.50-2.71), 4: 2.10 (1.48-2.97), 5: 2.87 (2.22-3.72), 6: 2.58 (1.91-3.49)
- population-weighted rain (+50 mm/week) (single lags): 0: 1.23 (0.94-1.60), 1: 1.04 (0.85-1.27), 2: 0.92 (0.72-1.17), 3: 1.41 (1.11-1.79), 4: 1.29 (0.94-1.75), 5: 2.01 (1.56-2.60), 6: 1.79 (1.30-2.48)
- heavy-rain week (single lags): 0: 1.11 (0.61-2.03), 1: 1.04 (0.64-1.68), 2: 0.91 (0.63-1.33), 3: 1.50 (0.85-2.65), 4: 0.95 (0.57-1.57), 5: 2.56 (1.55-4.21), 6: 2.33 (1.41-3.84)
- population share in a gale swath (single lags): 0: 0.38 (0.17-0.87), 1: 0.41 (0.18-0.94), 2: 1.00 (0.44-2.24), 3: 3.19 (1.08-9.44), 4: 0.92 (0.27-3.15), 5: 6.88 (0.93-50.58), 6: 5.06 (0.44-58.47)

## 2. City-week analysis (12 CCHAIN cities, 2016-2020)

Spec: `cases_ct ~ NB2(city FE + year FE + covid + 2 harmonics + rain_{c,t-l})`, Driscoll-Kraay SE (statsmodels `hac-groupsum` over weeks, 4 lags).

**Rain (+50 mm/week city CHIRPS):**

| lag (weeks) | single-lag IRR (95% CI) | p | joint DLM IRR (95% CI) | p |
|---|---|---|---|---|
| 0 | 1.16 (1.05-1.27) | 0.002 | 0.94 (0.87-1.01) | 0.102 |
| 1 | 1.28 (1.16-1.42) | 0.000 | 1.07 (0.99-1.15) | 0.073 |
| 2 | 1.31 (1.20-1.43) | 0.000 | 1.11 (1.03-1.20) | 0.007 |
| 3 | 1.50 (1.35-1.66) | 0.000 | 1.29 (1.17-1.41) | 0.000 |
| 4 | 1.58 (1.45-1.72) | 0.000 | 1.40 (1.29-1.52) | 0.000 |
| 5 | 1.34 (1.22-1.48) | 0.000 | 1.14 (1.06-1.22) | 0.001 |
| 6 | 1.28 (1.17-1.41) | 0.000 | 1.07 (0.99-1.17) | 0.088 |
| sum 0-6 | | | 2.45 (2.05-2.92) | 0.000 |

n = 3036 weeks, 1,685 cases; IRR per +50 mm/week city rain; NB alpha (joint) = 0.91.

**Heavy-rain week (>= the city's own 90th percentile):**

| lag (weeks) | single-lag IRR (95% CI) | p | joint DLM IRR (95% CI) | p |
|---|---|---|---|---|
| 0 | 1.45 (1.09-1.93) | 0.011 | 1.19 (0.92-1.54) | 0.195 |
| 1 | 1.53 (1.19-1.97) | 0.001 | 1.18 (0.96-1.44) | 0.107 |
| 2 | 1.68 (1.35-2.10) | 0.000 | 1.43 (1.17-1.75) | 0.000 |
| 3 | 2.21 (1.71-2.87) | 0.000 | 1.82 (1.42-2.33) | 0.000 |
| 4 | 2.33 (1.84-2.96) | 0.000 | 2.00 (1.61-2.48) | 0.000 |
| 5 | 1.47 (1.13-1.90) | 0.004 | 1.13 (0.92-1.39) | 0.233 |
| 6 | 1.53 (1.17-2.00) | 0.002 | 1.23 (0.98-1.55) | 0.073 |
| sum 0-6 | | | 10.16 (5.75-17.97) | 0.000 |

n = 3036 weeks, 1,685 cases; IRR per heavy-rain week (>= city p90); NB alpha (joint) = 1.11.

**City inside a gale circle (any WP storm) that week:**

| lag (weeks) | single-lag IRR (95% CI) | p | joint DLM IRR (95% CI) | p |
|---|---|---|---|---|
| 0 | 1.04 (0.76-1.44) | 0.794 | 1.06 (0.75-1.49) | 0.744 |
| 1 | 1.03 (0.77-1.36) | 0.858 | 1.04 (0.76-1.42) | 0.821 |
| 2 | 1.43 (1.03-1.99) | 0.034 | 1.36 (0.97-1.90) | 0.073 |
| 3 | 1.28 (0.78-2.11) | 0.332 | 1.19 (0.78-1.81) | 0.423 |
| 4 | 2.08 (1.14-3.80) | 0.016 | 2.03 (1.12-3.71) | 0.020 |
| 5 | 1.14 (0.70-1.84) | 0.598 | 1.10 (0.74-1.63) | 0.648 |
| 6 | 1.25 (0.71-2.21) | 0.436 | 1.25 (0.78-2.00) | 0.359 |
| sum 0-6 | | | 4.93 (1.21-20.08) | 0.026 |

n = 3060 weeks, 1,688 cases; IRR per city inside a gale circle that week; NB alpha (joint) = 1.37.

- city-specific seasonality, rain single lags: 0: 1.02 (0.94-1.12), 1: 1.13 (1.02-1.24), 2: 1.15 (1.05-1.26), 3: 1.33 (1.19-1.49), 4: 1.43 (1.30-1.56), 5: 1.14 (1.03-1.26), 6: 1.08 (0.97-1.20)
- 11 cities (no Iloilo), rain single lags: 0: 1.18 (1.07-1.30), 1: 1.29 (1.16-1.44), 2: 1.31 (1.19-1.45), 3: 1.52 (1.36-1.70), 4: 1.59 (1.46-1.73), 5: 1.33 (1.20-1.48), 6: 1.28 (1.16-1.40)
- literal CCHAIN week (date+6), rain single lags: 0: 1.28 (1.16-1.42), 1: 1.32 (1.20-1.44), 2: 1.51 (1.36-1.67), 3: 1.58 (1.45-1.72), 4: 1.35 (1.23-1.48), 5: 1.28 (1.17-1.41), 6: 1.22 (1.12-1.32)

## 3. Typhoon event study (weeks -4..+8 around landfall)

Cities inside each storm's whole-lifetime gale swath: Ompong: Dagupan City, Palayan City, Legazpi City, City of Mandaluyong, City of Navotas, City of Muntinlupa; Rolly: Palayan City, Legazpi City, City of Mandaluyong, City of Navotas, City of Muntinlupa; Tisoy: Dagupan City, Palayan City, Legazpi City, Iloilo City, Mandaue City, Tacloban City, Cagayan de Oro City, City of Mandaluyong, City of Navotas, City of Muntinlupa; Ulysses: Dagupan City, Palayan City, Legazpi City, City of Mandaluyong, City of Navotas, City of Muntinlupa.

| storm | group | pre (-4..-1) obs / exp | k0 | +1..+4 | +5..+8 |
|---|---|---|---|---|---|
| Ompong | outside (6) | 28 / 14.8 | 1 / 3.9 | 67 / 23.3 | 58 / 40.1 |
| Ompong | inside (6) | 93 / 18.3 | 19 / 4.1 | 40 / 16.2 | 17 / 11.0 |
| Rolly | outside (7) | 14 / 54.1 | 3 / 11.9 | 22 / 34.3 | 9 / 14.9 |
| Rolly | inside (5) | 4 / 7.6 | 1 / 1.0 | 8 / 2.4 | 9 / 1.8 |
| Tisoy | outside (2) | 6 / 6.7 | 0 / 1.5 | 10 / 3.9 | 2 / 12.6 |
| Tisoy | inside (10) | 24 / 31.6 | 5 / 3.7 | 14 / 8.6 | 16 / 16.5 |
| Ulysses | outside (6) | 19 / 44.2 | 2 / 8.8 | 19 / 22.2 | 6 / 14.0 |
| Ulysses | inside (6) | 4 / 12.1 | 2 / 1.4 | 12 / 3.1 | 3 / 2.5 |

Expected = the city's mean in the same 3 calendar weeks of the other 2014-2019 CCHAIN years, so in 2020 (COVID) every city sits below expectation; the inside/outside ratio removes that common drop.

Per storm, inside / outside ratio of obs/exp (Poisson CI, expected treated as known, no overdispersion):

| storm | pre (placebo) | k0 | +1..+4 | +5..+8 |
|---|---|---|---|---|
| Ompong | 2.69 (1.76-4.11) | 18.38 (2.46-137.27) | 0.86 (0.58-1.27) | 1.07 (0.62-1.84) |
| Rolly | 2.03 (0.67-6.17) | 3.96 (0.41-38.10) | 5.11 (2.27-11.47) | 8.10 (3.21-20.39) |
| Tisoy | 0.84 (0.34-2.06) | 4.40 (0.24-79.57)* | 0.63 (0.28-1.43) | 6.14 (1.41-26.72) |
| Ulysses | 0.77 (0.26-2.27) | 6.32 (0.89-44.87) | 4.58 (2.22-9.44) | 2.84 (0.71-11.35) |

(*) 0.5 added to a zero cell.

Pooled (quasi-Poisson, offset log expected, FE storm x event week; IRR = inside obs/exp over outside obs/exp):

| storms | period | IRR (95% CI) | p | dispersion | inside city-storms | inside obs / exp | outside obs / exp |
|---|---|---|---|---|---|---|---|
| ompong+rolly+tisoy+ulysses | pre | 2.05 (1.22-3.43) | 0.006 | 2.46 | 27 | 125 / 71.6 | 67 / 120.7 |
| ompong+rolly+tisoy+ulysses | k0 | 8.49 (1.82-39.66) | 0.007 | 2.46 | 27 | 27 / 11.0 | 6 / 26.3 |
| ompong+rolly+tisoy+ulysses | post1_4 | 1.22 (0.74-2.03) | 0.437 | 2.46 | 27 | 74 / 33.0 | 118 / 84.7 |
| ompong+rolly+tisoy+ulysses | late5_8 | 1.72 (0.94-3.17) | 0.080 | 2.46 | 27 | 45 / 34.6 | 75 / 76.8 |
| ompong+tisoy | pre | 2.36 (1.55-3.61) | 0.000 | 1.19 | 16 | 117 / 51.2 | 34 / 21.6 |
| ompong+tisoy | k0 | 20.22 (2.27-180.04) | 0.007 | 1.19 | 16 | 24 / 8.2 | 1 / 5.4 |
| ompong+tisoy | post1_4 | 0.81 (0.55-1.20) | 0.294 | 1.19 | 16 | 54 / 26.4 | 77 / 27.4 |
| ompong+tisoy | late5_8 | 1.36 (0.83-2.22) | 0.218 | 1.19 | 16 | 33 / 29.2 | 60 / 53.3 |
| rolly+ulysses | pre | 1.20 (0.32-4.53) | 0.787 | 2.87 | 11 | 8 / 20.4 | 33 / 99.1 |
| rolly+ulysses | k0 | 4.44 (0.38-51.48) | 0.233 | 2.87 | 11 | 3 / 2.8 | 5 / 20.9 |
| rolly+ulysses | post1_4 | 4.31 (1.72-10.85) | 0.002 | 2.87 | 11 | 20 / 6.5 | 41 / 57.3 |
| rolly+ulysses | late5_8 | 3.79 (1.03-13.99) | 0.046 | 2.87 | 11 | 12 / 5.4 | 15 / 23.4 |

Rolly and Ulysses landed 10 days apart, so their windows share city-weeks: the same weeks enter both storms in the pooled fits, and the two are not independent events.

169 city-weeks had a zero seasonal expectation (floored at 0.1 cases/week).

**Sentinel-1**: 31 of 48 city-storm pairs have radar over > 20% of the city; 8 show any new flood (max 2.2%). Pairs with flood: Ompong Dagupan City 2.2% flooded, 28 cases in +1..+4 (exp 7.8); Ompong Palayan City 0.6% flooded, 0 cases in +1..+4 (exp 0.3); Tisoy Palayan City 0.0% flooded, 0 cases in +1..+4 (exp 0.0); Tisoy Legazpi City 0.1% flooded, 0 cases in +1..+4 (exp 0.2); Rolly Palayan City 0.1% flooded, 0 cases in +1..+4 (exp 0.2); Rolly Iloilo City 0.7% flooded, 10 cases in +1..+4 (exp 23.9); Ulysses Palayan City 0.6% flooded, 0 cases in +1..+4 (exp 0.3); Ulysses Tacloban City 0.0% flooded, 0 cases in +1..+4 (exp 0.2). Too few flooded city-storm pairs to estimate a flood-case relation; reported descriptively only.

## Caveats

- Power: the national series is ~80 weeks with a COVID break and gaps (HAC errors treat the observed weeks as consecutive); the city panel is ~3,000 city-weeks but under 2,000 cases, over a third of them in Iloilo City, mostly zero weeks. Rain is seasonal, so the harmonics absorb much of its variation and the rain terms identify within-season anomalies; the common harmonics do not remove city-specific seasons (see the city-specific seasonality row).
- Lags 0-6 are collinear (weekly rain is autocorrelated); read the joint profile and the cumulative sum together, not single joint coefficients.
- Week labels: the CCHAIN-vs-HDX check fixes the city weeks to within about one week; a one-week label error shifts the lag profile one week (see the 'literal CCHAIN week' row).
- The heavy-rain threshold is an in-sample percentile and the models are fit on all weeks: fine for a retrospective association, not for a forecast (that would refit both inside each training window).
- The event study has 4 storms (2 in the COVID year; Rolly and Ulysses 10 days apart, so their windows overlap) and a handful of inside cities per storm; inside vs outside is mostly Luzon/NCR vs Visayas/Mindanao. Before Ompong, CHIRPS has heavy-rain weeks (>= the city's p90) in the inside cities from late July to early September 2018 (Dagupan 385 mm in the week ending 22 Jul and 141-275 mm/week from 12 Aug to 2 Sep), so those cities were already far above expectation before landfall (placebo column). For the same reason the landfall-week (k0) ratios reflect earlier rain, not the storm: incubation alone is usually 1-2 weeks.
- CCHAIN covers 12 cities only; the national series is Mendeley. Neither says anything about provinces.
- Matsushita et al. (2018) found the rain-leptospirosis risk peaking ~2 weeks after heavy rain, mediated by flooding; compare the lag profile above with that, not with a significance threshold.
