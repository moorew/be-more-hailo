"""Home Assistant smart-home control.

There is no Home Assistant to test against, so a fake HTTP layer stands in for
`requests`.  The things that matter most: never act on a non-command, never
open a lock or garage on a guess, and ask rather than pick when it's ambiguous.
"""
import pytest

from core.home_assistant import (
    MSG_BAD_TOKEN,
    MSG_HA_ERROR,
    MSG_UNREACHABLE,
    HomeAssistant,
    from_settings,
    parse_command,
)

URL = "http://ha.local:8123"


def _state(entity_id, name=None, state="off"):
    attrs = {"friendly_name": name} if name else {}
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


STATES = [
    _state("light.kitchen_light", "Kitchen Light", "on"),
    _state("light.kitchen_ceiling", "Kitchen Ceiling Light", "on"),
    _state("light.kitchen_lamp", "Kitchen Lamp", "off"),
    _state("light.bedroom_light", "Bedroom Light", "on"),
    _state("light.bedroom_bedside", "Bedroom Bedside Light", "on"),
    _state("light.porch", "Porch Light"),
    _state("light.lamp", "Lamp"),
    _state("light.living_room_main", "Living Room Main Light"),
    _state("light.living_room_floor", "Living Room Floor Light"),
    _state("fan.ceiling_fan", "Ceiling Fan"),
    _state("switch.coffee_maker", "Coffee Maker"),
    _state("lock.front_door", "Front Door", "locked"),
    _state("lock.back_door", "Back Door", "locked"),
    _state("cover.garage_door", "Garage Door", "closed"),
    _state("scene.movie_night", "Movie Night", "scening"),
    _state("sensor.outside_temperature", "Outside Temperature", "12"),
    _state("input_boolean.guest_mode"),
]


class Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, states=None, get_status=200, post_status=200, raise_on=None):
        self.states = STATES if states is None else states
        self.get_status = get_status
        self.post_status = post_status
        self.raise_on = raise_on  # "get" / "post"
        self.gets, self.posts = [], []

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, headers, timeout))
        if self.raise_on == "get":
            raise TimeoutError("timed out")
        return Resp(self.get_status, self.states)

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, json))
        if self.raise_on == "post":
            raise TimeoutError("timed out")
        return Resp(self.post_status, [])


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _ha(**kw):
    http = FakeHttp(**kw)
    clock = Clock()
    return HomeAssistant(URL + "/", "TOKEN", http=http, clock=clock), http, clock


def _services(http):
    return [(url.removeprefix(URL), body) for url, body in http.posts]


# ------------------------------------------------------------------ parser ---

@pytest.mark.parametrize("text,action,target,value", [
    ("turn on the kitchen lights", "on", "kitchen lights", None),
    ("Hey BMO, turn off the kitchen lights.", "off", "kitchen lights", None),
    ("turn the kitchen lights on", "on", "kitchen lights", None),
    ("BMO turn the kitchen lights off please", "off", "kitchen lights", None),
    ("switch off the fan", "off", "fan", None),
    ("could you switch on the coffee maker", "on", "coffee maker", None),
    ("lights off in the bedroom", "off", "bedroom lights", None),
    ("turn off the lights in the bedroom", "off", "bedroom lights", None),
    ("toggle the porch light", "toggle", "porch light", None),
    ("set the living room lights to 40 percent", "set_brightness", "living room lights", 40),
    ("dim the lamp to 20%", "set_brightness", "lamp", 20),
    ("brighten the lamp", "set_brightness", "lamp", 100),
    ("set the lamp to 250%", "set_brightness", "lamp", 100),
    ("is the front door locked?", "query", "front door", None),
    ("are the kitchen lights on?", "query", "kitchen lights", None),
    ("open the garage door", "open", "garage door", None),
    ("close the garage door", "close", "garage door", None),
    ("shut the garage door", "close", "garage door", None),
    ("lock the front door", "lock", "front door", None),
    ("please unlock the front door", "unlock", "front door", None),
    ("activate movie night", "activate", "movie night", None),
    ("turn on movie night", "on", "movie night", None),
    # Parsed even though no such entity exists — handle() says it couldn't find it.
    ("turn on the radio", "on", "radio", None),
])
def test_parser_positives(text, action, target, value):
    assert parse_command(text) == {"action": action, "target": target, "value": value}


@pytest.mark.parametrize("text", [
    # Volume belongs to the music/volume routes, and "up"/"down" aren't on/off.
    "turn the music up",
    "turn up the heat",
    "turn off the music",
    "what's the weather",
    "I turned off the lights earlier",
    "the lights are off",
    "can you turn it off",
    "turn on",
    "set a timer for 5 minutes",
    "set the thermostat to 21",  # no percent: could be a temperature, so not a brightness
    "shut down",
    "tell me a story about a lamp that turned on",
    "",
])
def test_parser_negatives(text):
    assert parse_command(text) is None


# --------------------------------------------------------------- matching ---

def test_exact_match_calls_service_and_confirms():
    ha, http, _ = _ha()
    assert ha.handle("toggle the porch light") == "Okay! Toggled Porch Light."
    assert _services(http) == [("/api/services/light/toggle", {"entity_id": "light.porch"})]
    _, headers, timeout = http.gets[0]
    assert headers["Authorization"] == "Bearer TOKEN" and timeout == 5


