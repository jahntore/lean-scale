"""Pure, hardware-independent calibration and switching logic."""

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Config:
    monitor: str
    camera: str
    normal_eye: float
    leaned_eye: float
    normal_scale: float
    leaned_scale: float
    fps: float = 8.0
    dwell: float = 1.8
    smoothing: float = 0.6
    hysteresis: float = 0.15
    lost_timeout: float = 5.0

    def __post_init__(self):
        if not self.monitor or any(c in self.monitor for c in "\n\r\x00"):
            raise ValueError("Invalid monitor name")
        if not isinstance(self.camera, str) or not self.camera:
            raise ValueError("Camera must be an index or /dev/video path")
        for key, value in asdict(self).items():
            if key in {"monitor", "camera"}:
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number")
        if not 0 < self.leaned_eye <= self.normal_eye * 0.9 < 0.9:
            raise ValueError("Leaned-back eye spacing must be at least 10% smaller than normal")
        if not 0.5 <= self.normal_scale < self.leaned_scale <= 4:
            raise ValueError("Scales must satisfy 0.5 <= normal < leaned <= 4")
        if not 1 <= self.fps <= 30:
            raise ValueError("fps must be between 1 and 30")
        if not 0.2 <= self.dwell <= 15 or not 0.05 <= self.smoothing <= 5:
            raise ValueError("Invalid dwell or smoothing time")
        if not 0.05 <= self.hysteresis <= 0.4:
            raise ValueError("hysteresis must be between 0.05 and 0.4")
        if not 1 <= self.lost_timeout <= 60:
            raise ValueError("lost_timeout must be between 1 and 60 seconds")


class Controller:
    """Time-based EMA, Schmitt trigger, continuous dwell, and lost-face fallback.

    Returns a state only when a transition is needed. Missing/ambiguous readings
    break the dwell timer; no transition can be caused by stale measurements.
    """

    def __init__(self, config: Config):
        self.config = config
        self.reset()

    def reset(self):
        self.state = "normal"
        self.smoothed = None
        self.last_valid = None
        self.previous = None
        self.pending = None
        self.pending_since = None
        self.progress = None

    def update(self, eye: float | None, now: float) -> str | None:
        c = self.config
        if eye is None or not math.isfinite(eye) or eye <= 0:
            self.pending = self.pending_since = None
            self.previous = None
            if self.last_valid is not None and now - self.last_valid >= c.lost_timeout:
                self.smoothed = self.progress = None
                if self.state != "normal":
                    self.state = "normal"
                    return self.state
            return None

        # A long capture gap must not count toward a stable posture.
        if self.previous is None or now - self.previous > max(0.5, 3 / c.fps):
            self.smoothed = eye
            self.pending = self.pending_since = None
        else:
            alpha = 1 - math.exp(-(now - self.previous) / c.smoothing)
            self.smoothed += alpha * (eye - self.smoothed)
        self.previous = self.last_valid = now
        self.progress = (c.normal_eye - self.smoothed) / (c.normal_eye - c.leaned_eye)
        target = self.state
        if self.state == "normal" and self.progress >= 0.5 + c.hysteresis:
            target = "leaned"
        elif self.state == "leaned" and self.progress <= 0.5 - c.hysteresis:
            target = "normal"
        if target == self.state:
            self.pending = self.pending_since = None
        elif self.pending != target:
            self.pending, self.pending_since = target, now
        elif now - self.pending_since >= c.dwell:
            self.state = target
            self.pending = self.pending_since = None
            return target
        return None
