"""Optional smart-home control through a local Home Assistant.

BMO talks to Home Assistant's REST API on the LAN with a long-lived access
token the user pastes into settings.json — no cloud, no account linking.  Like
timers, this is pre-LLM routing: qwen3:1.7b would happily invent an entity id
or "turn off" the wrong thing, so commands are parsed deterministically here
and anything we don't clearly recognise falls through to the LLM untouched.

Safety rules, because a misheard word must never open the garage:
  * the parser only matches whole utterances that are clearly commands
    ("I turned off the lights earlier" is a statement, not a command);
  * locks and covers (and anything called "garage") are only acted on when the
    spoken name exactly matches or is contained in the entity's name — never
    via fuzzy matching;
  * when several entities match equally, BMO asks instead of guessing, except
    for a plural with an area ("the kitchen lights"), where acting on all of
    them is what people mean.

`handle()` parses before touching the network, so non-commands cost nothing.
A state question about something that isn't in Home Assistant ("is the library
open?") also returns None so the LLM can answer it.
"""
import difflib
import logging
import re
import time

logger = logging.getLogger(__name__)

TIMEOUT = 5
CACHE_SECONDS = 60
FUZZY_CUTOFF = 0.75

DOMAINS = ("light", "switch", "fan", "cover", "media_player", "climate", "lock",
           "scene", "script", "input_boolean")
# Domains that can unlock, open or otherwise physically expose the house.
SAFETY_DOMAINS = ("lock", "cover")

# action -> {domain: service}
_SERVICES = {
    "on": {"light": "turn_on", "switch": "turn_on", "fan": "turn_on", "input_boolean": "turn_on",
           "media_player": "turn_on", "climate": "turn_on", "scene": "turn_on", "script": "turn_on"},
    "off": {"light": "turn_off", "switch": "turn_off", "fan": "turn_off", "input_boolean": "turn_off",
            "media_player": "turn_off", "climate": "turn_off"},
    "toggle": {"light": "toggle", "switch": "toggle", "fan": "toggle", "input_boolean": "toggle",
               "media_player": "toggle"},
    "set_brightness": {"light": "turn_on"},
    "open": {"cover": "open_cover"},
    "close": {"cover": "close_cover"},
    "lock": {"lock": "lock"},
    "unlock": {"lock": "unlock"},
    "activate": {"scene": "turn_on", "script": "turn_on"},
    "query": {d: None for d in DOMAINS},
}
_SAFETY_ACTIONS = ("open", "close", "lock", "unlock")

MSG_UNREACHABLE = "Hmm, BMO couldn't reach Home Assistant."
MSG_BAD_TOKEN = "Home Assistant didn't accept BMO's token."
MSG_HA_ERROR = "Hmm, Home Assistant had a problem doing that."


class HomeAssistantError(Exception):
    """A failure with the sentence BMO should say about it."""

    def __init__(self, spoken: str):
        super().__init__(spoken)
        self.spoken = spoken


# ---------------------------------------------------------------- parsing ---

_PREFIX_RE = re.compile(r"^(?:hey bmo|hi bmo|okay bmo|ok bmo|bmo|please|can you|could you|would you)\s+")
_SUFFIX_RE = re.compile(r"\s+(?:please|for me|bmo)$")
# Targets that are never a smart-home device: pronouns, and things other
# routes own ("turn off the music" belongs to the music player).
_NOT_TARGETS = {"it", "that", "this", "them", "these", "those", "you", "yourself", "me",
                "everything", "something", "music", "song", "volume", "sound", "timer", "alarm",
                "up", "down"}
_MAX_TARGET_WORDS = 5
_PCT = r"(?P<n>\d{1,3})\s?(?:%|percent)"

