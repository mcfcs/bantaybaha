"""bantay.units: name normalisation and the crosswalk rules, on a hand-built mini COD-AB (ADM2 / ADM3) table."""

import pandas as pd
import pytest

from bantay import units as U

pytestmark = pytest.mark.usefixtures("isolated_status")


@pytest.mark.parametrize("name, key", [
    ("Las Piñas", "LASPINAS"),
    ("City of Las Piñas", "LASPINAS"),
    ("LAS PINAS CITY", "LASPINAS"),
    ("Quezon City", "QUEZON"),
    ("Lucena City (Capital)", "LUCENA"),
    ("Cotabato (North Cotabato)", "COTABATO"),
    ("General Santos City (Dadiangas)", "GENERALSANTOS"),
    ("City of Isabela (not a province)", "ISABELA"),
    ("Santo Niño", "SANTONINO"),
    ("Ma-ayon", "MAAYON"),
    ("nueva vizcaya", "NUEVAVIZCAYA"),
])
def test_norm(name, key):
    assert U.norm(name) == key


ADM2 = pd.DataFrame([
    ("PH02031", "Isabela"), ("PH09097", "City of Isabela (not a province)"), ("PH19007", "Basilan"),
    ("PH04056", "Quezon"), ("PH13039", "Metropolitan Manila First District"),
    ("PH13074", "Metropolitan Manila Second District"), ("PH19087", "Maguindanao del Norte"),
    ("PH19088", "Maguindanao del Sur"), ("PH12047", "Cotabato (North Cotabato)"), ("PH19099", "Special Geographic Area"),
    ("PH05017", "Camarines Sur"), ("PH07022", "Cebu"), ("PH10013", "Bukidnon"), ("PH06045", "Negros Occidental"),
    ("PH16068", "Surigao del Sur"),
], columns=["adm2_pcode", "adm2_name"])

ADM3 = pd.DataFrame([
    ("Quezon City", "Metropolitan Manila Second District"), ("Quezon", "Bukidnon"), ("Quezon", "Quezon"),
    ("City of Isabela", "City of Isabela (not a province)"), ("Isabela", "Negros Occidental"),
    ("Naga City", "Camarines Sur"), ("City of Naga", "Cebu"), ("Cotabato City", "Maguindanao del Norte"),
    ("Bislig City", "Surigao del Sur"), ("Lucena City (Capital)", "Quezon"),
], columns=["adm3_name", "adm2_name"])


@pytest.fixture
def xw2():
    return U.build_adm2_crosswalk(ADM2)


def test_adm2_merges_and_ids(xw2):
    x = xw2.set_index("adm2_name")
    assert x.loc["Maguindanao del Norte", "unit_id"] == x.loc["Maguindanao del Sur", "unit_id"] == "PH_MAGUINDANAO_2016"
    assert x.loc["Maguindanao del Sur", "unit_name"] == "Maguindanao"
    assert U.SYNTHETIC_ID["Maguindanao"] == "PH_MAGUINDANAO_2016"
    assert x.loc["Special Geographic Area", "unit_id"] == "PH12047"  # -> Cotabato's own pcode
    assert x.loc["City of Isabela (not a province)", "unit_id"] == "PH19007"  # -> Basilan, not Isabela (PH02031)
    assert x.loc["Isabela", "unit_id"] == "PH02031"
    assert x.loc["Metropolitan Manila Second District", "unit_id"] == "PH13074"  # NCR districts kept
    assert x.loc["Special Geographic Area", "rule"].startswith("merged:")
    assert x.loc["Cebu", "rule"] == "same as COD-AB ADM2"
    assert xw2.unit_id.nunique() == len(ADM2) - 3  # three merges
    assert list(xw2.columns) == ["adm2_pcode", "adm2_name", "unit_id", "unit_name", "rule"]


def test_adm2_merge_without_parent_fails_loudly():
    with pytest.raises(AssertionError):
        U.build_adm2_crosswalk(ADM2[ADM2.adm2_name != "Basilan"])  # City of Isabela has no unit to fold into


LOCS = ["QUEZON CITY", "QUEZON", "ISABELA", "ISABELA CITY", "NAGA CITY", "COTABATO CITY", "MAGUINDANAO",
        "NORTH COTABATO", "BASILIG CITY", "LUCENA CITY", "MANILA CITY", "ATLANTIS"]


@pytest.fixture
def xwd(xw2):
    return U.build_dengue_crosswalk(LOCS, ADM2, ADM3, xw2).set_index("dengue_loc")


@pytest.mark.parametrize("loc, adm2, unit", [
    ("QUEZON CITY", "Metropolitan Manila Second District", "PH13074"),  # city first: Quezon City is not Quezon
    ("QUEZON", "Quezon", "PH04056"),  # a province name wins over same-name towns
    ("ISABELA", "Isabela", "PH02031"),  # not the City of Isabela, whose normalised name collides
    ("ISABELA CITY", "City of Isabela (not a province)", "PH19007"),  # -> Basilan
    ("NAGA CITY", "Camarines Sur", "PH05017"),  # Region V, not Cebu's City of Naga
    ("COTABATO CITY", "Maguindanao del Norte", "PH_MAGUINDANAO_2016"),
    ("MAGUINDANAO", "Maguindanao del Norte", "PH_MAGUINDANAO_2016"),
    ("NORTH COTABATO", "Cotabato (North Cotabato)", "PH12047"),
    ("BASILIG CITY", "Surigao del Sur", "PH16068"),  # misspelling of Bislig
    ("LUCENA CITY", "Quezon", "PH04056"),
    ("MANILA CITY", "Metropolitan Manila First District", "PH13039"),
])
def test_dengue_locations(xwd, loc, adm2, unit):
    assert xwd.loc[loc, "adm2_name"] == adm2
    assert xwd.loc[loc, "unit_id"] == unit
    assert xwd.loc[loc, "match"] != "UNMATCHED"


def test_dengue_match_kinds_and_notes(xwd):
    assert xwd.loc["QUEZON CITY", "match"] == "ADM3 city -> ADM2"
    assert xwd.loc["QUEZON", "match"] == "ADM2"
    assert "Region V" in xwd.loc["NAGA CITY", "note"]
    assert xwd.loc["QUEZON CITY", "note"] == ""
    assert xwd.loc["ATLANTIS", "match"] == "UNMATCHED" and pd.isna(xwd.loc["ATLANTIS", "unit_id"])
    assert len(xwd) == len(LOCS)


def test_crosswalk_csv_header_round_trip(tmp_path):
    df = pd.DataFrame({"code": ["0101", "PH01028"], "name": ["Las Piñas", "Ilocos Norte"]})
    p = tmp_path / "sub" / "xw.csv"
    U.write_csv_with_header(df, p, "Source: test.\nSecond line, with a comma")
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# Source: test.", "# Second line, with a comma"]
    back = U.read_crosswalk(p)
    assert back.equals(df)  # comments skipped, codes stay strings ("0101" keeps its zero)
    assert back.code.iloc[0] == "0101"
