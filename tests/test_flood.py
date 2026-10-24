"""bantay.flood: reading the Copernicus EMS layer records status only when the build asks for it."""

import json

from bantay import flood


def test_ems_reader_records_status_by_default(isolated_status, tmp_path, monkeypatch):
    monkeypatch.setattr(flood, "EMS", tmp_path / "ems")  # no delineation packages
    assert flood.ems_observed_flood("EMSR312") is None
    st = json.loads(isolated_status.read_text(encoding="utf-8"))
    assert st["ems_EMSR312"]["available"] is False


def test_ems_reader_can_leave_status_alone(isolated_status, tmp_path, monkeypatch):
    """The documents (make_results / make_spec) read EMS with record_status=False, so generating them never rewrites
    data/processed/status.json."""
    monkeypatch.setattr(flood, "EMS", tmp_path / "ems")
    assert flood.ems_observed_flood("EMSR312", record_status=False) is None
    assert not isolated_status.exists()
