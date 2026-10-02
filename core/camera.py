"""BMO's camera: one owner for photos and motion frames, plus a plain-words check.

Only one process (or Picamera2 instance) can hold the camera, so presence
detection and "take a photo" share this object instead of each opening it:
a small "lores" stream feeds motion detection, the main stream gives photos.
When Picamera2 isn't running (no camera, or presence detection is off),
photos fall back to rpicam-still as before.

    python -m core.camera --check     # why isn't the camera working?
"""
import logging
import os
import re
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)

PHOTO_SIZE = (640, 480)
MAIN_SIZE = (1280, 960)
LORES_SIZE = (320, 240)
CONFIG_TXT = "/boot/firmware/config.txt"


def cameras():
    """Cameras libcamera can see: [{"Model": "imx519", ...}], [] if none or no picamera2."""
    try:
        from picamera2 import Picamera2
        return list(Picamera2.global_camera_info())
    except Exception as e:
        logger.info(f"Camera: picamera2 unavailable ({e})")
        return []


class Camera:
    """Picamera2 with a lores stream for motion and a main stream for photos."""

    def __init__(self):
        self._cam = None
        self._lock = threading.Lock()
        self.model = None

    @property
    def running(self) -> bool:
        return self._cam is not None

    def start(self) -> bool:
        """Open and start the camera; False (and logged) if there isn't one."""
        with self._lock:
            if self._cam is not None:
                return True
            info = cameras()
            if not info:
                return False
            try:
                from picamera2 import Picamera2
                cam = Picamera2()
                config = cam.create_still_configuration(
                    main={"size": MAIN_SIZE, "format": "RGB888"},
                    lores={"size": LORES_SIZE, "format": "YUV420"},
                    buffer_count=2)
                cam.configure(config)
                cam.start()
                try:  # continuous autofocus on cameras that have it (IMX519, IMX708)
                    from libcamera import controls
                    cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
                except Exception:
                    pass
                self._cam = cam
                self.model = info[0].get("Model")
                logger.info(f"Camera: {self.model} started")
                return True
            except Exception as e:
                logger.warning(f"Camera: couldn't start ({e})")
                return False

    def stop(self):
        with self._lock:
            if self._cam is not None:
                try:
                    self._cam.stop()
                    self._cam.close()
                except Exception:
                    pass
                self._cam = None

    def motion_frame(self):
        """A small greyscale frame (numpy uint8, ~80x60) for motion detection, or None."""
        with self._lock:
            if self._cam is None:
                return None
            try:
                yuv = self._cam.capture_array("lores")
            except Exception as e:
                logger.warning(f"Camera: lores capture failed ({e})")
                return None
        h = LORES_SIZE[1]
        y = yuv[:h, :LORES_SIZE[0]]          # the Y (luma) plane
        return y[::4, ::4].copy()

    def photo(self, path: str) -> str:
        """Save a PHOTO_SIZE JPEG; uses the running camera, else rpicam-still.
        Raises CameraError with a message BMO can say."""
        with self._lock:
            cam = self._cam
            if cam is not None:
                try:
                    from PIL import Image
                    rgb = cam.capture_array("main")
                    # RGB888 in Picamera2 is BGR byte order.
                    Image.fromarray(rgb[:, :, ::-1]).resize(PHOTO_SIZE).save(path, quality=90)
                    return path
                except Exception as e:
                    logger.warning(f"Camera: capture from running camera failed ({e})")
        return _rpicam_still(path)


class CameraError(Exception):
    """Something BMO can say out loud about why there's no photo."""


def _rpicam_still(path: str) -> str:
    cmd = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    if cmd is None:
        raise CameraError("BMO doesn't have the camera software installed.")
    try:
        r = subprocess.run([cmd, "-o", path, "--width", str(PHOTO_SIZE[0]), "--height", str(PHOTO_SIZE[1]),
                            "--nopreview", "-t", "2000", "--autofocus-mode", "continuous"],
                           capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise CameraError("My camera took too long to respond. Let's try that again later!")
    if r.returncode != 0 or not os.path.exists(path):
        logger.warning(f"Camera: {os.path.basename(cmd)} failed: {(r.stderr or '').strip()[-300:]}")
        if "No cameras available" in (r.stderr or "") or not cameras():
            raise CameraError("BMO can't find my camera. Check that its ribbon cable is pushed in "
                              "all the way, then restart me.")
        raise CameraError("I tried to take a photo, but my camera isn't working.")
    return path


# --- diagnosis -------------------------------------------------------------------

_PROBE_FAIL = re.compile(r"(imx\d+|ov\d+)\s+[\w-]+:\s+failed to read chip id[^\n]*error (-?\d+)", re.I)


def _read(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def diagnose(kernel_log: str = None, config_txt: str = None, cams=None) -> list:
    """Plain-words findings about the camera, most important first."""
    cams = cameras() if cams is None else cams
    if cams:
        return [f"OK: libcamera sees {', '.join(c.get('Model', '?') for c in cams)}."]
    kernel_log = _read(["dmesg"]) if kernel_log is None else kernel_log
    if config_txt is None:
        try:
            with open(CONFIG_TXT) as f:
                config_txt = f.read()
        except OSError:
            config_txt = ""
    lines = [ln.split("#")[0].strip() for ln in config_txt.splitlines()]
    overlays = [ln.split("=", 1)[1] for ln in lines if ln.startswith("dtoverlay=") and
                re.match(r"(imx|ov)\d+", ln.split("=", 1)[1])]
    auto = "camera_auto_detect=1" in lines
    out = ["No camera is visible to libcamera."]
    m = _PROBE_FAIL.search(kernel_log or "")
    if m:
        sensor, err = m.group(1).upper(), m.group(2)
        out.append(f"The {sensor} driver loaded but the sensor didn't answer on its I2C bus "
                   f"(error {err}). The driver choice is fine; the camera isn't electrically "
                   "connected: power the Pi off, then check the ribbon cable is fully seated "
                   "and the right way round at both ends. A Pi 5 needs a 22-pin "
                   "(Pi 5) cable at the Pi end.")
    elif overlays:
        out.append(f"config.txt forces {', '.join(overlays)} but the kernel log shows no probe: "
                   "check the overlay name and port (cam0/cam1) match the camera.")
    elif not auto:
        out.append("camera_auto_detect is off and no camera overlay is set in config.txt.")
    else:
        out.append("Auto-detect is on but nothing was found: check the cable, or add the "
                   "overlay for a third-party camera (e.g. dtoverlay=imx519,cam0 for an Arducam 16MP).")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.camera")
    ap.add_argument("--check", action="store_true", help="explain why the camera does or doesn't work")
    ap.add_argument("--photo", metavar="PATH", help="take a test photo")
    args = ap.parse_args()
    if args.photo:
        try:
            print(Camera().photo(args.photo))
        except CameraError as e:
            print(f"Failed: {e}")
    for line in diagnose():
        print(line)
