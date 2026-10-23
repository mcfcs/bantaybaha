# Bantay-Baha: demonstration video script (2:50)

About 380 words of narration at a calm pace (~140 words a minute). **Anonymous:** no names, team name, school or logos on screen
or in the voice-over. Record the dashboard full screen at 1920 x 1080 (`run_app.bat`, then open http://localhost:8501), browser zoom
90%, with Typhoon Ompong selected and the track at 0 / 0 before you start. Numbers below are what the dashboard shows for this build;
if you rebuild, re-check them on screen.

| Time | On screen (cue) | Narration |
|---|---|---|
| **0:00-0:15** | Deck slide 2 (typhoons, Ondoy, 2019 epidemic) or the national dengue curve. Slow zoom on the 2019 peak. | "Eight or nine typhoons cross the Philippines every year. Their floods bring leptospirosis and dengue, yet we respond only after cases rise, and the hardest-hit places are often cut off from care." |
| **0:15-0:35** | Deck slide 5: three graphs, one ranking. Point at each row as you name it. | "Bantay-Baha answers two questions for any typhoon track: where will disease surge, and who will lose their way to a hospital? It joins flood exposure seen from space, a graph of how outbreaks travel between provinces, and a road-and-ferry network that the storm can cut." |
| **0:35-1:00** | Dashboard, **Priority map** tab, Ompong 2018. Hover the track, then the dashed gale swath, then the red cancelled ferry lines. Pause on the KPI row. | "This is Typhoon Ompong, 2018, replayed with only the data available in its landfall week. Orange is the track; the dashed outline is its gale-force swath; the red lines are the 42 ferry routes it would cancel. Roads are cut where Sentinel-1 radar saw new floodwater. About 343,000 people lose their route to a hospital, and 21 provinces are flagged to pre-position supplies." |
| **1:00-1:15** | Hover **Pampanga** (darkest) and read the tooltip: R 0.51, A 4.8%. | "Pampanga tops the list. Its surge probability is 51 percent, and radar shows almost five percent of its people cut off, so it is both likely to surge and hard to reach." |
| **1:15-1:35** | Sidebar: move **Shift north** to **-1.0**, then to **+1.0**. Let the map redraw each time; point at the ferry lines and the KPI "people cut off". | "What if the storm comes in further south? Shift the track, and the ranking updates in seconds: 58 ferry routes close instead of 14 when it passes one degree south. For a track that hasn't happened, flooded roads come from hazard maps, so these numbers are an upper-bound estimate." |
| **1:35-1:55** | Shift back to **0.0**. Open **Risk vs access**. Point at the top-right quadrant and the dotted threshold lines. | "Each province sits on two axes: surge risk and access loss. Top right means act first. The dotted lines set the action tier: monitor sentinel sites, pre-position doxycycline and vector control, or send mobile clinics before the roads close." |
| **1:55-2:15** | **Ranked provinces** tab. Scroll slowly; point at "cases next 4 wk (90% range)", "people cut off" and "drivers". Then **Municipalities**, choose Pampanga: Candaba (36% cut off), Apalit, San Luis. | "The ranked list gives expected cases for the next four weeks with an honest range, the people cut off, and what drives each risk. Drill down: in Pampanga, Candaba and Apalit lose the most access, which tells a health officer exactly where a mobile clinic should go." |
| **2:15-2:35** | **Forecast skill** tab: the table, then the reliability chart; choose Cagayan, horizon 4, to show the fan chart. Then **Validation** tab. | "Is it right? On two years of real-time-style tests, the forecast is 45 percent better than the seasonal baseline, and 85 percent of outcomes fall inside its 90 percent range. After Ompong, seven of the ten provinces we ranked highest really did surge." |
| **2:35-2:50** | Deck slide 18 (putting it in the loop), then the title slide. | "Next, we put it in the loop: a PAGASA bulletin goes in, and a ranked action list reaches health officers before landfall. Bantay-Baha: see the surge before the water rises." |

## Before recording

- Restart the dashboard after any rebuild (it caches data): close it and run `run_app.bat` again.
- Check the tooltip and KPI numbers above against the screen; if a rebuild changed them, read what the screen shows.
- Keep the mouse still while you speak over a chart, and move it only on the cues.
- Hide the browser bookmarks bar and any tabs or accounts that show a name.
- Trim to 2:50 in editing; a two-second title card at the start and end is enough (no logos).
