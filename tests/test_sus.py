"""System Usability Scale scoring and anonymous storage."""

import pytest

import sus


def test_score_examples():
    assert sus.score([3] * 10) == 50.0
    assert sus.score([5, 1] * 5) == 100.0  # agree with every positive item, disagree with every negative one
    assert sus.score([1, 5] * 5) == 0.0
    assert sus.score([4, 2, 4, 2, 4, 2, 4, 2, 4, 2]) == 75.0


@pytest.mark.parametrize("bad", [[3] * 9, [3] * 11, [0] + [3] * 9, [6] + [3] * 9])
def test_score_rejects_bad_answers(bad):
    with pytest.raises(ValueError):
        sus.score(bad)


def test_ten_standard_items_and_no_identifiers():
    assert len(sus.ITEMS) == 10
    assert sus.ROLES == ["DOH regional office", "LGU health office", "DRRM office", "Other"]
    assert not {"name", "email", "phone", "organisation", "organization"} & set(sus.FIELDS)


def test_save_appends_to_env_path(sus_csv):
    assert sus.path() == sus_csv
    assert sus.load().empty
    s1 = sus.save("LGU health office", [4, 2] * 5, "Completed", 12)
    s2 = sus.save("Other", [3] * 10, "Partly completed", None)
    r = sus.load()
    assert (s1, s2) == (75.0, 50.0)
    assert len(r) == 2 and r.sus.mean() == 62.5
    assert list(r.columns) == sus.FIELDS
    assert r.role.tolist() == ["LGU health office", "Other"]


def test_save_rejects_unknown_role(sus_csv):
    with pytest.raises(ValueError):
        sus.save("Juan dela Cruz", [3] * 10, "Completed", 5)
    assert not sus_csv.exists()