def test_singular_spoken_plural_name_still_matches():
    ha, http, _ = _ha()
    assert ha.handle("switch off the fan") == "Okay! Ceiling Fan is off."
    assert _services(http) == [("/api/services/fan/turn_off", {"entity_id": "fan.ceiling_fan"})]


def test_plural_with_area_acts_on_the_whole_group():
    ha, http, _ = _ha()
    assert ha.handle("turn off the kitchen lights") == "Okay! Kitchen lights are off."
    (path, body), = _services(http)
    assert path == "/api/services/light/turn_off"
    assert body["entity_id"] == ["light.kitchen_light", "light.kitchen_ceiling"]


def test_area_phrasing_groups_bedroom_lights():
    ha, http, _ = _ha()
    assert ha.handle("lights off in the bedroom") == "Okay! Bedroom lights are off."
    assert _services(http)[0][1]["entity_id"] == ["light.bedroom_light", "light.bedroom_bedside"]


def test_brightness_on_a_group():
    ha, http, _ = _ha()
    assert ha.handle("set the living room lights to 40 percent") == "Okay! Living room lights are at 40 percent."
    assert _services(http) == [("/api/services/light/turn_on",
                                {"entity_id": ["light.living_room_main", "light.living_room_floor"],
                                 "brightness_pct": 40})]


def test_dim_and_brighten_a_single_light():
    ha, http, _ = _ha()
    assert ha.handle("dim the lamp to 20%") == "Okay! Lamp is at 20 percent."
    assert ha.handle("brighten the lamp") == "Okay! Lamp is at 100 percent."
    assert [b["brightness_pct"] for _, b in _services(http)] == [20, 100]
    assert all(b["entity_id"] == "light.lamp" for _, b in _services(http))


def test_singular_ambiguity_asks_instead_of_guessing():
    ha, http, _ = _ha()
    reply = ha.handle("turn on the kitchen light")  # exact "Kitchen Light" wins — no question
    assert reply == "Okay! Kitchen Light is on."
    reply = ha.handle("turn off the bedroom light")
    assert reply == "Okay! Bedroom Light is off."
    http.posts.clear()
    assert ha.handle("toggle the kitchen") == "Which one? I found Kitchen Light, Kitchen Ceiling Light and Kitchen Lamp."
    assert http.posts == []


def test_plural_without_area_asks():
    ha, http, _ = _ha()
    reply = ha.handle("turn off the lights")
    assert reply.startswith("Which one? I found ")
    assert http.posts == []


def test_fuzzy_match_for_ordinary_devices():
    ha, http, _ = _ha()
    assert ha.handle("turn on the cofee maker") == "Okay! Coffee Maker is on."
    assert _services(http) == [("/api/services/switch/turn_on", {"entity_id": "switch.coffee_maker"})]


def test_entity_without_friendly_name_uses_derived_name():
    ha, http, _ = _ha()
    assert {"entity_id": "input_boolean.guest_mode", "name": "Guest Mode", "state": "off",
            "domain": "input_boolean"} in ha.entities()
    assert ha.handle("turn on guest mode") == "Okay! Guest Mode is on."
    assert _services(http) == [("/api/services/input_boolean/turn_on", {"entity_id": "input_boolean.guest_mode"})]


def test_unsupported_domains_are_not_listed():
    ha, _, _ = _ha()
    assert all(not e["entity_id"].startswith("sensor.") for e in ha.entities())


def test_scene_activation_both_phrasings():
    ha, http, _ = _ha()
    assert ha.handle("activate movie night") == "Okay! Starting Movie Night."
    assert ha.handle("turn on movie night") == "Okay! Starting Movie Night."
    assert _services(http) == [("/api/services/scene/turn_on", {"entity_id": "scene.movie_night"})] * 2


def test_unknown_device_is_reported():
    ha, http, _ = _ha()
    assert ha.handle("turn on the patio heater") == "BMO couldn't find anything called 'patio heater'."
    assert ha.handle("turn on the radio") == "BMO couldn't find anything called 'radio'."
    assert http.posts == []


def test_wrong_domain_for_action_is_not_found():
    ha, http, _ = _ha()
    # Brightness only applies to lights.
    assert ha.handle("dim the coffee maker to 30%") == "BMO couldn't find anything called 'coffee maker'."
    assert http.posts == []


# ------------------------------------------------------------- lock safety ---

def test_lock_and_unlock_exact():
    ha, http, _ = _ha()
    assert ha.handle("lock the front door") == "Okay! Front Door is locked."
    assert ha.handle("unlock the front door") == "Okay! Front Door is unlocked."
    assert _services(http) == [("/api/services/lock/lock", {"entity_id": "lock.front_door"}),
                               ("/api/services/lock/unlock", {"entity_id": "lock.front_door"})]


