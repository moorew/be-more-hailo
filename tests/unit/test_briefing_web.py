"""The briefing in the web UI: today's cached script, audio and card PNGs."""
import datetime
import struct
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.briefing import audio, script, web
from tests.unit.test_briefing_script import HEADLINES, NOW, weather


def _wav(text, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050)
        w.writeframes(struct.pack("<h", 300) * 2205)


def client(monkeypatch, tmp_path, with_briefing=True):
    monkeypatch.setattr(audio, "CACHE_ROOT", str(tmp_path))
    monkeypatch.setattr(web, "_today", lambda: NOW.date())
    if with_briefing:
        parts = script.build_script({"weather": weather(), "headlines": HEADLINES, "extras": {}}, NOW)
        audio.render_briefing(parts, NOW.date(), cache_root=str(tmp_path), to_wav=_wav)
    return TestClient(web.mounted(FastAPI()))


def test_briefing_json_lists_parts_audio_and_cards(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    data = c.get("/api/briefing").json()
    assert [p["key"] for p in data["parts"]] == ["weather", "headlines", "signoff"]
    assert data["parts"][1]["marks"] and data["parts"][0]["text"].startswith("Good morning!")
    assert data["parts"][2]["card"] == data["parts"][1]["card"]           # sign-off keeps the last card
    wav = c.get(data["parts"][0]["audio"])
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    png = c.get(data["parts"][1]["card"] + "&highlight=1")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_no_briefing_yet_says_how_to_get_one(monkeypatch, tmp_path):
    r = client(monkeypatch, tmp_path, with_briefing=False).get("/api/briefing")
    assert r.status_code == 404 and "brief me" in r.json()["detail"]


def test_bad_part_numbers(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    assert c.get("/api/briefing/audio/9").status_code == 404
    assert c.get("/api/briefing/card/2").status_code == 404                 # the sign-off has no card
    assert datetime.date.today  # (keeps flake8 quiet about the import on some setups)
