"""settings.json is shared: the volume writer used to dump {"volume": ...} and
wipe the hand-edited briefing block on the first volume change."""
import json

from core.briefing.settings import DEFAULTS, load_briefing_settings, update_settings


def test_volume_update_keeps_the_briefing_block(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume": 0.5, "briefing": {"location": "Paris", "window": ["08:00", "10:00"]}}))
    update_settings({"volume": 0.9}, path=str(path))
    data = json.loads(path.read_text())
    assert data["volume"] == 0.9
    assert data["briefing"] == {"location": "Paris", "window": ["08:00", "10:00"]}


def test_update_creates_missing_file(tmp_path):
    path = tmp_path / "settings.json"
    update_settings({"volume": 0.3}, path=str(path))
    assert json.loads(path.read_text()) == {"volume": 0.3}


def test_unreadable_file_is_not_clobbered(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"briefing": {"location": "Paris"')   # half-edited by hand
    update_settings({"volume": 0.3}, path=str(path))
    assert path.read_text() == '{"briefing": {"location": "Paris"'


def test_briefing_defaults_fill_missing_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"briefing": {"news": {"count": 9}, "extras": {"sun": False},
                                             "days": ["Monday", "TUE"]}}))
    s = load_briefing_settings(str(path))
    assert s["news"]["count"] == 5                       # clamped to 3-5
    assert s["news"]["region"] == "ca-en"                # nested default kept
    assert s["extras"]["sun"] is False and s["extras"]["reminders"] is True
    assert s["days"] == ["mon", "tue"]
    assert s["window"] == DEFAULTS["window"]


def test_no_file_gives_defaults(tmp_path):
    s = load_briefing_settings(str(tmp_path / "missing.json"))
    assert s["location"] == "Brantford" and s["enabled"] is True and s["talk_mood"] == "happy"
