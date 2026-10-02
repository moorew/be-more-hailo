"""Environment Canada weather alerts: parsing the real GeoMet response, and
announcing each alert only once.  Network calls are faked."""
import datetime
import json
import os

from core import weather_alerts as wa

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "eccc_alerts_canada.json")
# The fixture was fetched 2026-10-02 15:32 UTC; alerts end 17:45 / expire ~19:45 UTC.
NOW_TS = datetime.datetime(2026, 10, 2, 15, 30, tzinfo=datetime.timezone.utc).timestamp()
DAY = 24 * 3600


def real():
    with open(FIXTURE) as f:
        return json.load(f)


def feature(fid, kind, name, area="Brant", status="issued",
            published="2026-10-02T10:00:00Z", expires="2026-10-02T20:00:00Z", ends="2026-10-02T19:00:00Z"):
    return {"type": "Feature", "id": fid, "geometry": None, "properties": {
        "alert_type": kind, "alert_name_en": name, "feature_name_en": area, "status_en": status,
        "publication_datetime": published, "expiration_datetime": expires, "event_end_datetime": ends}}


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def get(data, now=NOW_TS):
    return wa.get_alerts(43.13, -80.27, fetch=lambda url: data, clock=lambda: now)


# --- parsing -----------------------------------------------------------------

def test_real_response_dedupes_sub_areas_and_orders_by_severity():
    alerts = get(real())
    assert [a["title"] for a in alerts] == ["Storm surge warning", "Fog advisory"]
    surge, fog = alerts
    assert surge["kind"] == "warning" and fog["kind"] == "advisory"
    assert fog["id"] == "133141280898885853202610020501"
    assert fog["area"] == "Ft. Simpson Region including Jean Marie River, Wrigley Region"
    assert surge["area"] == "Coastline of Yukon incl. Herschel Island"
    assert fog["issued"] == datetime.datetime(2026, 10, 2, 14, 8, 55, 530000,
                                              tzinfo=datetime.timezone.utc).timestamp()
    assert fog["expires"] > NOW_TS


def test_url_is_a_small_bbox_around_the_point():
    urls = []
    wa.get_alerts(43.13, -80.27, fetch=lambda url: urls.append(url) or collection())
    assert urls[0].startswith("https://api.weather.gc.ca/collections/weather-alerts/items?")
    assert "lang=en" in urls[0] and "bbox=-80.2800,43.1200,-80.2600,43.1400" in urls[0]


def test_severity_order_warning_watch_advisory_statement():
    alerts = get(collection(
        feature("s_1", "statement", "special weather statement"),
        feature("a_1", "advisory", "fog advisory"),
        feature("w_1", "warning", "freezing rain warning"),
        feature("h_1", "watch", "severe thunderstorm watch"),
    ))
    assert [a["kind"] for a in alerts] == ["warning", "watch", "advisory", "statement"]
    assert alerts[0] == {"id": "w", "kind": "warning", "title": "Freezing rain warning", "area": "Brant",
                         "expires": wa._epoch("2026-10-02T20:00:00Z"), "issued": wa._epoch("2026-10-02T10:00:00Z")}


def test_expired_ended_and_cancelled_alerts_are_dropped():
    alerts = get(collection(
        feature("ok_1", "warning", "rainfall warning"),
        feature("ended_1", "warning", "wind warning", status="ended"),
        feature("cxl_1", "watch", "tornado watch", status="cancelled"),
        feature("old_1", "advisory", "fog advisory", expires="2026-10-02T12:00:00Z"),
        feature("over_1", "advisory", "heat advisory", ends="2026-10-02T15:00:00Z"),
    ))
    assert [a["id"] for a in alerts] == ["ok"]


def test_no_alerts_is_empty_list_and_network_failure_is_none():
    assert get(collection()) == []

    def boom(url):
        raise OSError("no route to host")
    assert wa.get_alerts(43.13, -80.27, fetch=boom) is None


def test_same_name_twice_for_one_point_is_spoken_once():
    alerts = get(collection(
        feature("old_1", "warning", "rainfall warning", published="2026-10-02T08:00:00Z"),
        feature("new_1", "warning", "rainfall warning", published="2026-10-02T11:00:00Z"),
    ))
    assert [a["id"] for a in alerts] == ["new"]


