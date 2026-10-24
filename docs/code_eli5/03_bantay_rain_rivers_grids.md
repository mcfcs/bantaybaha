## bantay/rain.py

How much it rained in each province each week. Satellites give rain on a grid of small squares (like graph paper laid
over the country); this file averages the squares that fall inside each province, day by day, then adds the days up into
weeks.

### imports

Describes the rule for turning grid squares into province averages, and borrows number, table and map tools (`sparse`
is a memory-saving way to store a mostly-empty table).

### CHIRPS_DIR

Where the two rain datasets live: CHIRPS (satellite plus rain gauges) and IMERG (satellite, from Google Earth Engine).

### zonal_weights

Works out, once, which grid squares belong to which province. Each province gets an equal share from each of its
squares, and the shares add up to 1, so the result is an average. Sea squares are ignored. A tiny island that has no
square centre inside it borrows the nearest land square, so it is never left out. Like deciding, once, which desks
belong to which class before you start counting.

### apply_weights

Uses those shares to turn a whole stack of daily rain maps into daily province averages in one go. Blank squares (no
reading) are skipped instead of being treated as zero rain.

### _grid_transform

Builds the "map ruler" that says where each grid square sits on Earth, from the list of square centres. If the rows run
south-to-north, it notes that the map must be flipped the right way up.

### nearest_cells

For a list of points (for example, river segments), finds the nearest land square of the rain grid to each one, using a
fast "nearest neighbour" search.

### chirps_daily_units

Reads the CHIRPS rain files year by year. The files count days in an unusual way ("days since 4713 BC"), so it converts
them to normal dates. It returns daily rain for every province, and optionally the daily rain at each river segment. It
uses a simple file reader that works even on locked-down Windows computers.

### imerg_daily_units

The same for IMERG rain, which comes as one file per month with one layer per day. If those files are not downloaded
yet, it reports them missing and the build carries on.

### weekly

Turns daily rain into three weekly numbers per province: the total for Monday-Sunday (`_7d`), the total for the last
three days of the week (`_3d`, a "it rained right before the week ended" clue), and the wettest single day (`_max1d`).

## bantay/rivers.py

Rain does not stay where it falls: rivers carry it downstream. A town at a river's mouth can flood from rain that fell
in the mountains. This file follows the river network and gives every province a measure of "how much rain is arriving
from upstream".

### imports

Explains the idea and borrows number, table and map tools.

### HR_ZIP

Where the river map (HydroRIVERS) is, and the layer inside it. The Philippines is in the "Australasia" file of that
dataset, not the "Asia" one.

### load_reaches

Opens the river map: thousands of short river pieces ("reaches"), each knowing which piece is next downstream. Each piece
is assigned to the province it sits in (pieces just off the coast go to the nearest province). They are sorted from
small upstream pieces to big downstream ones, so we can walk the water downhill in order.

### accumulate

Walks the water downhill. Each piece's rain (rain times its own little drainage area) is added to the next piece down,
which adds it to the next, and so on. Dividing by everything upstream gives "the average rain over all the land that
drains into this point". Like a bucket brigade passing water down a line, each person adding their own bucket.

### unit_week_river

Does that for every week, then gives each province one number: the upstream rain at its river pieces, with big rivers
counting more than small streams (`river_up_7d`). It also gives how much more that is than the province's own rain
(`river_excess_7d`): a large value means "rain is coming from somewhere else".

## bantay/grids.py

People maps. A population map (WorldPop) gives the number of people in every 100 m square of the country. This file lines
everything up with that grid, so "how many people are flooded" or "how many people are cut off" can be counted square
by square.

### imports

Explains why everything uses the same 100 m grid and borrows number, table, map and raster tools.

### WORLDPOP

Where the population map is, and the names of the files this module saves (a province map on the same grid, and the
1 km population points). `BLOCK` is how big a piece of the map is read at once, so the computer's memory is not
overloaded by the whole country at 100 m.

### fresh

Answers "is this saved file still up to date?": yes if it exists and is newer than the files it was made from. It saves
redoing slow work.

### unit_index

Gives each province a small number (1 to 85) for use on a map grid, where 0 means "not in any province".

### build_unit_raster

Paints the 85 provinces onto the 100 m population grid, piece by piece, so every square knows which province it is in.
Like colouring a paint-by-numbers sheet with province numbers.

### iter_blocks

Reads several matching grid maps together, one piece at a time, and hands the pieces over. It lets the code go through
the whole country without loading it all at once.

### worldpop_clean

Turns "no data" squares and impossible values (negative, infinite) into 0 people.

### unit_population_worldpop

Counts the people in each province by adding up the population squares with that province's number. It is the backup
when the census table is missing.

### build_pop_cells

Groups the 100 m squares into 1 km squares (10 by 10) and adds up the people, giving about 369,000 points across the
country. Each point is labelled with its province and its town. These points are the "people" the hospital-access model
routes to hospitals. Coastal squares whose centre is in the sea are given to the nearest town.

### HRSL

Where Meta's age-group population maps live: children under 5 and people aged 60 and over. `HRSL_ROWS` is how many map
rows are read at a time.

### _hrsl_block_sums

These age maps use a finer 30 m grid. This adds every 30 m square into the 1 km square that holds it, reading the file
from top to bottom in strips (fast for a zipped file). It also counts how many people fall outside our grid, so we can
report it.

### build_vulnerable_cells

Gives every 1 km population point its number of young children and of older people, so the access model can say how
many of the people cut off are in these vulnerable groups. Saved for reuse; if an age map is missing, those numbers are
left blank.

### ADM3_RASTER

The name of the saved file that paints towns and cities (instead of provinces) onto the 100 m grid.

### adm3_index

Gives each town a number for that map (0 means "not in any town").

### build_adm3_raster

Paints all towns onto the 100 m grid, piece by piece, only drawing the towns that touch each piece (to save time). Used
to count flooded people per town.

### _box

A tiny helper that turns four edges (west, south, east, north) into a rectangle shape.
