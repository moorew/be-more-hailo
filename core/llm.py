import base64
import os
import threading
import time
import requests
import logging
import re
import json
import urllib.parse
import numpy as np
from .config import LLM_URL, LLM_KEEP_ALIVE, LLM_MODEL, FAST_LLM_MODEL, VISION_MODEL, VLM_HEF_PATH, get_system_prompt, get_current_context
from .tts import add_pronunciation
from .search import get_weather, search_web, search_images
from .timers import (describe_duration, describe_when, match_reminders, parse_reminder_query,
                     parse_reminder_request, parse_timer_request)
from .briefing import intents as briefing_intents

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Hailo VLM (Vision Language Model) singleton
# --------------------------------------------------------------------------- #
# Lazy-loaded per image-analysis request and released immediately afterwards.
#
# The Hailo-10H is single-tenant (see core/config.py): a cached VLM would hold
# /dev/hailo0 for the life of the process, so the first photo BMO ever took
# would permanently starve hailo-ollama and BMO could never think again.  We pay
# the ~3 s init cost per photo to keep the LLM alive — photos are rare, thinking
# is not.
_vlm_instance = None
_vlm_vdevice = None
_vlm_thread = None  # in-flight inference thread, if any


def _vlm_inflight() -> bool:
    """True while a VLM inference thread is still touching the device."""
    return _vlm_thread is not None and _vlm_thread.is_alive()


def _release_vlm():
    """Tear down the VLM and hand /dev/hailo0 back to hailo-ollama."""
    global _vlm_instance, _vlm_vdevice
    _vlm_instance = None
    if _vlm_vdevice is not None:
        try:
            _vlm_vdevice.release()
        except Exception as exc:
            logger.warning(f"VDevice release failed: {exc}")
        _vlm_vdevice = None


def _get_vlm():
    """Return a (vlm, frame_shape, frame_dtype) tuple, initialising on first call."""
    global _vlm_instance, _vlm_vdevice

    if _vlm_instance is not None:
        shape = _vlm_instance.input_frame_shape()
        dtype = _vlm_instance.input_frame_format_type()
        return _vlm_instance, shape, dtype

    hef = VLM_HEF_PATH
    if not os.path.isabs(hef):
        # Resolve relative to project root (where the scripts live)
        hef = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), hef)

    if not os.path.exists(hef):
        raise FileNotFoundError(f"VLM HEF not found at {hef}. Run setup.sh to download it.")

    from hailo_platform import VDevice
    from hailo_platform.genai import VLM

    logger.info(f"Initialising Hailo VLM from {hef} ...")
    # Hold the device only locally until both the VDevice and VLM succeed —
    # otherwise a failed VLM init (e.g. HAILO_INVALID_HEF when hailo-ollama
    # already owns the NPU) leaks /dev/hailo0 for the rest of the process,
    # which starves the LLM service into a SEGV loop.
    vdevice = VDevice()
    try:
        instance = VLM(vdevice, hef)
    except Exception:
        try:
            vdevice.release()
        except Exception:
            pass
        del vdevice
        raise

    _vlm_vdevice = vdevice
    _vlm_instance = instance
    shape = _vlm_instance.input_frame_shape()
    dtype = _vlm_instance.input_frame_format_type()
    logger.info(f"VLM ready — frame shape {shape}, dtype {dtype}")
    return _vlm_instance, shape, dtype


def _label(r) -> str:
    """'the pasta timer', 'the timer', 'your reminder to put the bins out'."""
    if r.get("name"):
        return f"the {r['name']} timer"
    if r.get("kind", "timer") == "timer" and r.get("message") == "Timer is up!":
        return "the timer"
    what = r.get("message", "").rstrip("!.")
    return f"your reminder to {what[:1].lower()}{what[1:]}" if what and what != "Reminder" else "your reminder"


def _or_list(labels):
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " or " + labels[-1]


def _describe_item(r, lead=False) -> str:
    """'the pasta timer has 4 minutes left' / 'your reminder to call mum is tomorrow at 9 a.m.'"""
    left = r["due"] - time.time()
    label = _label(r)
    if lead:
        label = label[:1].upper() + label[1:]
    if r.get("kind", "timer") == "timer" and left < 12 * 3600:
        if left < 60:
            return f"{label} has {max(1, int(left))} seconds left"
        m, sec = divmod(int(left), 60)
        h, m = divmod(m, 60)
        parts = ([f"{h} hour{'s' if h != 1 else ''}"] if h else []) + \
                ([f"{m} minute{'s' if m != 1 else ''}"] if m else [])
        return f"{label} has {' '.join(parts)} left"
    return f"{label} is {describe_when(r['due'])}"


VLM_NPU_WAIT_S = 25


def _free_npu_for_vlm():
    """Ask hailo-ollama to unload its model so the VLM can open the NPU.

    hailo-ollama holds the NPU exclusively while a model is loaded, and BMO
    pins the LLM there (keep_alive -1), so the VLM could never start ("eyes
    aren't working").  A request with keep_alive 0 unloads it; the device is
    free ~5 s later.  The LLM is reloaded in the background afterwards."""
    payload = {"model": FAST_LLM_MODEL, "messages": [{"role": "user", "content": "hi"}],
               "stream": False, "keep_alive": 0, "options": {"num_predict": 1}}
    try:
        requests.post(LLM_URL, json=payload, timeout=60)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Couldn't ask hailo-ollama to unload: {e}")


def _get_vlm_when_free(wait_s: float = VLM_NPU_WAIT_S):
    """_get_vlm(), retrying while hailo-ollama is still letting go of the NPU."""
    end = time.monotonic() + wait_s
    while True:
        try:
            return _get_vlm()
        except FileNotFoundError:
            raise
        except Exception as e:
            if time.monotonic() >= end:
                raise
            logger.info(f"NPU not free yet ({e}); retrying")
            time.sleep(2.0)


def _decode_image_to_frame(image_b64: str, target_shape, target_dtype=np.uint8):
    """Decode a base64 JPEG/PNG into a numpy array matching VLM input requirements."""
    import cv2

    raw = base64.b64decode(image_b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image from base64 data")

    # OpenCV loads BGR; VLM expects RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    h, w, c = target_shape
    if img.shape[0] != h or img.shape[1] != w:
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)

    return img.astype(target_dtype)

_WEATHER_KEYWORDS = (
    "weather", "forecast", "temperature", "raining", "snowing", "how cold", "how hot",
    "jacket", "coat", "umbrella", "cold outside", "hot outside",
)

# Keep at most this many messages (plus the system prompt) to avoid
# unbounded memory growth on memory-constrained devices like a Pi.
MAX_HISTORY_MESSAGES = 20