def test_garbage_never_raises():
    for junk in (None, "oops", 42, [], {}, {"features": "x"}, {"features": None}):
        assert get(junk) is None
    weird = collection(None, 7, {"id": "x"}, {"properties": "nope"},
                       feature("", "warning", "wind warning"),
                       feature("u_1", "mystery", "nothing to see"),
                       feature("t_1", None, "snowfall warning", published="yesterday", expires=None, ends=12),
                       feature("ok_1", "watch", "tornado watch"))
    alerts = get(weird)
    assert [(a["id"], a["kind"]) for a in alerts] == [("t", "warning"), ("ok", "watch")]
    assert alerts[0]["issued"] is None and alerts[0]["expires"] is None


# --- spoken ------------------------------------------------------------------

def test_spoken_grammar():
    def say(kind, title):
        return wa.spoken({"kind": kind, "title": title}, "Brantford")
    assert say("warning", "Freezing rain warning") == \
        "Heads up! Environment Canada has issued a freezing rain warning for Brantford."
    assert say("advisory", "Extreme cold advisory").startswith("Heads up! Environment Canada has issued an extreme")
    assert "issued an orange warning" in say("warning", "Orange warning")
    assert "issued a special weather statement for Brantford." in say("statement", "Special weather statement")
    assert "issued a special weather statement for Brantford." in say("statement", "Weather")
    assert "issued an air quality statement" in say("statement", "Air quality statement")


# --- watcher -----------------------------------------------------------------

ALERT = {"id": "A1", "kind": "warning", "title": "Wind warning", "area": "Brant", "expires": None, "issued": 1.0}
OTHER = {"id": "B2", "kind": "statement", "title": "Special weather statement", "area": "Brant",
         "expires": None, "issued": 2.0}


class Feed:
    def __init__(self):
        self.result, self.now = [], NOW_TS

    def get(self, lat, lon):
        return self.result

    def watcher(self, path):
        return wa.AlertWatcher(43.13, -80.27, "Brantford", state_path=path, get=self.get, clock=lambda: self.now)


def test_watcher_reports_new_ids_once(tmp_path):
    feed = Feed()
    w = feed.watcher(str(tmp_path / "seen.json"))
    feed.result = [ALERT]
    assert w.poll() == [ALERT]
    assert w.poll() == []
    feed.result = [ALERT, OTHER]
    assert w.poll() == [OTHER]
    assert w.active() == [ALERT, OTHER]


def test_watcher_state_survives_restart(tmp_path):
    path = str(tmp_path / "cache" / "seen.json")
    feed = Feed()
    feed.result = [ALERT]
    assert feed.watcher(path).poll() == [ALERT]
    assert feed.watcher(path).poll() == []


def test_network_failure_keeps_state_and_last_active(tmp_path):
    path = str(tmp_path / "seen.json")
    feed = Feed()
    feed.result = [ALERT]
    w = feed.watcher(path)
    w.poll()
    feed.result = None
    assert w.poll() == [] and w.active() == [ALERT]
    feed.result = [ALERT]
    assert w.poll() == [] and feed.watcher(path).poll() == []


def test_failure_drops_alerts_that_expired_meanwhile(tmp_path):
    feed = Feed()
    w = feed.watcher(str(tmp_path / "seen.json"))
    feed.result = [dict(ALERT, expires=NOW_TS + 60)]
    w.poll()
    feed.result, feed.now = None, NOW_TS + 120
    w.poll()
    assert w.active() == []


def test_seen_ids_pruned_after_a_week_unseen(tmp_path):
    path = str(tmp_path / "seen.json")
    feed = Feed()
    feed.result = [ALERT]
    feed.watcher(path).poll()
    feed.result, feed.now = [], NOW_TS + 8 * DAY
    feed.watcher(path).poll()
    with open(path) as f:
        assert json.load(f)["seen"] == {}


def test_long_running_alert_is_not_repeated_after_a_week(tmp_path):
    feed = Feed()
    w = feed.watcher(str(tmp_path / "seen.json"))
    feed.result = [ALERT]
    for day in range(10):
        feed.now = NOW_TS + day * DAY
        assert w.poll() == ([ALERT] if day == 0 else [])


def test_corrupt_state_file_starts_fresh(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{not json")
    feed = Feed()
    feed.result = [ALERT]
    assert feed.watcher(str(path)).poll() == [ALERT]
