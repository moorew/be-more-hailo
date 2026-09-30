"""Render the rig without a screen: expression sheets, WAV lip-sync frames, timing.

    python -m bmo_face.preview sheet  out/expressions.png
    python -m bmo_face.preview wav    sounds/greeting_sounds/greeting_01.wav out/greeting_01
    python -m bmo_face.preview bench  [--supersample 2]
"""

from __future__ import annotations

import argparse
import os
import time

from PIL import Image, ImageDraw

from .lipsync import analyse_wav
from .render import PillowRenderer
from .rig import FaceRig, load_presets


def sheet(out: str, size=(400, 240), cols: int = 4) -> None:
    names = list(load_presets()["expressions"])
    rows = (len(names) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * size[0], rows * size[1]), (20, 30, 28))
    for i, name in enumerate(names):
        rig = FaceRig()
        rig.blinker.next = 99
        rig.set_expression(name, instant=True)
        rig.p["breathe"].snap(0)
        rig.p["motion"].snap(0)
        img = PillowRenderer(rig.shapes, size).render(rig.frame())
        ImageDraw.Draw(img).text((8, 6), name, fill=(0, 0, 0))
        canvas.paste(img, ((i % cols) * size[0], (i // cols) * size[1]))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    canvas.save(out)
    print(f"wrote {out}")


def wav(path: str, out_dir: str, fps: int = 30, size=(800, 480)) -> None:
    items, duration = analyse_wav(path)
    rig = FaceRig()
    renderer = PillowRenderer(rig.shapes, size)
    os.makedirs(out_dir, exist_ok=True)
    dt, t, i, n = 1 / fps, 0.0, 0, int((duration + 0.6) * fps)
    thumbs = []
    for frame in range(n):
        t += dt
        latest, onset = None, False
        while i < len(items) and items[i][0] <= t:
            latest = items[i][2]
            onset = onset or latest["onset"]
            i += 1
        if latest is not None:
            rig.set_speech({**latest, "onset": onset})
        elif t > duration + 0.15:
            rig.set_speech({"viseme": "X", "intensity": 0, "active": False, "onset": False})
        rig.update(dt)
        img = renderer.render(rig.frame())
        img.save(os.path.join(out_dir, f"frame_{frame:04d}.png"))
        thumbs.append(img.resize((200, 120)))
    cols = 10
    sheet_img = Image.new("RGB", (cols * 200, ((len(thumbs) + cols - 1) // cols) * 120))
    for k, th in enumerate(thumbs):
        sheet_img.paste(th, ((k % cols) * 200, (k // cols) * 120))
    sheet_img.save(os.path.join(out_dir, "contact_sheet.png"))
    print(f"wrote {n} frames + contact_sheet.png to {out_dir}")


def bench(supersample: int = 2, frames: int = 300) -> None:
    rig = FaceRig()
    renderer = PillowRenderer(rig.shapes, (800, 480), supersample=supersample)
    visemes = "XABCDEFBCDA"
    t0 = time.perf_counter()
    for k in range(frames):
        rig.set_speech({"viseme": visemes[(k // 3) % len(visemes)], "intensity": 0.7, "active": True, "onset": k % 9 == 0})
        rig.update(1 / 30)
        renderer.render(rig.frame())
    ms = (time.perf_counter() - t0) * 1000 / frames
    print(f"update+render: {ms:.1f} ms/frame at supersample={supersample} ({1000 / ms:.0f} fps max)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("out")
    w = sub.add_parser("wav")
    w.add_argument("path")
    w.add_argument("out_dir")
    w.add_argument("--fps", type=int, default=30)
    b = sub.add_parser("bench")
    b.add_argument("--supersample", type=int, default=2)
    a = ap.parse_args()
    if a.cmd == "sheet":
        sheet(a.out)
    elif a.cmd == "wav":
        wav(a.path, a.out_dir, a.fps)
    else:
        bench(a.supersample)


if __name__ == "__main__":
    main()