# hailo-ollama's qwen3:1.7b HEF has a fixed ~2k-token context and ignores
# num_ctx.  Past it the server silently drops the stream ("Response ended
# prematurely") — measured failing at ~6.2k chars of messages, fine at ~5.5k.
# Because a failed turn never appends a reply, an over-long saved history kept
# BMO stuck "thinking" forever, even across restarts.  Budget the prompt in
# characters (system prompt included) with room left for the 120-token reply.
MAX_CONTEXT_CHARS = 4500
# When the saved history outgrows the budget, cut it well below so the next few
# turns share an unchanged prefix — hailo-ollama only reuses its KV cache when
# earlier turns match exactly (first token ~0.8 s cached vs ~3-10 s re-prefilled).
TRIM_TARGET_CHARS = 2800


def _fit_context(messages: list, budget: int = MAX_CONTEXT_CHARS) -> list:
    """Drop the oldest non-system messages until the total content fits `budget`.

    The system prompt and the final message are always kept, and the retained
    conversation always starts on a user turn so roles keep alternating."""
    if not messages:
        return messages
    head = [messages[0]] if messages[0].get("role") == "system" else []
    body = list(messages[len(head):])

    def size(msgs):
        return sum(len(m.get("content") or "") for m in msgs)

    while len(body) > 1 and size(head + body) > budget:
        body.pop(0)
        while len(body) > 1 and body[0].get("role") != "user":
            body.pop(0)
    return head + body

_DISPLAY_IMAGE_KEYWORDS = [
    "show me a picture", "show me an image", "show me a photo",
    "show a picture", "show an image", "show a photo",
    "display a picture", "display an image", "display a photo",
    "picture of", "image of", "photo of",
    "generate an image", "generate a picture",
    "draw me", "draw a",
]

_MUSIC_KEYWORDS = [
    "play music", "play a song", "play me a song", "play some music",
    "sing a song", "sing me a song", "sing for me", "sing something",
    "play a tune", "play me a tune", "play some tunes",
    "can you sing", "will you sing", "do you sing",
    "play your music", "jam out", "dance for me",
    "sing for bmo", "bmo sing", "play me some music",
]

# Targeted leakage cleanup — only patterns that are unambiguous markers of the
# model echoing its own system prompt template, not natural user phrases.
# (Old approach truncated at "Rule 3:" or "Summarize:" anywhere in the reply,
# which broke legitimate replies about board-game rules and book summaries.)
_LEAK_PATTERNS = [
    # Anchored placeholders / template fragments — vanishingly rare in real speech
    re.compile(r'\[CUTE_WHIMSICAL_DESCRIPTION\]', re.IGNORECASE),
    re.compile(r'YOUR_PROMPT_HERE', re.IGNORECASE),
    re.compile(r'\[Summarize[^\]]*\]', re.IGNORECASE),
]
# Line-start labels we can safely strip (only when they begin a line)
_LINE_LABEL_RE = re.compile(
    r'^\s*(?:My thoughts|Reaction|Opinion|BMO\'s thoughts|BMO\'s reaction|'
    r"Summarize|Fact|RULES?|Info|Rule \d+):\s*",
    re.IGNORECASE | re.MULTILINE,
)
# Numbered list labels at line start — model often echoes "1. Start by saying..."
_NUMBERED_LINE_RE = re.compile(r'^\s*\d+[\.\)]\s+', re.MULTILINE)


def _build_display_image_action(user_text: str) -> str:
    """Extract the subject from user text and return a display_image JSON action."""
    # Strip common prefixes to get the image subject
    subject = user_text
    for prefix in ["show me a picture of", "show me an image of", "show me a photo of",
                    "show a picture of", "show an image of", "show a photo of",
                    "display a picture of", "display an image of", "display a photo of",
                    "generate an image of", "generate a picture of",
                    "draw me a", "draw me an", "draw me", "draw a", "draw an",
                    "picture of", "image of", "photo of"]:
        lower = subject.lower()
        if lower.startswith(prefix):
            subject = subject[len(prefix):].strip()
            break
    # Remove trailing punctuation
    subject = subject.rstrip("?.!")
    
    # Try to find a real image using DuckDuckGo
    real_url = search_images(subject)
    if real_url:
        return json.dumps({"action": "display_image", "image_url": real_url})
    
    # Fallback to a placeholder if search fails
    import random
    lock_id = random.randint(1, 1000000)
    return json.dumps({"action": "display_image", "image_url": f"https://loremflickr.com/512/512/{urllib.parse.quote(subject)}?lock={lock_id}"})


def strip_prompt_leakage(content: str) -> str:
    """Clean a model reply without aggressive truncation.

    Strategy:
    1. Strip <think>...</think> reasoning blocks (Qwen often emits these).
    2. Honour [BMO]…[/BMO] markers if present — return only what's between.
    3. Otherwise, just remove unambiguous template placeholders and line-start
       labels.  We deliberately do NOT truncate the reply at phrases like
       "Rule 1:" or "Summarize:" because users legitimately say those things.
    4. Strip any residual HTML tags and unescape HTML entities."""
    if not content:
        return ""

    # 1. Strip reasoning blocks
    if "<think>" in content.lower():
        if "</think>" in content.lower():
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
        else:
            # Unclosed <think> — model was cut off mid-reasoning.  Drop everything from there.
            content = re.split(r'<think>', content, flags=re.IGNORECASE)[0].strip()

    # 2. [BMO] markers — extract only the bracketed reply if present
    if "[/BMO]" in content:
        m = re.search(r'\[BMO\](.*?)\[/BMO\]', content, flags=re.DOTALL | re.IGNORECASE)
        if m:
            content = m.group(1).strip()
    elif "[BMO]" in content:
        # Half-tagged — strip everything before [BMO]
        content = content.split("[BMO]", 1)[1].strip()

    # 3. Line-start labels and numbered list prefixes
    content = _LINE_LABEL_RE.sub('', content)
    content = _NUMBERED_LINE_RE.sub('', content)

    # 4. Remove unambiguous placeholders (no truncation past them)
    for pat in _LEAK_PATTERNS:
        content = pat.sub('', content)

    # 5. Strip HTML tags and unescape entities echoed from search snippets.
    #    Two-pass: strip tags → unescape → strip decoded tags (handles &lt;b&gt; forms).
    import html as _html
    content = re.sub(r'<[^>]+>', ' ', content)
    content = _html.unescape(content)
    content = re.sub(r'<[^>]+>', ' ', content)

    # 6. Collapse runs of whitespace / leading-trailing whitespace
    content = re.sub(r'\s+', ' ', content)
    content = re.sub(r'\n{3,}', '\n\n', content).strip()
    return content


MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory.json")

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _partial_tag_tail(text: str, tag: str) -> int:
    """Length of the suffix of `text` that could be the start of `tag`.

    A streamed tag can arrive split across chunks ("<thi" + "nk>"), so the tail
    that might still grow into a tag must be held back rather than emitted."""
    lowered = text.lower()
    for k in range(min(len(tag) - 1, len(lowered)), 0, -1):
        if lowered.endswith(tag[:k]):
            return k
    return 0


class ThinkStripper:
    """Removes <think>…</think> spans from a *token stream*, statefully.

    strip_prompt_leakage() only sees one sentence-buffer at a time, so once the
    buffer holding the opening tag is flushed it has no way to know the reasoning
    is still running — every later reasoning sentence looks like ordinary prose
    and reaches the speaker.  This filter carries the open/closed state across
    chunks so reasoning never escapes.  Unclosed reasoning at end of stream is
    dropped (the model was cut off mid-thought)."""

    def __init__(self):
        self.in_think = False
        self._buf = ""

    def feed(self, chunk: str) -> str:
        """Consume a stream chunk, return only text outside reasoning blocks."""
        self._buf += chunk
        out = []
        while self._buf:
            if not self.in_think:
                i = self._buf.lower().find(_THINK_OPEN)
                if i == -1:
                    hold = _partial_tag_tail(self._buf, _THINK_OPEN)
                    emit_to = len(self._buf) - hold
                    out.append(self._buf[:emit_to])
                    self._buf = self._buf[emit_to:]
                    break
                out.append(self._buf[:i])
                self._buf = self._buf[i + len(_THINK_OPEN):]
                self.in_think = True
            else:
                j = self._buf.lower().find(_THINK_CLOSE)
                if j == -1:
                    hold = _partial_tag_tail(self._buf, _THINK_CLOSE)
                    self._buf = self._buf[len(self._buf) - hold:] if hold else ""
                    break
                self._buf = self._buf[j + len(_THINK_CLOSE):]
                self.in_think = False
        return "".join(out)

    def flush(self) -> str:
        """Return any held-back text at end of stream (nothing if still thinking)."""
        rest = "" if self.in_think else self._buf
        self._buf = ""
        return rest


def strip_think_blocks(content: str) -> str:
    """Remove complete and unclosed <think> spans from a finished reply.

    Used before persisting a turn to history: reasoning tokens must never be fed
    back into the next request, where they burn context and teach the model to
    keep reasoning out loud."""
    if not content or "<think>" not in content.lower():
        return content
    if "</think>" in content.lower():
        return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
    return re.split(r'<think>', content, flags=re.IGNORECASE)[0].strip()


# Control characters (incl. ANSI escape sequences from wttr.in / search snippets)
# break hailo-ollama's strict JSON prompt renderer.
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
_CTRL_RE = re.compile(r'[\x00-\x1f\x7f]')


def _sanitize_messages(messages: list) -> list:
    """Strip control characters from message content before sending to hailo-ollama.

    hailo-ollama's Qwen3 prompt renderer uses a strict JSON parser (nlohmann/json)
    that rejects control characters (RFC 7159 §7) in string values, even though
    they arrive correctly escaped in the HTTP body.  Newlines were the first
    offender found; ANSI escapes from weather/search snippets are the same class
    of bug.  Replace them with spaces so semantics survive but the renderer
    doesn't crash."""
    result = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            content = _ANSI_RE.sub(' ', content)
            content = _CTRL_RE.sub(' ', content)
        result.append({**m, "content": content})
    return result

# Public alias — other modules that build their own LLM payloads must sanitize too.
sanitize_messages = _sanitize_messages


def _quick_lead_in(user_text: str, intent: str) -> str:
    """Return a one-line BMO acknowledgement before a pre-routed action runs.

    Tries FAST_LLM_MODEL with a *tight* 600 ms ceiling — beyond that the user
    perceives lag and the static fallback is the better experience.  On Pi 5 +
    Hailo + qwen2.5-1.5B, a 30-token gen typically lands at 200–500 ms when
    the model is hot, so this is the right cut-off."""
    import random as _random
    fallbacks = {
        "image": [
            "Ooh, let BMO draw something for you!",
            "Time for some BMO art!",
            "BMO has a picture in mind!",
            "Let BMO show you something neat!",
        ],
        "photo": [
            "BMO is taking a look!",
            "Hold still, BMO is looking!",
            "Let BMO see what you've got!",
            "Ooh, BMO loves looking at things!",
        ],
        "music": [
            "Time to jam!",
            "Music time! BMO is so excited!",
            "Let BMO play you a tune!",
            "Oh yeah, BMO loves this song!",
        ],
    }
    try:
        payload = {
            "model": FAST_LLM_MODEL,
            "messages": _sanitize_messages([
                {"role": "system", "content":
                 "You are BMO. Reply with ONE short, cheerful sentence (max 12 words) "
                 "acknowledging what the user asked for. No markdown, no quotes."},
                {"role": "user", "content": user_text},
            ]),
            "stream": False,
            "keep_alive": LLM_KEEP_ALIVE,
            "options": {"temperature": 0.8, "num_predict": 30},
        }
        r = requests.post(LLM_URL, json=payload, timeout=0.6)
        if r.status_code == 200:
            txt = r.json().get("message", {}).get("content", "").strip().strip('"').strip("'")
            txt = re.sub(r"\s+", " ", txt)
            if 3 <= len(txt) <= 100:
                return txt
    except Exception:
        pass
    options = fallbacks.get(intent, [])
    return _random.choice(options) if options else ""


def extract_json_object(text: str):
    r"""Find the first balanced JSON object in `text` and return (parsed, span)
    or (None, None). Handles nested objects, escaped quotes, and unbalanced
    brace counts that broke the old `re.search(r'\{.*?\}')` approach."""
    if not text or '{' not in text:
        return None, None
    n = len(text)
    for start in range(n):
        if text[start] != '{':
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, n):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            return json.loads(candidate), (start, i + 1)
                        except json.JSONDecodeError:
                            break  # try next '{' opener
    return None, None


def _with_current_context(messages):
    """Return a shallow copy of `messages` with the current time/date prepended
    to the LAST user message. Keeps the system prompt byte-stable so the LLM's
    prefix KV-cache can be reused across turns (saves 80–150 ms / turn)."""
    if not messages:
        return messages
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            msg = dict(out[i])
            msg["content"] = f"[{get_current_context()}] {msg.get('content', '')}"
            out[i] = msg
            break
    return out


