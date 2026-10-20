"""Hyprland Lua IPC; no persistent compositor configuration is edited."""

import json
import logging
import math
import re
import subprocess
import time

from .storage import load_json, recovery_path, save_json

log = logging.getLogger(__name__)


def hyprctl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["hyprctl", *args], capture_output=True, text=True, timeout=5, check=False
        )
        # hyprctl prints valid help to stdout but exits 1, including on 0.56.
        if result.returncode and not (args == ("--help",) and result.returncode == 1):
            result.check_returncode()
    except FileNotFoundError as exc:
        raise RuntimeError("hyprctl is not installed") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"hyprctl failed: {exc}") from exc
    text = result.stdout.strip()
    if re.search(r"^(error|unknown request|invalid)\b", text, re.IGNORECASE):
        raise RuntimeError(f"Hyprland rejected request: {text}")
    return text


def monitors() -> list[dict]:
    return json.loads(hyprctl("-j", "monitors"))


def get_monitor(name: str | None = None) -> dict:
    available = monitors()
    if name is None:
        chosen = next((m for m in available if m.get("focused")), None)
        chosen = chosen or (available[0] if available else None)
    else:
        chosen = next((m for m in available if m["name"] == name), None)
    if chosen is None:
        raise RuntimeError(f"Monitor {name or '(focused)'} is not connected")
    if chosen.get("mirrorOf", "none") != "none":
        raise RuntimeError("Mirrored monitors are not supported")
    return chosen


def require_lua():
    help_text = hyprctl("--help")
    if not re.search(r"^\s+eval\s", help_text, re.MULTILINE):
        raise RuntimeError("This app requires Hyprland's Lua API (`hyprctl eval`, Hyprland 0.55+)")


def closest_scale(monitor: dict, desired: float) -> float:
    """Keep logical width/height integral to avoid compositor scale fallback."""
    divisor = math.gcd(monitor["width"], monitor["height"])
    candidates = [divisor / n for n in range(1, divisor * 2 + 1) if 0.5 <= divisor / n <= 4]
    return min(candidates, key=lambda value: abs(value - desired))


def scale_lua(name: str, scale: float) -> str:
    if not math.isfinite(scale) or not 0.5 <= scale <= 4:
        raise ValueError("Scale must be finite and between 0.5 and 4")
    # JSON quoting is also valid Lua quoting for these ASCII connector names.
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", name):
        raise ValueError("Unsupported monitor connector name")
    return f"hl.monitor({{output={json.dumps(name)}, scale={scale:.9f}}})"


def set_scale(name: str, scale: float):
    hyprctl("eval", scale_lua(name, scale))
    deadline = time.monotonic() + 2.5
    actual = None
    while time.monotonic() < deadline:
        actual = get_monitor(name)["scale"]
        if math.isclose(actual, scale, abs_tol=0.005):
            return
        time.sleep(0.1)
    raise RuntimeError(
        f"Hyprland did not apply scale {scale:g} (actual {actual}); "
        "choose a scale with integral logical dimensions"
    )


class Display:
    def __init__(self, name: str, dry_run: bool = False):
        self.name = name
        self.original = float(get_monitor(name)["scale"])
        self.expected = self.original
        self.dry_run = dry_run
        self.changed = False

    def apply(self, scale: float):
        if math.isclose(scale, self.expected, abs_tol=0.005):
            return
        if self.dry_run:
            log.info("DRY RUN: %s scale %.4g -> %.4g", self.name, self.expected, scale)
            self.expected = scale
            return
        actual = get_monitor(self.name)["scale"]
        if not math.isclose(actual, self.expected, abs_tol=0.005):
            raise RuntimeError(
                "Display scale changed externally; stopping instead of overriding it"
            )
        # Journal before the mutation, so a crash/kill -9 can be recovered.
        save_json(
            recovery_path(),
            {
                "monitor": self.name,
                "original_scale": self.original,
                "previous_scale": self.expected,
                "target_scale": scale,
            },
        )
        self.changed = True
        self.expected = scale
        log.info("%s: applying scale %.4g", self.name, scale)
        try:
            set_scale(self.name, scale)
        except Exception:
            # Hyprland can substitute another scale if a request is invalid.
            # Roll back that failed request rather than treating it as a manual edit.
            try:
                set_scale(self.name, self.original)
                recovery_path().unlink(missing_ok=True)
                self.changed = False
                self.expected = self.original
            except Exception:
                log.exception("Rollback failed; recovery journal retained at %s", recovery_path())
            raise

    def restore(self):
        if self.dry_run:
            self.expected = self.original
            return
        if not self.changed:
            return
        restore_saved()
        self.changed = False
        self.expected = self.original


def restore_saved():
    path = recovery_path()
    if not path.exists():
        return
    saved = load_json(path)
    name, original = saved["monitor"], float(saved["original_scale"])
    actual = get_monitor(name)["scale"]
    known = [original, saved["previous_scale"], saved["target_scale"]]
    if any(math.isclose(actual, x, abs_tol=0.005) for x in known):
        if not math.isclose(actual, original, abs_tol=0.005):
            log.info("Restoring %s to %.4g", name, original)
            set_scale(name, original)
    else:
        log.warning("Not restoring %s: scale was changed externally to %s", name, actual)
    path.unlink(missing_ok=True)
