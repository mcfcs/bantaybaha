# Bantay-Baha: demonstration video script (2:50)

About 400 words of narration at a calm pace (~140 words a minute). **Anonymous:** no names, team name, school or logos on screen
or in the voice-over. Record the dashboard full screen at 1920 x 1080 (`run_app.bat`, then open http://localhost:8501), browser zoom
90%, with Typhoon Ompong selected and the track at "no shift" before you start. Every number below was checked against
`data/processed/app/` for this build and matches what the dashboard shows; if you rebuild, re-check them on screen.

| Time | On screen (cue) | Narration |
|---|---|---|
| **0:00-0:15** | Deck slide 2 (typhoons, Ondoy, 2019 epidemic) or the national dengue curve. Slow zoom on the 2019 peak. | "Eight or nine typhoons cross the Philippines every year. Their floods bring leptospirosis and dengue, yet we respond only after cases rise, and the hardest-hit places are often cut off from care." |
| **0:15-0:35** | Deck slide 5: three graphs, one ranking. Point at each row as you name it. | "Bantay-Baha answers two questions for any typhoon track: where will disease surge, and who will lose their way to a hospital? It joins flood exposure seen from space, a graph of how outbreaks travel between provinces, and a road-and-ferry network that the storm can cut." |
| **0:35-1:00** | Dashboard, **Action map** tab, Ompong 2018. Hover the track, then the dashed gale swath, then the green cancelled ferry lines. Pause on the KPI row (0 deploy, 22 pre-position, 343K cut off, 42 ferries). | "This is Typhoon Ompong, 2018, replayed with only the data available in its landfall week. Orange is the track; the dashed outline is its gale-force swath; the green lines are the 42 ferry routes it would cancel. Roads are cut where Sentinel-1 radar saw new floodwater. About 343,000 people lose their route to a hospital, and 22 provinces are flagged to pre-position supplies." |
| **1:00-1:15** | Hover **Pampanga** (darkest) and read the tooltip: R 0.83, A 4.8% (range 4.8-6.4%). | "Pampanga tops the list. After calibration on past forecasts, its surge probability is 83 percent, and radar shows almost five percent of its people cut off, so it is both likely to surge and hard to reach." |
| **1:15-1:35** | Sidebar, **Move track north or south**: choose **1° south**, then **1° north**. Let the map redraw each time; point at the ferry lines and the KPI "cut off from a hospital". | "What if the storm comes in further south? Move the track, and the ranking updates in seconds: 58 ferry routes close when it passes one degree south, and 14 when it passes one degree north. For a track that hasn't happened, flooded roads come from hazard maps, so these numbers are an upper-bound estimate." |
| **1:35-1:55** | Click **Back to observed track** (no shift). Open **Risk vs access**. Point at the top-right quadrant and the dotted threshold lines. | "Each province sits on two axes: surge risk and access loss. Top right means act first. The dotted lines set the action tier: monitor sentinel sites, pre-position doxycycline and vector control, or send mobile clinics before the roads close." |
| **1:55-2:15** | **Provinces** tab. Scroll slowly; point at the 4-week cases with their 90% range (Pampanga 934, 337-1,162), "cut off" and the drivers. Then **Municipalities**, choose Pampanga: Candaba (36% cut off), Apalit (28%), San Luis (25%). | "The ranked list gives expected cases for the next four weeks with an honest range, the people cut off, and what drives each risk. Drill down: in Pampanga, Candaba and Apalit lose the most access, which tells a health officer exactly where a mobile clinic should go." |
| **2:15-2:35** | **Forecast skill** tab: the model comparison, then the reliability chart; choose Cagayan, horizon 4, for the fan chart. Then **Validation** tab. | "Is it right? On two years of real-time-style tests, the forecast is 46 percent better than the seasonal baseline, and 85 percent of outcomes fall inside its 90 percent range. Blended with three foundation and graph models, it does better still. After Ompong, seven of the ten provinces we ranked highest really did surge." |
| **2:35-2:50** | Deck slide 19 (putting it in the loop), then the title slide. | "Next, we put it in the loop: a PAGASA bulletin goes in, and a ranked action list reaches health officers before landfall. Bantay-Baha: see the surge before the water rises." |

## Numbers on screen (Ompong, observed track; checked against the build)

- Deploy 0, pre-position 22; cut off 343K on the road network (lower bound), 632K on the friction-raster method; 42 of 108 ferry routes cancelled; top priority Pampanga.
- Pampanga: R 0.83 calibrated (the model's raw R is 0.50; say 83 percent, not 50 or 51), A 4.8% (method range 4.8-6.4%), P 0.040, cases next 4 weeks 934 (90% range 337-1,162).
- Candaba: 36% of people cut off (36,776); 34.5% of its land in new radar flood (41,578 people). Then Apalit 28%, San Luis 25%.
- 1° south: 58 ferries, 7.8 M cut off (upper bound), 7 deploy / 19 pre-position, top Isabela. 1° north: 14 ferries, 6.9 M, 7 / 18, top Isabela.
- Forecast skill: relative WIS 0.54 (46% better), 90% coverage 85%; median ensemble 0.44. Validation: 7 of the top 10 surged, Spearman(R) 0.68.
- Calibration makes ties: nine provinces share R 0.83 for Ompong, so rank by P (the map's colour), not by R alone.

## Before recording

- After a rebuild, refresh the dashboard page: it reloads the new outputs (no restart needed).
- Tabs, in order: Action map, Risk vs access, Provinces, Municipalities, Outbreak graph, Forecast skill, Leptospirosis, Validation, Data & caveats, Usability test.
- The track slider reads "1° south / no shift / 1° north" (and east / west for the second slider).
- Keep the mouse still while you speak over a chart, and move it only on the cues.
- Hide the browser bookmarks bar and any tabs or accounts that show a name.
- Trim to 2:50 in editing; a two-second title card at the start and end is enough (no logos).
