"""Drive the face-rig code paths in agent_hailo.py without a Pi, Tk or audio.

Stubs Tk, audio and model imports, builds a BotGUI without its __init__
threads, and runs the real methods on a fake clock:
warm-up -> greeting clip -> LLM mood + Piper stream -> PNG hand-off -> error fallback.

    python tests/face_rig_harness.py          # from the repo root
"""

import io
import os
import sys
import threading
import types
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
GREETING_A = os.path.join(REPO, "sounds", "greeting_sounds", "greeting_10.wav")
GREETING_B = os.path.join(REPO, "sounds", "greeting_sounds", "greeting_05.wav")


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class _Any:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Any()

    def __getattr__(self, _):
        return _Any()


class FakePhoto:
    n = 0

    def __init__(self, img=None, **k):
        FakePhoto.n += 1
        self.name = f"pyimage{FakePhoto.n}"
        self.pastes = 0

    def paste(self, im):
        self.pastes += 1

    def __str__(self):
        return self.name


# Stub everything that needs hardware, a display or the LLM stack.
stub("tkinter", Tk=_Any, Label=_Any, Canvas=_Any, S="s")
stub("tkinter.ttk")
sys.modules["tkinter"].ttk = sys.modules["tkinter.ttk"]
import PIL  # noqa: E402

stub("PIL.ImageTk", PhotoImage=FakePhoto)
PIL.ImageTk = sys.modules["PIL.ImageTk"]
for name in ("sounddevice", "scipy", "scipy.signal", "openwakeword", "core"):
    stub(name)
stub("openwakeword.model", Model=_Any)
stub("core.llm", Brain=_Any, extract_json_object=lambda s: (None, None),
     strip_prompt_leakage=lambda s: s, sanitize_messages=lambda m: m)
stub("core.tts", play_audio_on_hardware=_Any(), clean_text_for_speech=lambda t: t)
stub("core.stt", transcribe_audio=_Any())
stub("core.endpoint", EndpointDetector=_Any)
stub("core.config", LLM_KEEP_ALIVE=-1, MIC_DEVICE_INDEX=0, MIC_SAMPLE_RATE=48000, WAKE_WORD_MODEL="", WAKE_WORD_THRESHOLD=0.5,
     ALSA_DEVICE="default", VOLUME=1.0, PIPER_CMD="piper", PIPER_MODEL="bmo.onnx")

path = os.path.join(REPO, "agent_hailo.py")
mod = types.ModuleType("agent_hailo")
mod.__file__ = path
with open(path, encoding="utf-8") as f:
    exec(compile(f.read(), path, "exec"), mod.__dict__)
assert mod.FACE_RIG_OK, "bmo_face failed to import (see [FACE] message above)"
BotGUI, S = mod.BotGUI, mod.BotStates


class FakeLabel:
    def __init__(self):
        self.image = ""

    def config(self, image=None, **k):
        if image is not None:
            self.image = str(image)

    def cget(self, key):
        return self.image


class FakeMaster:
    def __init__(self):
        self.calls = []

    def after(self, ms, fn):
        self.calls.append(ms)


clock = {"t": 1000.0}
mod.time.time = lambda: clock["t"]  # deterministic lip-sync replay

gui = BotGUI.__new__(BotGUI)
gui.master = FakeMaster()
gui.status_label = _Any()
gui.status_label.winfo_ismapped = lambda: True
gui.background_label = FakeLabel()
gui.current_state = S.WARMUP
gui.last_state_change = clock["t"]
gui.current_mood = "neutral"
gui.last_mood_change = clock["t"]
gui.mood_duration = 300
gui.expressions_map = {"neutral": [S.IDLE]}
gui.screensaver_expr, gui.screensaver_expr_until = S.IDLE, 0
gui.animations = {}
gui.current_frame = 0
gui._lip_lock = threading.Lock()
gui._lip_sched, gui._lip_start, gui._lip_end = [], None, None
gui.mouth_open = gui.mouth_ema = 0
gui.speaking_frame = 0
gui.is_muted = False
gui.volume = 1.0
gui.face_view = mod.FaceView(gui.background_label, size=(800, 480))
gui._lip_sync = mod.LipSync(22050)
gui._rig_state = None
gui._rig_speech = mod.FACE_SILENT
gui._rig_frames = 0
gui._talk_mood = "idle"


def run(seconds, fps=30):
    seen = []
    for _ in range(int(seconds * fps)):
        clock["t"] += 1 / fps
        gui.update_animation()
        r = gui.face_view.rig
        seen.append((r.expr["name"], r.speech.get("viseme"), bool(r.speech.get("active"))))
    return seen


log = []

seen = run(0.5)
assert seen[-1][0] == "sleepy", seen[-1]
assert gui.background_label.image == str(gui.face_view.photo), "label not showing the rig"
log.append(f"warm-up: rig draws '{seen[-1][0]}', next tick {gui.master.calls[-1]} ms")

