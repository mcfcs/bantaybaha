## bantay/flood.py

Where floods happen. Three sources: NOAH flood-hazard maps ("this area floods in a big storm", the same every year),
Copernicus EMS maps drawn by experts after Typhoon Ompong, and our own Sentinel-1 radar maps (radar sees water through
clouds, so we compare a photo from before the storm with one from after and mark the land that became water).

### imports

Describes the codes used in the flood maps (255 = no map here, 0 = mapped and dry, 1-3 = low/medium/high hazard; for
radar 1 = new flood) and borrows file, table, map and raster tools.

### NOAH

Where the three flood sources live, and the two NOAH storm sizes: a 5-year flood (fairly common) and a 25-year flood (a
rare, big one).

### hazard_raster_path

The name of the saved national hazard map for one storm size.

### _nk

Cleans a name for matching: capital letters only, no brackets, no spaces or punctuation.

### noah_file_units

NOAH comes as one zip file per province, named in many styles (some by name, some by an old ID number). This works out,
for each zip, which of our 85 provinces it covers, and warns about any file it could not match.

### _hazard_col

Different NOAH files call the hazard column by different names (`Var`, `HAZ`, `GRIDCODE`, ...). This finds whichever one
the file uses.

### build_hazard_raster

Paints all NOAH maps onto the 100 m population grid, for one storm size. It starts with everything marked "no map", then
for each province with a NOAH file marks that province as "mapped and dry" and paints the hazard areas on top (high wins
over low where they overlap). Areas without a map stay "no map", **not** "safe": not knowing is different from knowing it
is dry.

### unit_hazard_shares

For each province, the share of its people who live in a flood-hazard area (any level, and high only), for both storm
sizes. If less than half the province's people are covered by a NOAH map, the answer is left blank instead of guessing.

### ems_observed_flood

Opens the expert flood maps drawn after Typhoon Ompong (activation EMSR312) and keeps only the "observed flood" shapes.
We use them as the answer sheet to check our radar flood maps.

### s1_tiles

Lists the radar flood map pieces (tiles, about 1 degree square each) downloaded for one storm.

### _tile_cell

Reads a tile's name (like `s1flood_121E_17N`) to find the exact 1-degree square it is meant to cover.

### _s1_zone_sums

The counting machine for radar floods. For each tile, it lines the radar map up with the population grid and, for every
province (or town), counts three things: how much land the radar saw, how much of it was newly flooded, and how many
people live on that flooded land. Tiles overlap a tiny bit at the edges; with `crop` on, each tile is trimmed to its own
square so the overlap is not counted twice.

### s1_unit_flood

Per province, for one storm: the share of the land the radar saw that was newly flooded, and the number of people on
that flooded land. Where the radar saw nothing, the answer is blank (not zero).

### s1_adm3_flood

The same, per town and city, for every storm with radar tiles. It also says what share of each town the radar actually
saw, so a reader can tell "no flood" from "not looked at".

### s1_flood_lookup

Makes a quick "is this spot flooded?" helper for one storm: give it map points and it answers 1 (flooded), 0 (dry) or
255 (radar did not see it). The hospital-access model uses it to know which roads were under water.

## bantay/panel.py

The big table everything else reads: one row per province per week (85 provinces x 262 weeks), with the dengue count,
population, storm, rain, river and flood clues side by side. If an input is missing, its columns are simply blank and the
table is still built.

### imports

Describes the table and borrows the tools and every data module (dengue, units, storms, rain, rivers, flood, grids).

### PANEL

Where the table and its "data card" (a short description of every column) are saved, and the list of columns with their
source and meaning. That list is also used to make sure every column exists, even when blank.

### _newest

Finds the most recent change time among some files.

### cached

"Reuse if still fresh, otherwise remake." If a saved result is newer than all the files it was made from, read it;
otherwise rebuild and save it. Like keeping leftovers in the fridge, but only if nothing new was bought since.

### rain_layers

Gets weekly rain per province from CHIRPS (and, in the same pass, the river upstream rain) and from IMERG if those files
exist. Each comes back blank if its files are missing.

### static_layers

Gets the NOAH flood-hazard shares per province (making the hazard maps the first time). These do not change week to week.

### s1_layers

Puts the radar flood numbers into the right weeks. The flood map is only "known" once all its after-storm photos exist
(landfall + 10 days), so the numbers are put on the 4 weeks starting from then, not on the landfall week. That way the
forecast never sees a photo before it was taken. When two storms share a week, the bigger flood is kept.

### build_panel

Builds the whole table step by step: the empty province-by-week grid, dengue cases, population (census, or WorldPop as a
backup), cases per 100,000, storm clues (no storm nearby = 2000 km, 0 hits), rain, river, hazard, storm-times-hazard,
and radar flood. Every listed column is made to exist, then the table and its data card are saved.

### write_card

Writes the data card: what the table is, a line per column with how complete it is, and a list of every input saying
whether it was there.

### load_panel

Opens the saved table.
