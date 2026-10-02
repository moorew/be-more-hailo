"""Active Environment Canada weather alerts for a point, so BMO can say "heads up".

Why: the forecast tells you it will rain; only the official alert tells you a
freezing rain warning is out for Brant county.  BMO polls this, speaks new
alerts once, and the morning briefing reads the still-active ones.

Source: the Meteorological Service of Canada (MSC) GeoMet OGC API, no key:

    https://api.weather.gc.ca/collections/weather-alerts/items?f=json&lang=en&limit=100
        &bbox=-80.28,43.12,-80.26,43.14          (lon_min,lat_min,lon_max,lat_max)

The bbox is intersected with each alert's polygon, so a tiny box around the
point acts as a point query.  (The old weather.gc.ca/rss/warning/*.xml ATOM
feeds now 404.)  The response is a GeoJSON FeatureCollection; per feature we
use these `properties`:

    alert_type            "warning" | "watch" | "advisory" | "statement"
    alert_name_en         "fog advisory", "storm surge warning" (lower case)
    feature_name_en       the forecast region, e.g. "Brant" / "Wrigley Region"
    status_en             "issued", "continued", ... "ended" / "cancelled"
    publication_datetime  when this version was issued (ISO 8601, Z)
    expiration_datetime   when this bulletin lapses unless re-issued
    event_end_datetime    when the hazard itself is expected to end

Quirks:
  * One alert is returned once per forecast sub-region.  The feature `id` is
    "<alert id>_<feature_id>", e.g. "1331...0501_fea1-2456" and
    "1331...0501_fea1-2457" are the same fog advisory for two regions; we
    de-duplicate on the part before the last "_", which also stays the same
    when the alert is "continued" (re-published), so it is a stable id for
    "already announced".
  * An alert that has finished still comes back for a while with status
    "ended"/"cancelled"; we drop those, and anything past its expiration or
    event-end time.
  * `lang=en` only switches the HTML/link language; both _en and _fr fields
    are always present.  We only read the _en ones.
  * The default page size is 10, so we ask for limit=100.

Network calls are injectable (`fetch`, `get`, `clock`) so tests run offline.
"""
import datetime
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

API_URL = "https://api.weather.gc.ca/collections/weather-alerts/items"
BBOX_HALF_DEG = 0.01            # ~1 km box around the point
SEEN_MAX_AGE_S = 7 * 24 * 3600
KINDS = ("warning", "watch", "advisory", "statement")   # most severe first
_RANK = {k: i for i, k in enumerate(KINDS)}
_DEAD_STATUSES = {"ended", "cancelled", "canceled", "expired"}
_UA = "Mozilla/5.0 (X11; Linux aarch64) BMO-weather-alerts"


def alerts_url(lat: float, lon: float) -> str:
    d = BBOX_HALF_DEG
    bbox = f"{lon - d:.4f},{lat - d:.4f},{lon + d:.4f},{lat + d:.4f}"
    return f"{API_URL}?f=json&lang=en&limit=100&bbox={bbox}"


def _fetch_json(url: str, timeout: float = 10):
    import requests
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
    resp.raise_for_status()
    return resp.json()