# Order matters: more specific patterns first.  Each must match the WHOLE utterance.
_PATTERNS = [
    ("set_brightness", re.compile(r"set (?:the )?brightness (?:of|on|for) (?P<t>.+?) to " + _PCT)),
    ("set_brightness", re.compile(r"(?:set|turn|put) (?P<t>.+?) (?:to|at) " + _PCT + r"(?: brightness)?")),
    ("set_brightness", re.compile(r"(?:dim|brighten) (?P<t>.+?) to (?P<n>\d{1,3})\s?(?:%|percent)?")),
    ("brighten", re.compile(r"brighten (?:up )?(?P<t>.+?)(?: up| all the way| fully)?")),
    ("onoff", re.compile(r"(?:turn|switch|shut) (?P<s>on|off) (?P<t>.+)")),
    ("onoff", re.compile(r"(?:turn|switch|shut) (?P<t>.+?) (?P<s>on|off)")),
    ("onoff_area", re.compile(r"(?P<dev>lights?|lamps?|fans?) (?P<s>on|off) in (?:the )?(?P<area>.+)")),
    ("toggle", re.compile(r"toggle (?P<t>.+)")),
    ("query", re.compile(r"(?:is|are) (?P<t>.+?) (?:currently |still |turned )?"
                         r"(?P<s>on|off|locked|unlocked|open|closed|shut)")),
    ("openclose", re.compile(r"(?P<s>open|close|shut) (?P<t>.+)")),
    ("lockunlock", re.compile(r"(?P<s>lock|unlock) (?P<t>.+)")),
    ("activate", re.compile(r"activate (?P<t>.+?)(?: scene| script)?")),
    ("activate", re.compile(r"(?:run|start) (?P<t>.+?) (?:scene|script)")),
]


def _clean_utterance(text: str) -> str:
    s = (text or "").lower().replace("’", "'")
    s = re.sub(r"[^\w%' ]+", " ", s).replace("'", "")
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:
        prev = s
        s = _PREFIX_RE.sub("", s)
        s = _SUFFIX_RE.sub("", s)
    return s