gui.set_state(S.SPEAKING, "Ready!")
gui._schedule_wav_lipsync(GREETING_A)
seen = run(4.0)
vis = [v for _, v, a in seen if a]
assert set(vis) & set("BCDEF"), f"no open mouth shapes: {set(vis)}"
assert not seen[-1][2], "speech should end after the clip"
log.append(f"greeting clip: {len(vis)} talking frames, shapes {''.join(sorted(set(vis)))}")

gui.set_state(S.LISTENING, "Listening...")
run(0.3)
gui.set_state(S.THINKING, "Thinking...")
run(0.3)
gui.set_state(S.HAPPY, "Feeling happy...")
run(0.1)
gui.current_state = S.SPEAKING  # what speak(msg=None) does

with wave.open(GREETING_B, "rb") as w:
    pcm = w.readframes(w.getnframes())


class FakeProc:
    def __init__(self, data=b""):
        self.stdout = io.BytesIO(data)
        self.stdin = io.BytesIO()

    def poll(self):
        return None


gui._piper_proc = FakeProc(pcm)
gui._tts_aplay = FakeProc()
with gui._lip_lock:
    gui._lip_sched, gui._lip_start, gui._lip_end = [], None, None
gui._lip_sync.reset()
gui._piper_to_aplay_loop()  # the real reader thread body, run inline
n = len(gui._lip_sched)
assert n > 50 and len(gui._lip_sched[0]) == 3 and gui._lip_sched[0][2] is not None
seen = run(3.2)
talk = [(e, v) for e, v, a in seen if a]
assert talk and all(e == "happy" for e, _ in talk), {e for e, _ in talk}
log.append(f"Piper stream: {n} chunks scheduled, talked {len(talk)} frames in mood '{talk[0][0]}'")

gui.set_state(S.IDLE, "Tap to speak")
assert run(0.5)[-1][0] == "idle"
# Every state is drawn by the rig; the PNG frames aren't preloaded.
all_states = {v for k, v in vars(S).items() if not k.startswith("_")} - {S.DISPLAY_IMAGE, S.SCREENSAVER}
missing = all_states - set(mod.RIG_EXPRESSIONS)
assert not missing, f"states without a rig face: {missing}"
for state, expr in mod.RIG_EXPRESSIONS.items():
    if state == S.SPEAKING:
        continue
    gui.current_state = state
    seen = run(0.2)
    assert seen[-1][0] == expr, (state, seen[-1][0])
    assert gui.background_label.image == str(gui.face_view.photo), state
gui.load_animations()
assert gui.animations == {}, "PNG frames should not be preloaded while the rig works"
gui.current_state = S.IDLE
run(0.1)
log.append(f"every face: {len(mod.RIG_EXPRESSIONS) - 1} states drawn by the rig, no PNGs preloaded")

# The wake-word flow pre-warms Piper with nothing attached to its output.
# speak() must still wire up the reader + aplay, or every reply is silent.
wired = []
gui._piper_proc = FakeProc()          # warm: alive, but no reader / aplay yet
gui._piper_reader_thread = None
gui._tts_aplay = None
gui.speak_lock = threading.Lock()
gui._start_tts_turn = lambda: wired.append(True)
gui._write_to_piper = lambda text: None
gui.speak("Hello friend!", msg=None, end_of_turn=False)
assert wired, "speak() wrote to a warm Piper without starting the audio pipeline"
log.append("speech: a pre-warmed Piper still gets wired to the speaker")
del gui._start_tts_turn, gui._write_to_piper
gui.current_state = S.IDLE

# A set_expression tag that lands while BMO is still talking (Piper runs
# ahead of playback) must change the talking mood, not freeze the face on
# the expression.  Before this, a late "curious" tag showed an open-O face.
import json  # noqa: E402
import re  # noqa: E402


def _extract_json(text):
    m = re.search(r"\{[^{}]*\}", text)
    return (json.loads(m.group()), m.span()) if m else (None, None)


mod.extract_json_object = _extract_json
spoken = []
gui.speak = lambda text, msg=None, end_of_turn=True: spoken.append(text)
gui.current_state = S.SPEAKING
gui._talk_mood = "idle"
gui._handle_response_chunk('It might rain. {"action": "set_expression", "value": "curious"}', is_last=False)
assert gui.current_state == S.SPEAKING, gui.current_state
assert gui._talk_mood == "surprised", gui._talk_mood
gui.current_state = S.THINKING  # before speech starts, the tag still sets the face
gui._handle_response_chunk('{"action": "set_expression", "value": "happy"} Yay!', is_last=False)
assert gui.current_state == S.HAPPY, gui.current_state
log.append("expressions: a late tag keeps BMO talking in that mood; an early one sets the face")
del gui.speak
gui.current_state = S.IDLE

gui.face_view.rig.frame = lambda: 1 / 0
gui.animations[S.IDLE] = [FakePhoto()]
print("(an intentional ZeroDivisionError traceback follows)")
gui.update_animation()
assert gui.face_view is None
log.append("fallback: a rig exception switches to PNG faces instead of crashing")

print("\n".join(log))
print("ALL FACE-RIG AGENT CHECKS PASSED")
