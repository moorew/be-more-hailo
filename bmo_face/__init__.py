"""BMO face rig: morphing mouth/eye shapes, behaviours, and spectral lip-sync.

    from bmo_face import FaceRig, PillowRenderer
    rig = FaceRig()
    renderer = PillowRenderer(rig.shapes, size=(800, 480))
    rig.set_expression("happy")
    rig.update(1 / 30)
    image = renderer.render(rig.frame())   # PIL.Image, 800x480

Web twin: web/bmo-face.js (same shapes.json / expressions.json).
"""

from .lipsync import LipSync, LipSyncAnalyser, VisemeSelector, analyse_wav
from .render import PillowRenderer
from .rig import SILENT, FaceRig, Spring, load_presets, load_shapes

__all__ = [
    "FaceRig", "Spring", "SILENT", "load_shapes", "load_presets",
    "PillowRenderer", "LipSync", "LipSyncAnalyser", "VisemeSelector", "analyse_wav",
]