def test_garage_open_close():
    ha, http, _ = _ha()
    assert ha.handle("open the garage door") == "Okay! Opening Garage Door."
    assert ha.handle("close the garage") == "Okay! Closing Garage Door."
    assert _services(http) == [("/api/services/cover/open_cover", {"entity_id": "cover.garage_door"}),
                               ("/api/services/cover/close_cover", {"entity_id": "cover.garage_door"})]


@pytest.mark.parametrize("text", [
    "unlock the frnt door",      # close enough for difflib, never for a lock
    "unlock the font door",
    "open the garbage door",
])
def test_locks_and_covers_never_fuzzy_match(text):
    ha, http, _ = _ha()
    reply = ha.handle(text)
    assert "isn't sure which one" in reply
    assert http.posts == []


def test_ambiguous_unlock_asks():
    ha, http, _ = _ha()
    assert ha.handle("unlock the doors") == "Which one? I found Front Door and Back Door."
    assert ha.handle("unlock the door") == "Which one? I found Front Door and Back Door."
    assert http.posts == []


# ------------------------------------------------------------------ queries ---

def test_query_single_and_group():
    ha, _, _ = _ha()
    assert ha.handle("is the front door locked?") == "The front door is locked."
    assert ha.handle("is the garage door open?") == "The garage door is closed."
    assert ha.handle("are the bedroom lights on?") == "The bedroom lights are on."
    assert ha.handle("are the kitchen lights on") == "The kitchen lights are on."


def test_query_mixed_group_lists_each():
    states = [_state("light.desk_a", "Office Desk Light", "on"), _state("light.desk_b", "Office Shelf Light", "off")]
    ha, _, _ = _ha(states=states)
    assert ha.handle("are the office lights on?") == "Office Desk Light is on and Office Shelf Light is off."


def test_query_about_something_not_in_the_house_falls_through():
    ha, _, _ = _ha()
    assert ha.handle("is the library open?") is None


def test_query_bypasses_cache_for_fresh_state():
    ha, http, _ = _ha()
    ha.entities()
    ha.handle("is the front door locked")
    assert len(http.gets) == 2


# --------------------------------------------------------------- non-commands ---

@pytest.mark.parametrize("text", ["what's the weather", "I turned off the lights earlier", "tell me a joke"])
def test_non_commands_make_no_network_calls(text):
    ha, http, _ = _ha()
    assert ha.handle(text) is None
    assert http.gets == [] and http.posts == []


# ----------------------------------------------------------------- caching ---

def test_states_are_cached_for_60_seconds():
    ha, http, clock = _ha()
    ha.entities()
    clock.t += 59
    ha.entities()
    assert len(http.gets) == 1
    clock.t += 2
    ha.entities()
    assert len(http.gets) == 2
    assert http.gets[0][0] == URL + "/api/states"


def test_commands_reuse_cache_until_a_service_call_changes_state():
    ha, http, _ = _ha()
    ha.handle("turn on the patio heater")
    ha.handle("turn on the hot tub")
    assert len(http.gets) == 1
    ha.handle("toggle the porch light")
    ha.handle("toggle the porch light")
    assert len(http.gets) == 2  # cache dropped after the first toggle


# ------------------------------------------------------------------ errors ---

def test_timeout_fetching_states():
    ha, http, _ = _ha(raise_on="get")
    assert ha.handle("turn on the lamp") == MSG_UNREACHABLE == "Hmm, BMO couldn't reach Home Assistant."


def test_timeout_calling_service():
    ha, _, _ = _ha(raise_on="post")
    assert ha.handle("turn on the lamp") == MSG_UNREACHABLE


def test_bad_token():
    ha, http, _ = _ha(get_status=401)
    assert ha.handle("turn on the lamp") == MSG_BAD_TOKEN == "Home Assistant didn't accept BMO's token."
    assert http.posts == []


def test_bad_token_on_service_call():
    ha, _, _ = _ha(post_status=401)
    assert ha.handle("turn on the lamp") == MSG_BAD_TOKEN


@pytest.mark.parametrize("kw", [{"get_status": 500}, {"post_status": 500}])
def test_server_error(kw):
    ha, _, _ = _ha(**kw)
    assert ha.handle("turn on the lamp") == MSG_HA_ERROR


def test_error_does_not_poison_cache():
    ha, http, _ = _ha(get_status=500)
    ha.handle("turn on the lamp")
    http.get_status = 200
    assert ha.handle("turn on the lamp") == "Okay! Lamp is on."


# ------------------------------------------------------------ from_settings ---

def test_from_settings_block():
    ha = from_settings({"url": "http://homeassistant.local:8123/", "token": "abc"})
    assert isinstance(ha, HomeAssistant)
    assert ha.url == "http://homeassistant.local:8123" and ha.token == "abc"


def test_from_settings_nested_block():
    ha = from_settings({"home_assistant": {"url": "http://homeassistant.local:8123", "token": "abc"}})
    assert isinstance(ha, HomeAssistant)


@pytest.mark.parametrize("settings", [
    None, {}, {"url": "", "token": "abc"}, {"url": "http://x", "token": ""},
    {"url": "http://x"}, {"home_assistant": None}, {"home_assistant": {"url": " ", "token": " "}},
])
def test_from_settings_unconfigured(settings):
    assert from_settings(settings) is None