class Brain:
    def __init__(self, persist: bool = True):
        """persist=False keeps this Brain off memory.json entirely.

        web_app builds a fresh Brain per request from the browser-supplied
        history.  With persistence on, each request force-wrote that history to
        memory.json, clobbering the long-lived desktop agent's memory — two
        processes racing last-writer-wins over one file."""
        self.persist = persist
        # Set by the agent: () -> True while a morning briefing is ready and
        # unplayed.  None (web_app, cli) skips briefing routing entirely.
        self.briefing_ready = None
        # Set by the agent: the shared core.reminders.ReminderRegistry, so
        # "what reminders do I have?" / "cancel the pasta timer" work.
        self.reminders = None
        self.history = []
        if persist:
            self.load_history()
        # System prompt is now static (no embedded time/date).  Ensure it's
        # present and matches the current source — but never mutate it on
        # subsequent turns, so the model's KV-cache prefix remains valid.
        if not self.history or self.history[0].get("role") != "system":
            self.history.insert(0, {"role": "system", "content": get_system_prompt()})
        elif self.history[0]["content"] != get_system_prompt():
            self.history[0]["content"] = get_system_prompt()

        # Memory persistence throttling — limit SD-card writes for 24/7 uptime.
        # Force a flush at most once every 60 s; pending changes flush on exit.
        self._save_min_interval_s = 60.0
        self._last_save_at = 0.0
        self._save_dirty = False
        if persist:
            import atexit as _atexit
            _atexit.register(self._save_on_exit)

    def warm_up(self):
        """Load the model onto the NPU (and pin it there) before the first question.

        hailo-ollama loads lazily, so without this the first question after a
        boot or server restart waits 7-36 s for the model on top of generation."""
        payload = {
            "model": FAST_LLM_MODEL,
            "messages": _sanitize_messages([self.history[0], {"role": "user", "content": "Hi"}]),
            "stream": False,
            "keep_alive": LLM_KEEP_ALIVE,
            "options": {"num_predict": 1},
        }
        try:
            requests.post(LLM_URL, json=payload, timeout=120)
            logger.info("LLM warmed up.")
        except requests.exceptions.RequestException as e:
            logger.warning(f"LLM warm-up failed: {e}")

    def load_history(self):
        """Load chat history from memory.json if it exists."""
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r') as f:
                    loaded = json.load(f)
                # Valid JSON that isn't a message list would crash __init__ later.
                if not isinstance(loaded, list) or not all(isinstance(m, dict) for m in loaded):
                    raise ValueError("memory.json is not a list of messages")
                self.history = loaded
                logger.info(f"Loaded {len(self.history)} messages from memory.")
            except Exception as e:
                logger.error(f"Failed to load memory: {e}")
                self.history = []

    def save_history(self, force: bool = False):
        """Persist chat history to disk.  Throttled to once per ~60 s by
        default to limit SD-card wear; call with force=True for hard flushes."""
        if not getattr(self, "persist", True):
            return
        import time as _t
        self._save_dirty = True
        now = _t.time()
        if not force and (now - self._last_save_at) < self._save_min_interval_s:
            return
        try:
            # Atomic replace: a power cut mid-write must not truncate memory.json.
            tmp = MEMORY_FILE + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(self.history, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, MEMORY_FILE)
            self._last_save_at = now
            self._save_dirty = False
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def _save_on_exit(self):
        """atexit hook — flush any pending throttled writes before shutdown."""
        if getattr(self, "_save_dirty", False):
            self.save_history(force=True)

    def _trim_history(self):
        """Keep the system prompt + the most recent MAX_HISTORY_MESSAGES messages."""
        # history[0] is always the system prompt
        non_system = self.history[1:]
        if len(non_system) > MAX_HISTORY_MESSAGES:
            self.history = [self.history[0]] + non_system[-MAX_HISTORY_MESSAGES:]
        if sum(len(m.get("content") or "") for m in self.history) > MAX_CONTEXT_CHARS:
            self.history = _fit_context(self.history, budget=TRIM_TARGET_CHARS)
        self.save_history()

    def _briefing_action(self, user_text: str):
        """'{"action": "play_briefing"}' if this asks for the briefing, else None.

        "Good morning" only plays a briefing that's ready and unplayed (else
        BMO chats as usual); "morning briefing" and friends play any time.
        No lead-in: the briefing opens with its own greeting."""
        if self.briefing_ready is None:
            return None
        intent = briefing_intents.match(user_text)
        if intent == briefing_intents.BRIEFING or (
                intent == briefing_intents.GOOD_MORNING and self.briefing_ready()):
            print(f"[LLM] Briefing MATCHED ({intent}): '{user_text[:60]}'")
            return '{"action": "play_briefing"}'
        return None

    @staticmethod
    def _reminder_reply(user_text: str):
        """(spoken, action) for "remind me tomorrow at 9 to ..." or None."""
        r = parse_reminder_request(user_text)
        if r is None:
            return None
        when = describe_when(r["due"])
        if r["message"] == "Alarm!":
            spoken = f"Okay friend! I set an alarm for {when}"
        elif r["message"] == "Reminder!":
            spoken = f"Okay friend! I'll remind you {when}"
        else:
            spoken = f"Okay friend! I'll remind you {when} to {r['message'].rstrip('!.')[:1].lower()}" \
                     f"{r['message'].rstrip('!.')[1:]}"
        if not spoken.endswith("."):
            spoken += "."
        return spoken, json.dumps({"action": "set_reminder", **r})

    def _reminder_query_reply(self, user_text: str):
        """Spoken answer to "what reminders do I have?", "cancel the pasta
        timer", "how long left?"; None if it isn't one (or no registry)."""
        if self.reminders is None:
            return None
        q = parse_reminder_query(user_text)
        if q is None:
            return None
        print(f"[LLM] Reminder query MATCHED: {q}")
        items = self.reminders.pending()
        if q["action"] == "list":
            if not items:
                return "You don't have any timers or reminders right now."
            said = [_describe_item(r) for r in items[:4]]
            more = f", and {len(items) - 4} more" if len(items) > 4 else ""
            n = len(items)
            return f"You have {n} {'thing' if n == 1 else 'things'} set: " + "; ".join(said) + more + "."
        hits = match_reminders(items, q["target"])
        if q["action"] == "cancel":
            if q.get("all"):
                for r in hits:
                    self.reminders.remove(r["id"])
                return "Okay! Everything's cancelled." if hits else "There's nothing to cancel, friend."
            if not hits:
                return "Hmm, BMO couldn't find that one." if items else "There's nothing to cancel, friend."
            if len(hits) > 1:
                return "Which one? You have " + _or_list([_label(r) for r in hits]) + "."
            self.reminders.remove(hits[0]["id"])
            return f"Okay, I cancelled {_label(hits[0])}."
        # time left
        if not hits:
            return "Hmm, BMO couldn't find that one." if items else "You don't have any timers running."
        if len(hits) > 1 and q["target"] is None:
            timers = [r for r in hits if r.get("kind", "timer") == "timer"]
            hits = timers if len(timers) == 1 else hits
        if len(hits) > 1:
            return "; ".join(_describe_item(r) for r in hits[:4]) + "."
        return _describe_item(hits[0], lead=True) + "."

    def think(self, user_text: str) -> str:
        """
        Send text to local LLM (Hailo/Ollama) and get response.
        """
        # System prompt is static; current time/date is injected into the
        # final user message at request-build time (see _with_current_context).
        self.history.append({"role": "user", "content": user_text})


        lower_text = user_text.lower()

        # Pre-LLM briefing check first: it only matches whole-utterance
        # requests, and "show me my briefing" mustn't reach the image check.
        briefing = self._briefing_action(user_text)
        if briefing:
            self.history.append({"role": "assistant", "content": briefing})
            return briefing

        # Pre-LLM camera check — same logic as stream_think
        camera_keywords = [
            "take a photo", "take a picture", "take photo", "take picture",
            "look at", "what do you see", "what can you see", "use your camera",
            "photograph", "snap a photo",
            # Common natural phrasings the prior list missed:
            "what is this", "what's this", "what am i holding", "do you see",
            "show me what you see", "can you see this", "tell me what you see",
            "what's that", "what is that",
        ]
        if any(kw in lower_text for kw in camera_keywords):
            action = '{"action": "take_photo"}'
            lead_in = _quick_lead_in(user_text, "photo")
            combined = (lead_in + " " + action).strip() if lead_in else action
            self.history.append({"role": "assistant", "content": combined})
            return combined

        # Pre-LLM display_image check — handle image generation requests
        # directly instead of relying on the small model to emit correct JSON
        if any(kw in lower_text for kw in _DISPLAY_IMAGE_KEYWORDS):
            action = _build_display_image_action(user_text)
            matched_kw = next(kw for kw in _DISPLAY_IMAGE_KEYWORDS if kw in lower_text)
            print(f"[LLM] Image keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            print(f"[LLM] Emitting display_image action: {action[:80]}")
            lead_in = _quick_lead_in(user_text, "image")
            combined = (lead_in + " " + action).strip() if lead_in else action
            self.history.append({"role": "assistant", "content": combined})
            return combined

        # Pre-LLM music check — emit play_music directly rather than
        # relying on the small model to emit correct JSON
        if any(kw in lower_text for kw in _MUSIC_KEYWORDS):
            action = '{"action": "play_music"}'
            matched_kw = next(kw for kw in _MUSIC_KEYWORDS if kw in lower_text)
            print(f"[LLM] Music keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            print(f"[LLM] Emitting play_music action")
            lead_in = _quick_lead_in(user_text, "music")
            combined = (lead_in + " " + action).strip() if lead_in else action
            self.history.append({"role": "assistant", "content": combined})
            return combined

        # Pre-LLM timer check — parsed in Python, never left to the model
        # (see core/timers.py).  Mirrors stream_think.
        timer = parse_timer_request(user_text)
        if timer is not None:
            action = json.dumps({"action": "set_timer", **timer})
            spoken = (f"Okay friend! I set a {timer['name']} timer for {describe_duration(timer['minutes'])}."
                      if timer.get("name") else
                      f"Okay friend! I set a timer for {describe_duration(timer['minutes'])}.")
            print(f"[LLM] Timer MATCHED: {timer}")
            combined = (spoken + " " + action).strip()
            self.history.append({"role": "assistant", "content": combined})
            return combined

        # Reminders for a clock time or a day ("tomorrow at 9", "on Friday").
        reminder = self._reminder_reply(user_text)
        if reminder is not None:
            print(f"[LLM] Reminder MATCHED: {reminder[1]}")
            combined = " ".join(reminder)
            self.history.append({"role": "assistant", "content": combined})
            return combined

        # Questions about timers/reminders ("what's set?", "cancel the pasta timer").
        answer = self._reminder_query_reply(user_text)
        if answer is not None:
            self.history.append({"role": "assistant", "content": answer})
            return answer

        print(f"[LLM] No pre-LLM action matched for: '{lower_text[:60]}'")

        # Pre-LLM web search — same logic as stream_think
        realtime_keywords = [
            "weather", "forecast", "temperature", "tonight", "tomorrow",
            "news", "latest", "right now", "score", "stocks", "bitcoin",
            "crypto", "price of", "happening", "recently", "live",
        ]
        question_markers = [
            "what", "who", "when", "where", "find", "search", "tell me",
            "look up", "check", "is there", "did", "?", "is it", "will it", "how",
        ]
        # General pre-LLM web search stays disabled for latency; weather is the
        # exception — wttr.in answers in <1 s and without it BMO invents the weather.
        has_realtime_kw = any(kw in lower_text for kw in _WEATHER_KEYWORDS)
        has_question = any(m in lower_text for m in question_markers)
        search_injected = False
        if has_realtime_kw and has_question:
            try:
                search_result = get_weather(user_text)  # only weather is routed here
                if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR") and len(search_result) > 50:
                    # Strip the verbose "SEARCH RESULTS for '...':" header from search.py
                    clean_result = re.sub(r"^SEARCH RESULTS for '.*?':\n?", "", search_result).strip()
                    # Inject as a tight [LIVE DATA] block — clearer than the previous format
                    self.history[-1]["content"] = (
                        f"[LIVE DATA: {clean_result}] "
                        f"Using only the above live data, answer in one or two sentences as BMO: {user_text}"
                    )
                    search_injected = True
            except Exception as e:
                logger.warning(f"Pre-LLM web search failed: {e}")

        # Simple heuristic to route to a faster model for simple chat
        complex_keywords = ["explain", "story", "how", "why", "code", "write", "create", "analyze", "compare", "difference", "history", "long"]
        words = user_text.lower().split()
        
        chosen_model = FAST_LLM_MODEL
        if len(words) > 15 or any(kw in words for kw in complex_keywords):
            chosen_model = LLM_MODEL

        payload = {
            "model": chosen_model,
            "messages": _sanitize_messages(_fit_context(_with_current_context(self.history))),
            "stream": False,
            "keep_alive": LLM_KEEP_ALIVE,
            "options": {
                "temperature": 0.7,
                # ~4.5 tok/s on the H10H, so num_predict is a latency budget, not
                # just a length cap: 1024 meant up to 3.5 min of generation and ~80 s
                # of rambling audio.  BMO speaks 1-3 sentences (~40-60 tokens); 120
                # leaves headroom while bounding a runaway turn at ~27 s.
                "num_predict": 120,
                "num_ctx": 4096,
            }
        }

        assistant_appended = False
        try:
            logger.info(f"Sending request to LLM ({chosen_model}): {LLM_URL}")
            response = requests.post(LLM_URL, json=payload, timeout=180)

            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")

                # Check if the LLM outputted a JSON action (like search_web)
                try:
                    # Replace smart quotes before parsing
                    clean_content = content.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
                    action_data, _span = extract_json_object(clean_content)
                    if action_data is not None:

                        if action_data.get("action") == "take_photo":
                            logger.info("LLM requested to take a photo.")
                            # Return the JSON string directly so the caller can handle the camera
                            photo_action = json.dumps({"action": "take_photo"})
                            self.history.append({"role": "assistant", "content": photo_action})
                            assistant_appended = True
                            return photo_action
                            
                        elif action_data.get("action") == "search_web":
                            query = action_data.get("query", "")
                            logger.info(f"LLM requested web search for: {query}")
                            
                            # Perform the search
                            search_result = search_web(query)
                            
                            # Feed the result back to the LLM to summarize
                            summary_prompt = [
                                {"role": "system", "content": "Summarize this search result in one short, conversational sentence as BMO. Do not use markdown."},
                                {"role": "user", "content": f"RESULT: {search_result} User Question: {user_text}"}
                            ]

                            summary_payload = {
                                "model": FAST_LLM_MODEL,
                                "messages": _sanitize_messages(summary_prompt),
                                "stream": False,
                                "keep_alive": LLM_KEEP_ALIVE,
                            }

                            summary_response = requests.post(LLM_URL, json=summary_payload, timeout=180)
                            if summary_response.status_code == 200:
                                content = summary_response.json().get("message", {}).get("content", "")
                            else:
                                content = "I tried to search the web, but my brain got confused reading the results."
                except json.JSONDecodeError:
                    pass # Not valid JSON, just treat as normal text
                
                # Check for pronunciation learning tag
                pronounce_match = re.search(r'!PRONOUNCE:\s*([a-zA-Z0-9_-]+)\s*=\s*([a-zA-Z0-9_-]+)', content, re.IGNORECASE)
                if pronounce_match:
                    word = pronounce_match.group(1).strip()
                    phonetic = pronounce_match.group(2).strip()
                    logger.info(f"Learned new pronunciation from LLM: {word} -> {phonetic}")
                    add_pronunciation(word, phonetic)
                    # Remove the tag from the spoken content
                    content = re.sub(r'!PRONOUNCE:.*', '', content, flags=re.IGNORECASE).strip()

                # Strip any system prompt leakage from the response
                content = strip_prompt_leakage(content)

                # Ensure BMO is spelled correctly in text responses
                content = re.sub(r'\bBeemo\b', 'BMO', content, flags=re.IGNORECASE)

                # Fallback if filtering left nothing useful
                if not content.strip():
                    content = "BMO is here! How can I help?"

                self.history.append({"role": "assistant", "content": content})
                assistant_appended = True

                # Clean injected search context from history so it doesn't
                # accumulate and confuse the model on future turns.
                if search_injected:
                    for msg in reversed(self.history):
                        if msg.get("role") == "user" and msg.get("content", "").startswith("[LIVE DATA:"):
                            msg["content"] = user_text
                            break

                self._trim_history()
                return content

            else:
                logger.error(f"LLM Error: {response.status_code} - {response.text}")
                return f"Error: {response.status_code}"

        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error to {LLM_URL}: {e}")
            return "Could not connect to my brain. Is the Hailo server running?"
        except Exception as e:
            logger.error(f"Brain Exception: {e}")
            return "I'm having trouble thinking right now."
        finally:
            # Preserve user/assistant alternation: if every code path above
            # bailed without recording an assistant turn (HTTP error, network
            # failure, take_photo path that bailed without append), drop the
            # unmatched user message so the next turn doesn't start with two
            # user messages in a row.
            if not assistant_appended:
                if self.history and self.history[-1].get("role") == "user":
                    self.history.pop()

    def get_history(self):
        return self.history

    def stream_think(self, user_text: str):
        """
        Send text to local LLM and yield full sentences as they are generated.
        Useful for TTS chunking (speaking while generating).
        """
        # System prompt is static; current time/date is injected per-turn into
        # the user message via _with_current_context() before the request.
        self.history.append({"role": "user", "content": user_text})


        lower_text = user_text.lower()

        # Pre-LLM briefing check first (see think()).
        briefing = self._briefing_action(user_text)
        if briefing:
            self.history.append({"role": "assistant", "content": briefing})
            yield briefing
            return

        # Pre-LLM camera check: if user asks to take a photo / look at something,
        # emit the action JSON directly without calling the LLM.
        # This is more reliable than hoping the small model emits the right JSON.
        camera_keywords = [
            "take a photo", "take a picture", "take photo", "take picture",
            "look at", "what do you see", "what can you see", "use your camera",
            "photograph", "snap a photo",
            # Common natural phrasings the prior list missed:
            "what is this", "what's this", "what am i holding", "do you see",
            "show me what you see", "can you see this", "tell me what you see",
            "what's that", "what is that",
        ]
        if any(kw in lower_text for kw in camera_keywords):
            action = '{"action": "take_photo"}'
            lead_in = _quick_lead_in(user_text, "photo")
            if lead_in:
                yield lead_in
            self.history.append({"role": "assistant", "content": (lead_in + " " + action).strip()})
            yield action
            return

        # Pre-LLM display_image check
        if any(kw in lower_text for kw in _DISPLAY_IMAGE_KEYWORDS):
            action = _build_display_image_action(user_text)
            matched_kw = next(kw for kw in _DISPLAY_IMAGE_KEYWORDS if kw in lower_text)
            print(f"[LLM-STREAM] Image keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            lead_in = _quick_lead_in(user_text, "image")
            if lead_in:
                yield lead_in
            self.history.append({"role": "assistant", "content": (lead_in + " " + action).strip()})
            yield action
            return

        # Pre-LLM music check — emit play_music directly
        if any(kw in lower_text for kw in _MUSIC_KEYWORDS):
            action = '{"action": "play_music"}'
            matched_kw = next(kw for kw in _MUSIC_KEYWORDS if kw in lower_text)
            print(f"[LLM-STREAM] Music keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            lead_in = _quick_lead_in(user_text, "music")
            if lead_in:
                yield lead_in
            self.history.append({"role": "assistant", "content": (lead_in + " " + action).strip()})
            yield action
            return

        # Pre-LLM timer check — parsed in Python, never left to the model.
        # qwen3:1.7b mis-parses units ("30 seconds" → 30 minutes) and copies the
        # example reminder text verbatim, so timers must not be probabilistic.
        timer = parse_timer_request(user_text)
        if timer is not None:
            action = json.dumps({"action": "set_timer", **timer})
            spoken = (f"Okay friend! I set a {timer['name']} timer for {describe_duration(timer['minutes'])}."
                      if timer.get("name") else
                      f"Okay friend! I set a timer for {describe_duration(timer['minutes'])}.")
            print(f"[LLM-STREAM] Timer MATCHED: {timer}")
            yield spoken
            self.history.append({"role": "assistant", "content": (spoken + " " + action).strip()})
            yield action
            return

        # Reminders for a clock time or a day ("tomorrow at 9", "on Friday").
        reminder = self._reminder_reply(user_text)
        if reminder is not None:
            print(f"[LLM-STREAM] Reminder MATCHED: {reminder[1]}")
            yield reminder[0]
            self.history.append({"role": "assistant", "content": " ".join(reminder)})
            yield reminder[1]
            return

        # Questions about timers/reminders ("what's set?", "cancel the pasta timer").
        answer = self._reminder_query_reply(user_text)
        if answer is not None:
            self.history.append({"role": "assistant", "content": answer})
            yield answer
            return

        print(f"[LLM-STREAM] No pre-LLM action matched for: '{lower_text[:60]}'")

        # Pre-LLM keyword check: if the question likely needs real-time info,
        # do the web search now rather than relying on the model to emit JSON.
        # Require at least one realtime keyword AND the text to look like a question
        # (contains 'what', 'who', 'when', 'find', 'search', '?', etc.) to avoid
        # false triggers on casual phrases like 'how are you doing today'.
        realtime_keywords = [
            "weather", "forecast", "temperature", "tonight", "tomorrow",
            "news", "latest", "right now", "score", "stocks", "bitcoin",
            "crypto", "price of", "happening", "recently", "live",
        ]
        question_markers = [
            "what", "who", "when", "where", "find", "search", "tell me",
            "look up", "check", "is there", "did", "?", "is it", "will it", "how",
        ]
        # General pre-LLM web search stays disabled for latency; weather is the
        # exception — wttr.in answers in <1 s and without it BMO invents the weather.
        has_realtime_kw = any(kw in lower_text for kw in _WEATHER_KEYWORDS)
        has_question = any(m in lower_text for m in question_markers)
        needs_search = has_realtime_kw and has_question
        search_injected = False
        if needs_search:
            try:
                search_result = get_weather(user_text)  # only weather is routed here
                # Only inject if we got a real result (not empty/error sentinel)
                if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR") and len(search_result) > 50:
                    # Strip verbose "SEARCH RESULTS for '...':" prefix from search.py
                    clean_result = re.sub(r"^SEARCH RESULTS for '.*?':\n?", "", search_result).strip()
                    self.history[-1]["content"] = (
                        f"[LIVE DATA: {clean_result}] "
                        f"Using only the above live data, answer in one or two sentences as BMO: {user_text}"
                    )
                    search_injected = True
            except Exception as e:
                logger.warning(f"Pre-LLM web search failed: {e}")

        # Simple heuristic to route to a faster model for simple chat
        complex_keywords = ["explain", "story", "how", "why", "code", "write", "create", "analyze", "compare", "difference", "history", "long"]
        words = user_text.lower().split()
        
        chosen_model = FAST_LLM_MODEL
        if len(words) > 15 or any(kw in words for kw in complex_keywords):
            chosen_model = LLM_MODEL



        messages = _fit_context(_with_current_context(self.history))
        # Keep the time-stamped user turn in history so next turn's prefix is
        # byte-identical to what the server saw and its KV cache is reused.
        if self.history and self.history[-1].get("role") == "user":
            self.history[-1] = messages[-1]

        payload = {
            "model": chosen_model,
            "messages": _sanitize_messages(messages),
            "stream": True,
            "keep_alive": LLM_KEEP_ALIVE,
            "options": {
                "temperature": 0.7,
                # ~4.5 tok/s on the H10H, so num_predict is a latency budget, not
                # just a length cap: 1024 meant up to 3.5 min of generation and ~80 s
                # of rambling audio.  BMO speaks 1-3 sentences (~40-60 tokens); 120
                # leaves headroom while bounding a runaway turn at ~27 s.
                "num_predict": 120,
                "num_ctx": 4096,      # Ensure context window is large enough
            }
        }

        full_content = ""
        raw_content = ""  # exactly as generated, for history / KV-cache reuse
        buffer = ""
        assistant_appended = False
        thinker = ThinkStripper()

        try:
            logger.info(f"Stream request to LLM ({chosen_model}): {LLM_URL}")
            with requests.post(LLM_URL, json=payload, stream=True, timeout=180) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("message", {}).get("content", "")
                                if not chunk:
                                    continue
                                raw_content += chunk

                                # Replace smart quotes
                                chunk = chunk.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

                                full_content += chunk
                                # Reasoning must never reach the speaker; the filter
                                # carries <think> state across chunk boundaries.
                                chunk = thinker.feed(chunk)
                                if not chunk:
                                    continue
                                buffer += chunk

                                # If buffer ends with strong punctuation or newline, yield it.
                                # Skip flush for: (a) digit-period-digit ("$4.99"),
                                # (b) common abbreviations (Dr., Mr., Mrs., e.g., i.e.),
                                # (c) buffers shorter than 10 chars (avoids "It's." flushing as a sentence)
                                ends_punct = any(buffer.endswith(p) for p in ['.', '!', '?', '\n'])
                                mid_decimal = (
                                    len(buffer) >= 2 and buffer.endswith('.')
                                    and buffer[-2].isdigit()
                                )
                                # Treat short buffers as not ready to flush
                                trimmed = buffer.strip()
                                # ...except exclamations/questions: speaking "Oh my!" the
                                # moment it arrives gives BMO a voice ~2 s sooner at 5 tok/s.
                                too_short = len(trimmed) < (4 if trimmed.endswith(('!', '?')) else 10)
                                # Common abbrev. tail check (case-insensitive)
                                abbrev_tail = any(
                                    trimmed.lower().endswith(a) for a in (
                                        ' dr.', ' mr.', ' mrs.', ' ms.', ' jr.', ' sr.',
                                        ' st.', ' vs.', ' etc.', ' e.g.', ' i.e.',
                                    )
                                )
                                # Never flush mid-JSON: a set_timer message ending in
                                # "." would split the action object across yields and
                                # the action would be silently dropped downstream.
                                unbalanced = buffer.count('{') > buffer.count('}')
                                ready = ends_punct and not mid_decimal and not too_short and not abbrev_tail
                                if (ready and not unbalanced) or ("\n\n" in buffer and not unbalanced):
                                    # Strip system prompt leakage
                                    cleaned = strip_prompt_leakage(buffer)
                                    # Ensure BMO spelling before yielding
                                    out_chunk = re.sub(r'\bBeemo\b', 'BMO', cleaned, flags=re.IGNORECASE)
                                    if out_chunk.strip():
                                        yield out_chunk
                                    buffer = ""
                                    
                            except json.JSONDecodeError:
                                pass
                                
                    # Yield any remaining buffer (plus text held back by the filter)
                    buffer += thinker.flush()
                    if buffer.strip():
                        cleaned = strip_prompt_leakage(buffer)
                        out_chunk = re.sub(r'\bBeemo\b', 'BMO', cleaned, flags=re.IGNORECASE)
                        if out_chunk.strip():
                            yield out_chunk

                    # Handle json actions at the very end if applicable
                    final_action, _ = extract_json_object(full_content)
                    if final_action is not None and "action" in final_action:
                        # For advanced tool use we won't yield the json action to TTS
                        pass
                    
                    self.history.append({"role": "assistant", "content": strip_think_blocks(raw_content) or raw_content})
                    assistant_appended = True
                    self.save_history()

                    # Clean injected search context from history so it doesn't
                    # accumulate and confuse the model on future turns.
                    if search_injected:
                        for msg in reversed(self.history):
                            if msg.get("role") == "user" and "[LIVE DATA:" in msg.get("content", ""):
                                msg["content"] = user_text
                                break

                    self._trim_history()

                else:
                    logger.error(f"LLM Stream Error: {response.status_code} - {response.text}")
                    yield "I'm having trouble thinking."
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error to {LLM_URL}: {e}")
            yield "Could not connect to my brain."
        except Exception as e:
            logger.error(f"Brain Exception: {e}")
            yield "I'm having trouble right now."
        finally:
            # Stream may have failed mid-generation. We MUST keep the
            # user-then-assistant alternation in history or the next turn will
            # confuse the model.  If we never appended an assistant turn,
            # either record what we got OR pop the dangling user message.
            if not assistant_appended:
                if full_content.strip():
                    salvaged = strip_think_blocks(full_content) or full_content
                    self.history.append({"role": "assistant", "content": salvaged})
                else:
                    # Drop the unmatched user message we appended at function start
                    if self.history and self.history[-1].get("role") == "user":
                        self.history.pop()
                self.save_history()
                self._trim_history()

    def set_history(self, new_history):
        # Ensure system prompt is always present and up to date
        if not new_history or new_history[0].get("role") != "system":
            new_history.insert(0, {"role": "system", "content": get_system_prompt()})
        else:
            new_history[0]["content"] = get_system_prompt()
        self.history = new_history
        # Bypass throttle on a wholesale history replacement so the change
        # hits disk immediately even if it falls inside the 60 s window.
        self.save_history(force=True)

    def analyze_image(self, image_base64: str, user_text: str) -> str:
        """
        Analyse an image using the Hailo VLM (Qwen2-VL-2B) running directly
        on the NPU via the HailoRT Python API.  Falls back to a polite error
        message if the HEF isn't available or the hardware can't be reached.
        """
        # Strip data URI prefix if present (browser sends "data:image/jpeg;base64,...")
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]

        # We don't append the image to the main history to save context window,
        # but we do append the user's question and the assistant's answer.
        self.history.append({"role": "user", "content": user_text})
        assistant_appended = False

        freed = False
        try:
            if _vlm_instance is None:
                _free_npu_for_vlm()
                freed = True
            vlm, frame_shape, frame_dtype = _get_vlm_when_free()

            # Decode the base64 image into a numpy frame the VLM expects
            frame = _decode_image_to_frame(image_base64, frame_shape, frame_dtype)

            # Build the structured prompt expected by the Qwen2-VL model
            prompt = [
                {"role": "system", "content": [
                    {"type": "text", "text": "You are BMO, a helpful robot assistant. Describe what you see concisely and conversationally in English."}
                ]},
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": user_text or "What do you see in this image?"}
                ]}
            ]

            logger.info("Running VLM inference on Hailo NPU ...")
            vlm.clear_context()

            # Run generate_all with a hard timeout so a hung/throttled NPU
            # doesn't freeze the agent indefinitely.
            result = {"content": None, "exc": None}

            def _run():
                try:
                    result["content"] = vlm.generate_all(
                        prompt=prompt,
                        frames=[frame],
                        max_generated_tokens=150,
                        temperature=0.4,
                    )
                except Exception as e:
                    result["exc"] = e

            global _vlm_thread
            t = threading.Thread(target=_run, daemon=True)
            _vlm_thread = t
            t.start()
            t.join(timeout=30)
            if t.is_alive():
                logger.error("VLM inference timed out after 30s.")
                return "My eyes are taking too long to focus right now."
            if result["exc"] is not None:
                raise result["exc"]
            content = result["content"] or ""

            # Clean up any smart quotes, stop tokens, or stray formatting
            content = content.replace('\u201c', '"').replace('\u201d', '"')
            content = content.replace('\u2018', "'").replace('\u2019', "'")
            for tok in ("<|im_end|>", "<|endoftext|>", "<|im_start|>"):
                content = content.replace(tok, "")
            content = content.strip()

            logger.info(f"VLM response ({len(content)} chars): {content[:120]}...")

            self.history.append({"role": "assistant", "content": content})
            assistant_appended = True
            return content

        except FileNotFoundError as e:
            logger.warning(f"VLM HEF not found: {e}")
            return "BMO's vision model isn't installed yet. Run setup.sh to download it!"
        except Exception as e:
            logger.error(f"VLM Exception: {e}", exc_info=True)
            return "I tried to look, but my eyes aren't working right now."
        finally:
            # Hand the NPU back to hailo-ollama, but never while an inference
            # thread is still touching the device — releasing under it segfaults.
            if _vlm_inflight():
                logger.error("VLM inference still running; leaving /dev/hailo0 held. "
                             "Restart BMO to recover the NPU for the LLM.")
            else:
                _release_vlm()
                if freed:
                    # Put the LLM back (~35 s) without making the user wait for it.
                    threading.Thread(target=self.warm_up, daemon=True).start()

            # Preserve user/assistant alternation if any error path bailed.
            if not assistant_appended:
                if self.history and self.history[-1].get("role") == "user":
                    self.history.pop()
