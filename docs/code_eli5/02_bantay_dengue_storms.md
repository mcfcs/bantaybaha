## bantay/dengue.py

The thing we want to predict: how many dengue cases each province had each week. It also finds how many people live in
each province, so cases can be turned into "cases per 100,000 people" (a fair comparison between a big and a small
province).

### imports

Describes the rules (skip the second row of the file, never use the deaths column) and borrows tables (`pandas`), the
settings, and the lookup tables from `units`.

### DENGUE

Where the two input files are: the DOH dengue file and the 2020 census table.

### weeks

The list of every Sunday from 10 Jan 2016 to 10 Jan 2021: 262 weeks. It is the calendar every other table is lined up on.

### load_dengue

Opens the DOH dengue file. It skips the file's second row (a row of technical tags, not data), trims stray spaces from
place names, checks every date is a Sunday, and drops the "deaths" column on purpose, because the 2016 deaths are too
high to be believable.

### unit_week_cases

Turns 126 reporting places into 85 provinces. A province's weekly total is the sum of all its places (the province plus
any cities inside it). If even one of its places is missing that week, the total is left **blank** instead of being
counted as a smaller number. Like adding up a class's test scores: if one student's paper is missing, you don't pretend
they scored zero.

### unit_population

How many people live in each province, from the 2020 census. The census lists every town with the province it belongs
to (big cities included), so we simply add up the towns of each province. A few names need a nudge: the Metro Manila
districts, the Special Geographic Area (counted with Cotabato) and the City of Isabela (counted with Basilan).

## bantay/storms.py

Typhoon paths. It reads where every storm was, every 3 hours, and works out the area that felt gale-force winds (the
"swath"), how close each storm came to each province each week, and what a storm would have done if its path had been a
little further north, south, east or west.

### imports

Describes how the wind radius is chosen (with fallbacks when data are missing) and borrows number, table and map-shape
tools.

### NM_KM

Fixed facts: one nautical mile is 1.852 km; where the storm-track file lives; the four columns that hold the US agency's
gale-wind distance in each direction; and the columns we read.

### load_ibtracs

Opens the storm-track file (IBTrACS) and keeps only 2016-2020 storms near the Philippines and the main track of each.
For each position it picks one wind speed: the US agency's, else the world agency's, else Japan's.

### gale_radius

How far from the eye the gale-force winds reach, for each storm position. First choice: the US agency's distance (the
biggest of its four directions). If that is blank (it often is), Japan's slightly wider measure. If both are blank, a
fixed 150 km. When the storm is weaker than gale force, the radius is zero. It also writes down which source it used.

### storm_track

All positions of one storm in time order, found by name and year (for our four typhoons) or by storm ID.

### shift_track

A "what if" storm: the same storm, same strength, but every position moved by a few degrees (and optionally in time).
Like sliding a drawing of the path across the map.

### interpolate

Positions are known every 3 hours; this fills in the in-between hours with straight-line steps, so the swath has no gaps
between the dots.

### swath

The area that felt gale-force winds: draw a circle of the gale radius around the storm at every hour and join all the
circles. The result looks like a fat ribbon along the path. If the storm never reached gale force, there is no swath.

### track_line

Joins the storm's positions into one line, for drawing on a map.

### unit_week_exposure

For every province and every week of 2016-2020, how storms touched it: the closest any storm came, whether the province
was inside a gale circle, the strongest wind within 300 km, and how many storms passed within 300 km. These numbers
become clues for the forecast ("a storm just hit here").

### origin_exposure

The storm clues for one forecast week, worked out exactly the same way the forecast learned them: over the last 4 weeks
up to that week, and never using storm positions from later weeks. When a track is moved for a "what if", this gives
the new clues while keeping every other storm the same.

### shift_storm

Moves only one of our four typhoons in the storm list and leaves every other storm where it was, so a "what if" changes
just that storm.
