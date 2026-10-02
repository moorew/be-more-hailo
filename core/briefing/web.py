"""The morning briefing in the web UI: today's cached script, audio and cards.

The browser plays the same WAVs BMO recorded and shows the same Pillow
cards (rendered here as PNGs, full width).  The web app never renders a
briefing itself: it's a separate process from the agent and would race it
for the cache folder, so with nothing cached yet it says to ask BMO.
"""
import datetime
import io
import os
import threading

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from core.briefing import audio, cards

router = APIRouter()
_card_cache = {}
_card_lock = threading.Lock()


def _today():
    return datetime.date.today()


def _load(cache_root=None):
    b = audio.load_briefing(_today(), cache_root or audio.CACHE_ROOT)
    if b is None:
        raise HTTPException(404, "No briefing yet today. Say \"brief me\" to BMO and it will make one.")
    return b


@router.get("/api/briefing")
def briefing():
    b = _load()
    keys = [p["key"] for p in b["parts"] if p.get("card")]
    parts = []
    last_card = None
    for i, p in enumerate(b["parts"]):
        if p.get("card"):
            last_card = i
        parts.append({"key": p["key"], "text": p["text"], "duration": p.get("duration"),
                      "marks": p.get("marks") or [],
                      "audio": f"/api/briefing/audio/{i}?v={int(b['created'])}",
                      "card": f"/api/briefing/card/{last_card}?v={int(b['created'])}"
                      if last_card is not None else None})
    return {"date": b["date"], "created": b["created"], "keys": keys, "parts": parts}


@router.get("/api/briefing/audio/{n}")
def briefing_audio(n: int):
    b = _load()
    if not 0 <= n < len(b["parts"]):
        raise HTTPException(404, "No such part")
    return FileResponse(b["parts"][n]["path"], media_type="audio/wav")


@router.get("/api/briefing/card/{n}")
def briefing_card(n: int, highlight: int = None):
    b = _load()
    if not 0 <= n < len(b["parts"]) or not b["parts"][n].get("card"):
        raise HTTPException(404, "No card for that part")
    key = (b["date"], b["created"], n, highlight)
    with _card_lock:
        png = _card_cache.get(key)
        if png is None:
            part = b["parts"][n]
            keys = [p["key"] for p in b["parts"] if p.get("card")]
            x0, y0, x1, y1 = cards.CARD_BOX_FULL
            img = cards.draw_card(part, keys, keys.index(part["key"]), (x1 - x0, y1 - y0), highlight)
            screen = cards.Image.new("RGB", (800, 480), cards.C["screen"])
            screen.paste(img, (x0, y0), img)
            buf = io.BytesIO()
            screen.save(buf, "PNG", optimize=True)
            png = buf.getvalue()
            if len(_card_cache) > 40:
                _card_cache.clear()
            _card_cache[key] = png
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


def mounted(app):
    """Add the routes to the web app (idempotent)."""
    if not any(getattr(r, "path", None) == "/api/briefing" for r in app.routes):
        app.include_router(router)
    return app


__all__ = ["router", "mounted", "os"]
