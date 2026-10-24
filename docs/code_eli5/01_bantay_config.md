## bantay/__init__.py

This file only says "this folder is a Python package called `bantay`". Having it lets every other script write
`from bantay import ...`, the way a label on a box lets you find the box.

### imports

Just a description of the package. There is no working code here: Python reads this text as the package's name tag.

## bantay/config.py

The settings drawer. Every other file opens this one to find out where the data lives, which weeks we study, which
typhoons we replay, and how to write down "this input was missing". Keeping these in one place means changing a setting
here changes it everywhere.

### imports

The first lines describe the file. Then it borrows three tools: `json` (to save notes as text files), `datetime` (to
stamp the time) and `Path` (to build folder paths that work on any computer).

### ROOT

The address book and the calendar.

- `ROOT` finds the project folder by starting at this file and going up one level. So the code works no matter where
  the project is copied.
- `RAW`, `INTERIM`, `PROCESSED`, `CROSSWALKS`, `APP_DATA` are the drawers: untouched downloads, half-finished work,
  finished tables, hand-checked lookup tables, and the small files the dashboard reads.
- `BBOX` is a box drawn around the Philippines on a map (west, south, east, north). `CRS_M` is a map "ruler" in metres.
- The DOH counts dengue in weeks that end on **Sunday**, so the calendar is "every Sunday from 10 Jan 2016 to 10 Jan 2021".
  `MODEL_END` (end of 2019) is the last week the model may learn from, because 2020 counts dropped when COVID-19 hit.
- `STORMS` lists the four typhoons we replay (Ompong, Tisoy, Rolly, Ulysses) with the day each reached land.
- `S1_AFTER_DAYS = 10`: a satellite flood map needs up to 10 days of photos after landfall, so the forecast may only use
  it after those 10 days have passed. Using it earlier would be like reading tomorrow's newspaper today.
- `QUANTILES` are the 23 "how sure are we" levels (1%, 2.5%, 5% ... 99%) that forecast hubs use for ranges.

### week_ending

Give it any date, and it tells you which Sunday ends that week. Wednesday 3 June becomes Sunday 7 June; a Sunday stays
the same. Every daily thing (rain, storm positions) is put into the right weekly box this way, so it lines up with the
weekly dengue counts.

### _STATUS_FILE

The name of the notebook (`status.json`) where the build writes down which inputs were there and which were missing.

### _load_status

Opens that notebook and reads it. If the notebook does not exist yet, it starts with an empty page.

### record

Writes one line in the notebook: "input X: available (or not), here is a detail, checked at this time". It keeps the
other lines and only updates this one.

### status

Hands back the whole notebook, so the build can print the missing list at the end and the dashboard can show it.

### missing

Says out loud "WARNING: X is missing" and writes it in the notebook. It returns nothing on purpose, so a function can
stop with `return missing(...)` and the caller just sees "no answer" instead of a crash.

### have

Checks that a file (or a folder with at least one matching file) is really there. If yes, it writes "available"; if not,
it calls `missing` and answers False. It is the "do we have the ingredients?" check before cooking.

### ensure_dirs

Makes sure the output drawers exist before anything is put in them.

## bantay/units.py

The places problem. The dengue file names 126 places (provinces mixed with big cities), but today's official map has
newer borders. This file builds one agreed list of **85 provinces as they were in 2016-2020** and two lookup tables
("crosswalks") that translate every name into that list. Think of it as making sure everyone uses the same map before
comparing numbers.

### imports

Describes the problem and borrows tools: text matching (`re`, `unicodedata`), tables (`pandas`), map shapes
(`geopandas`) and the settings from `config`.

### COD_ZIP

The fixed facts this file works with.

- Where the official boundary file (COD-AB) and the two lookup tables live.
- `MERGE` undoes three border changes made after 2020: two Maguindanao halves become one Maguindanao again, the
  "Special Geographic Area" goes back to Cotabato, and the City of Isabela goes back into Basilan.
- Maguindanao gets a made-up ID because no single current code covers it.
- `DENGUE_FIX` corrects spelling slips in the dengue file (NUEVA VISCAYA, SISQUIJOR, BASILIG means Bislig) and maps old
  names to the right place. NAGA CITY is in Camarines Sur, because the file lists it under that region.

### norm

Cleans a place name so two spellings can be compared: removes accents (Las Piñas becomes LASPINAS), anything in
brackets, the words "City of" and "City", spaces and punctuation, and makes it capital letters. "City of Las Piñas"
and "LAS PINAS CITY" both become `LASPINAS`.

### read_adm

Opens one layer of the official map: level 2 is provinces, level 3 is towns and cities. If the map file is missing it
reports that instead of crashing.

### _unit_name

For one official province name, answers "which 2016-2020 province is this?" and which rule was used. Most answers are
"itself"; the three merged places get their old province.

### build_adm2_crosswalk

Builds the first lookup table: every official province, its 2016-2020 province, and that province's ID. The ID is the
official code of the member with the same name (or Maguindanao's made-up ID).

### build_dengue_crosswalk

Builds the second lookup table: each of the 126 dengue names to a 2016-2020 province. City names are looked up as cities
first, so "QUEZON CITY" is not mistaken for Quezon province. Then province names, then town names. Every match is
folded into its province, and unclear matches get a note so a person can check them.

### write_csv_with_header

Saves a table as a CSV file with a few `#` comment lines on top that say where it came from and which rules were used,
so a person reading it later knows how it was made.

### read_crosswalk

Opens a lookup table, skipping the `#` comment lines and keeping codes as text (so a leading zero is not lost).

### build_crosswalks

Makes both lookup tables once and saves them. Next time it just reuses them, because a person checked them by hand and
we do not want them silently remade. Writes down how many dengue names matched (all 126).

### check_psgc

An optional double-check: if someone downloaded the government's official code list (PSGC) by hand, it confirms every
province code exists in it. If the file is not there, it simply skips.

### build_units_geometry

Glues the official province shapes together into the 85 study provinces (for example the two Maguindanao halves become
one shape), fixes any broken shapes, smooths the edges a little so maps draw fast, and saves the result.

### load_units

Opens the saved province shapes, making them first if they do not exist yet.

### adm3_with_units

Gives the town and city shapes, each labelled with its 2016-2020 province, for the town-level results.