def _clean_target(raw: str):
    t = raw.strip()
    # "the lights in the bedroom" -> "bedroom lights"
    m = re.fullmatch(r"(?P<dev>.+?) in (?:the )?(?P<area>.+)", t)
    if m:
        t = f"{m['area']} {m['dev']}"
    t = re.sub(r"^(?:all (?:of )?)?(?:the |my |our )+", "", t).strip()
    t = re.sub(r"\b(?:the|my|our)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split()
    if not words or len(words) > _MAX_TARGET_WORDS or t in _NOT_TARGETS or words[0] in _NOT_TARGETS:
        return None
    return t


def parse_command(text: str):
    """Parse one utterance into {"action", "target", "value"}, or None if it isn't a smart-home command.

    Pure: no network.  Whether the target exists is `HomeAssistant.handle`'s job.
    """
    s = _clean_utterance(text)
    if not s:
        return None
    for kind, pattern in _PATTERNS:
        m = pattern.fullmatch(s)
        if not m:
            continue
        groups = m.groupdict()
        if kind == "onoff_area":
            target = _clean_target(f"{groups['area']} {groups['dev']}")
        else:
            target = _clean_target(groups["t"])
        if not target:
            return None
        value = None
        if kind in ("set_brightness",):
            action, value = "set_brightness", max(0, min(100, int(groups["n"])))
        elif kind == "brighten":
            action, value = "set_brightness", 100
        elif kind in ("onoff", "onoff_area"):
            action = groups["s"]
        elif kind == "openclose":
            action = "open" if groups["s"] == "open" else "close"
        elif kind == "lockunlock":
            action = groups["s"]
        else:  # toggle, query, activate
            action = kind
        return {"action": action, "target": target, "value": value}
    return None


# --------------------------------------------------------------- matching ---

def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith(("ches", "shes", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _norm_words(text: str) -> list:
    s = re.sub(r"[^\w ]+", " ", (text or "").lower().replace("'", "")).replace("_", " ")
    return [_singular(w) for w in s.split() if w not in ("the", "my", "our")]


def _is_safety(entity: dict) -> bool:
    return entity["domain"] in SAFETY_DOMAINS or "garage" in _norm_words(entity["name"] + " " + entity["entity_id"])


def match_entities(target: str, entities: list, action: str):
    """Return (tier, matches): tier is "exact", "contained", "fuzzy" or None.

    `matches` are the best-tier candidates among entities whose domain supports `action`.
    For a plural target with an area word ("kitchen lights") the contained tier
    includes the exact matches, so the whole group is returned.
    """
    domains = _SERVICES[action]
    candidates = [e for e in entities if e["domain"] in domains]
    t_words = _norm_words(target)
    t_joined = " ".join(t_words)
    exact, contained = [], []
    for e in candidates:
        name_words = _norm_words(e["name"])
        id_words = _norm_words(e["entity_id"].split(".", 1)[-1])
        if name_words == t_words or id_words == t_words:
            exact.append(e)
            contained.append(e)
        elif set(t_words) <= set(name_words) or set(t_words) <= set(id_words):
            contained.append(e)
    if _is_group_request(target) and len(contained) > 1:
        return "contained", contained
    if exact:
        return "exact", exact
    if contained:
        return "contained", contained
    scored = []
    for e in candidates:
        if _is_safety(e):
            continue  # never fuzzy-match anything that can open the house
        ratio = difflib.SequenceMatcher(None, t_joined, " ".join(_norm_words(e["name"]))).ratio()
        if ratio >= FUZZY_CUTOFF:
            scored.append((ratio, e))
    if not scored:
        return None, []
    best = max(r for r, _ in scored)
    return "fuzzy", [e for r, e in scored if r == best]


def _is_group_request(target: str) -> bool:
    """A plural device word plus at least one area word: "kitchen lights", not "the lights"."""
    words = re.sub(r"[^\w ]+", " ", target.lower()).split()
    return len(words) >= 2 and _singular(words[-1]) != words[-1]


def _join(names: list) -> str:
    if len(names) > 5:
        names = names[:4] + [f"{len(names) - 4} more"]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _sounds_plural(name: str) -> bool:
    last = (name.split() or [""])[-1].lower()
    return _singular(last) != last


def _subject(name: str) -> str:
    """'Front Door' -> 'the front door' (for mid-sentence queries)."""
    low = name.lower()
    return low if low.startswith("the ") else f"the {low}"


_STATE_WORDS = {"on": "on", "off": "off", "locked": "locked", "unlocked": "unlocked", "open": "open",
                "closed": "closed", "opening": "opening", "closing": "closing", "locking": "locking",
                "unlocking": "unlocking", "jammed": "jammed", "playing": "playing", "paused": "paused",
                "idle": "idle", "standby": "on standby", "heat": "heating", "cool": "cooling",
                "auto": "on auto", "unavailable": "unavailable", "unknown": "in an unknown state"}


# ------------------------------------------------------------------ client ---

class HomeAssistant:
    """Talks to one Home Assistant instance; `handle()` is the voice entry point."""

    def __init__(self, url: str, token: str, http=None, clock=time.time):
        if http is None:
            import requests
            http = requests
        self.url = url.rstrip("/")
        self.token = token
        self.http = http
        self.clock = clock
        self._cache = None
        self._cache_at = 0.0

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _check(self, resp, what: str):
        code = getattr(resp, "status_code", 0)
        if code in (401, 403):
            logger.warning(f"Home Assistant rejected the token ({code}) on {what}")
            raise HomeAssistantError(MSG_BAD_TOKEN)
        if not 200 <= code < 300:
            logger.warning(f"Home Assistant returned {code} on {what}")
            raise HomeAssistantError(MSG_HA_ERROR)

    def _get(self, path: str):
        try:
            resp = self.http.get(self.url + path, headers=self._headers, timeout=TIMEOUT)
        except Exception as e:
            logger.warning(f"Home Assistant GET {path} failed: {e}")
            raise HomeAssistantError(MSG_UNREACHABLE) from e
        self._check(resp, f"GET {path}")
        try:
            return resp.json()
        except Exception as e:
            logger.warning(f"Home Assistant GET {path} returned bad JSON: {e}")
            raise HomeAssistantError(MSG_HA_ERROR) from e

    def call_service(self, domain: str, service: str, data: dict):
        path = f"/api/services/{domain}/{service}"
        try:
            resp = self.http.post(self.url + path, headers=self._headers, json=data, timeout=TIMEOUT)
        except Exception as e:
            logger.warning(f"Home Assistant POST {path} failed: {e}")
            raise HomeAssistantError(MSG_UNREACHABLE) from e
        self._check(resp, f"POST {path}")
        logger.info(f"Home Assistant: {domain}.{service} {data}")

    def entities(self, refresh: bool = False) -> list:
        """Controllable entities from GET /api/states, cached for CACHE_SECONDS."""
        now = self.clock()
        if not refresh and self._cache is not None and now - self._cache_at < CACHE_SECONDS:
            return self._cache
        states = self._get("/api/states")
        out = []
        for st in states if isinstance(states, list) else []:
            entity_id = st.get("entity_id", "")
            domain = entity_id.split(".", 1)[0]
            if domain not in DOMAINS or "." not in entity_id:
                continue
            name = (st.get("attributes") or {}).get("friendly_name") or \
                entity_id.split(".", 1)[1].replace("_", " ").title()
            out.append({"entity_id": entity_id, "name": name, "state": st.get("state"), "domain": domain})
        self._cache, self._cache_at = out, now
        return out

    def handle(self, text: str):
        """BMO's spoken reply to a smart-home command, or None if `text` isn't one."""
        cmd = parse_command(text)
        if cmd is None:
            return None
        try:
            return self._run(cmd)
        except HomeAssistantError as e:
            return e.spoken

    def _run(self, cmd: dict):
        action, target, value = cmd["action"], cmd["target"], cmd["value"]
        # Queries want the live state, not a minute-old snapshot.
        entities = self.entities(refresh=(action == "query"))
        tier, matches = match_entities(target, entities, action)
        if not matches:
            if action == "query":
                # "is the library open?" is a question for the LLM, not about the house.
                return None
            if action in _SAFETY_ACTIONS and any(e["domain"] in _SERVICES[action] for e in entities):
                return f"BMO isn't sure which one you mean by '{target}', so BMO won't touch it."
            return f"BMO couldn't find anything called '{target}'."
        if len(matches) > 1:
            groupable = (tier == "contained" and _is_group_request(target)
                         and not any(_is_safety(e) for e in matches))
            if not groupable:
                return f"Which one? I found {_join([e['name'] for e in matches])}."
        if action == "query":
            return self._describe(target, matches)
        by_domain = {}
        for e in matches:
            by_domain.setdefault(e["domain"], []).append(e["entity_id"])
        for domain, ids in by_domain.items():
            data = {"entity_id": ids[0] if len(ids) == 1 else ids}
            if action == "set_brightness":
                data["brightness_pct"] = value
            self.call_service(domain, _SERVICES[action][domain], data)
        self._cache = None  # states just changed
        return self._confirm(action, target, value, matches)

    @staticmethod
    def _confirm(action: str, target: str, value, matches: list) -> str:
        if len(matches) > 1:
            name, verb = target[:1].upper() + target[1:], "are"
        else:
            name = matches[0]["name"]
            verb = "are" if _sounds_plural(name) else "is"
        if action == "toggle":
            return f"Okay! Toggled {name}."
        if action == "set_brightness":
            return f"Okay! {name} {verb} at {value} percent."
        if action == "open":
            return f"Okay! Opening {name}."
        if action == "close":
            return f"Okay! Closing {name}."
        if action == "lock":
            return f"Okay! {name} {verb} locked."
        if action == "unlock":
            return f"Okay! {name} {verb} unlocked."
        if action == "activate" or matches[0]["domain"] in ("scene", "script"):
            return f"Okay! Starting {name}."
        return f"Okay! {name} {verb} {action}."

    @staticmethod
    def _describe(target: str, matches: list) -> str:
        def word(e):
            return _STATE_WORDS.get(str(e["state"]).lower(), str(e["state"]))
        if len(matches) == 1:
            e = matches[0]
            verb = "are" if _sounds_plural(e["name"]) else "is"
            subject = _subject(e["name"])
            return f"{subject[:1].upper() + subject[1:]} {verb} {word(e)}."
        states = {word(e) for e in matches}
        if len(states) == 1:
            subject = _subject(target)
            return f"{subject[:1].upper() + subject[1:]} are {states.pop()}."
        return _join([f"{e['name']} is {word(e)}" for e in matches]) + "."


def from_settings(settings: dict):
    """Build a client from settings.json's {"url", "token"} block (or a whole settings dict
    containing it under "home_assistant"); None when Home Assistant isn't configured."""
    if not isinstance(settings, dict):
        return None
    block = settings.get("home_assistant", settings)
    if not isinstance(block, dict):
        return None
    url = str(block.get("url") or "").strip()
    token = str(block.get("token") or "").strip()
    if not url or not token:
        return None
    return HomeAssistant(url, token)
