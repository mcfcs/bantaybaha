# Bantay-Baha: technical demo script (2:50)

About 300 words of narration at a calm pace (~140 words a minute), leaving time for the clicks and redraws. This is a
feature-by-feature tour of the dashboard: every control, tab and column, and what it tells a health officer.
**Anonymous:** no names, team name, school or logos on screen or in the voice-over. Record the dashboard full screen at
1920 x 1080, browser zoom 90%, with Typhoon Ompong selected and the track at "no shift" before you start. Cues in
**bold** are what you click.

| Time | On screen (cue) | Narration |
|---|---|---|
| **0:00-0:12** | Dashboard, **Action map** tab. Slowly point down the sidebar: **Typhoon**, the two track sliders, **How to read this**. | "This is the Bantay-Baha dashboard. On the left you choose a typhoon and, if you want, move its track. Everything else updates from that choice." |
| **0:12-0:27** | Open the **Typhoon** box, type `Kalm`, then press Esc to keep Ompong. Point at the caption: 4 backtest typhoons, then the catalogue. | "Four typhoons have full what-if tracks. Every other storm from 2017 to 2020 that reached land is in the catalogue too: 42 storms in all, 98 scenarios." |
| **0:27-0:45** | **Colour provinces by**: click **Surge risk R**, then **Access loss A**, then back to **Priority P**. Hover the track, the dashed gale swath and a green ferry line. | "The map colours provinces by surge risk, access loss, or priority, which is the two multiplied. On top: the track, the gale-force swath, and the 42 ferry routes this storm would cancel." |
| **0:45-1:00** | Right panel **Act first**: point at the top rows and the tier counts below (0 deploy, 22 pre-position). Hover the **Surge risk R** header to show its definition. | "Act first lists the top ten, each with an action tier: deploy clinics, pre-position supplies, or monitor. Every column header explains itself on hover." |
| **1:00-1:17** | Sidebar: **Move track north or south** to **1° south**, wait for the redraw, then **Back to observed track**. Point at the browser address bar. | "Move the storm one degree south and the ranking updates in seconds; 58 ferries close instead of 42. The choice is kept in the link, so a colleague sees the same scenario." |
| **1:17-1:40** | **Provinces** tab. Scroll right along Pampanga's row: R 0.83 and R raw 0.50, A range 4.8-6.4%, cases 934 (337-1,162), under-5 and 60+ cut off, Sentinel, Main drivers. Click **Download table (CSV)**. | "Provinces is the full ranked table. Pampanga's surge risk is 83 percent after calibration; its access loss is a range, because two methods measure it. You get expected cases with a 90 percent range, children and older people cut off, and the drivers of the risk." |
| **1:40-1:52** | **Municipalities** tab: choose **Pampanga**. Point at Candaba (36%), Apalit, San Luis. | "Municipalities drills down to towns: in Pampanga, Candaba loses the most access, so that is where a mobile clinic should go." |
| **1:52-2:10** | **Outbreak graph** (sentinels), then **Forecast skill**: the model comparison, then **Weeks ahead** 4 for the fan chart. Then **Validation**. | "Outbreak graph shows which provinces rise first. Forecast skill compares our model with the baseline and three benchmarks. Validation shows whether high-priority provinces really surged." |
| **2:10-2:22** | **Leptospirosis** (lag chart), then **Usability test**. | "Leptospirosis shows how cases follow rain, and a built-in usability test lets health officers rate the tool." |
| **2:22-2:50** | **Data & caveats** tab: scroll to **Storm catalogue**; point at the storm count. End on the Action map. | "Nothing is trained while you click: the dashboard serves the results of the latest run. When a new typhoon arrives, the model is retrained from scratch, using only what was known before that storm, and the new storm joins this list with every number on these tabs. Same data, same model: the training is repeatable." |

## Numbers on screen (Ompong, observed track; same as the demonstration video)

- Act first: deploy 0, pre-position 22; 42 of 108 ferry routes cancelled; top priority Pampanga.
- Pampanga: R 0.83 calibrated (R raw 0.50), A 4.8% (method range 4.8-6.4%), cases next 4 weeks 934 (90% range 337-1,162).
- Municipalities, Pampanga: Candaba 36% cut off, then Apalit 28%, San Luis 25%.
- 1° south: 58 ferry routes cancelled. Catalogue: 42 storms scored (4 backtest typhoons + 38 others), 98 scenarios.
- Retraining: the forecast models are trained fresh on every run, each only on data before its storm's landfall week, with a fixed seed (same data, same model). No model is trained in the dashboard.
- Calibration makes ties: nine provinces share R 0.83 for Ompong, so the map ranks by P, not by R alone.

## Before recording

- Tabs, in order: Action map, Risk vs access, Provinces, Municipalities, Outbreak graph, Forecast skill, Leptospirosis, Validation, Data & caveats, Usability test.
- Do not type anything into the Usability test form during the take; only show it.
- Hide the browser bookmarks bar and any tabs or accounts that show a name; the address bar may show only `localhost`.
- Keep the mouse still while you speak over a chart, and move it only on the cues. Trim to 2:50 in editing.