def _epoch(raw):
    """'2026-10-02T14:08:55.530Z' -> epoch seconds; None if missing/garbled."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _kind(props: dict, name: str):
    kind = str(props.get("alert_type") or "").strip().lower()
    if kind in _RANK:
        return kind
    for k in KINDS:                       # fall back to the name: "... warning"
        if name.lower().endswith(k):
            return k
    return None


def _parse_feature(feat, now: float):
    """One GeoJSON feature -> alert dict, or None if malformed / no longer active."""
    if not isinstance(feat, dict) or not isinstance(feat.get("properties"), dict):
        return None
    props = feat["properties"]
    if str(props.get("status_en") or "").strip().lower() in _DEAD_STATUSES:
        return None
    name = str(props.get("alert_name_en") or props.get("alert_short_name_en") or "").strip()
    kind = _kind(props, name)
    if not name or kind is None:
        return None
    raw_id = str(feat.get("id") or props.get("id") or "")
    alert_id = raw_id.rsplit("_", 1)[0] if "_" in raw_id else raw_id
    if not alert_id:
        return None
    expires = _epoch(props.get("expiration_datetime"))
    ends = _epoch(props.get("event_end_datetime"))
    if any(t is not None and t <= now for t in (expires, ends)):
        return None
    return {
        "id": alert_id,
        "kind": kind,
        "title": name[0].upper() + name[1:],
        "area": str(props.get("feature_name_en") or "").strip(),
        "expires": expires,
        "issued": _epoch(props.get("publication_datetime")),
    }


def parse_alerts(data, now: float):
    """FeatureCollection -> de-duplicated active alerts, most severe first.

    None if `data` isn't a FeatureCollection-shaped dict at all."""
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        return None
    by_id = {}
    for feat in data["features"]:
        alert = _parse_feature(feat, now)
        if alert is None:
            continue
        seen = by_id.get(alert["id"])
        if seen is None:
            by_id[alert["id"]] = alert
        elif alert["area"] and alert["area"] not in seen["area"].split(", "):
            seen["area"] = ", ".join(a for a in (seen["area"], alert["area"]) if a)
    # Two separate bulletins with the same name for one point: say it once (newest wins).
    by_title = {}
    for alert in by_id.values():
        prev = by_title.get(alert["title"].lower())
        if prev is None or (alert["issued"] or 0) > (prev["issued"] or 0):
            by_title[alert["title"].lower()] = alert
    return sorted(by_title.values(), key=lambda a: (_RANK[a["kind"]], -(a["issued"] or 0)))


def get_alerts(lat: float, lon: float, fetch=None, clock=time.time):
    """Active ECCC alerts covering (lat, lon).

    Returns [{"id", "kind", "title", "area", "expires", "issued"}] most severe
    first, [] when there are none, or None when the API couldn't be reached
    or returned something unusable.  Never raises."""
    fetch = fetch or _fetch_json
    try:
        data = fetch(alerts_url(lat, lon))
    except Exception as e:
        logger.warning("weather alerts fetch failed: %s", e)
        return None
    try:
        alerts = parse_alerts(data, clock())
    except Exception as e:                # belt and braces: garbage must not crash the poller
        logger.warning("weather alerts parse failed: %s", e)
        return None
    if alerts is None:
        logger.warning("weather alerts: unexpected response shape")
    return alerts


def spoken(alert: dict, place: str) -> str:
    """'Heads up! Environment Canada has issued a freezing rain warning for Brantford.'"""
    title = str(alert.get("title") or "").strip().lower()
    if alert.get("kind") == "statement" and "statement" not in title:
        title = "special weather statement"
    title = title or "weather alert"
    article = "an" if title[0] in "aeiou" else "a"
    return f"Heads up! Environment Canada has issued {article} {title} for {place}."


class AlertWatcher:
    """Polls get_alerts and hands back each alert only the first time it's seen.

    Announced ids are kept in `state_path` (with when they were last seen
    active) so a restart doesn't repeat them; ids not seen for 7 days are pruned."""

    def __init__(self, lat, lon, place, state_path=os.path.join("cache", "alerts_seen.json"),
                 get=get_alerts, clock=time.time):
        self.lat, self.lon, self.place = lat, lon, place
        self.state_path = state_path
        self._get = get
        self._clock = clock
        self._active = []
        self._seen = self._load()

    def _load(self) -> dict:
        try:
            with open(self.state_path) as f:
                seen = json.load(f).get("seen", {})
            return {str(k): float(v) for k, v in seen.items()}
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.warning("alerts state unreadable (%s), starting fresh", e)
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"seen": self._seen}, f)
            os.replace(tmp, self.state_path)
        except Exception as e:
            logger.warning("could not save alerts state: %s", e)

    def poll(self) -> list:
        """Alerts not announced before.  On a network failure: [] and state untouched."""
        now = self._clock()
        try:
            alerts = self._get(self.lat, self.lon)
        except Exception as e:
            logger.warning("weather alerts poll failed: %s", e)
            alerts = None
        if alerts is None:
            # Keep what we had, minus anything that has since expired.
            self._active = [a for a in self._active if a.get("expires") is None or a["expires"] > now]
            return []
        self._active = list(alerts)
        new = [a for a in alerts if a["id"] not in self._seen]
        for a in alerts:                  # last-seen time, so a week-long alert isn't re-announced
            self._seen[a["id"]] = now
        self._seen = {k: t for k, t in self._seen.items() if now - t < SEEN_MAX_AGE_S}
        self._save()
        return new

    def active(self) -> list:
        """The active alerts from the last poll (for the morning briefing)."""
        return list(self._active)
