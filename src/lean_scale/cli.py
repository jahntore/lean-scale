import argparse
import json
import logging
import math
import signal
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .core import Config, Controller
from .hypr import Display, closest_scale, get_monitor, monitors, require_lua, restore_saved
from .runtime import Lock, Server, request
from .storage import config_path, load_json, recovery_path, save_json
from .vision import Camera, install_model

log = logging.getLogger(__name__)


def read_config(path: Path) -> Config:
    if not path.exists():
        raise RuntimeError(f"No configuration at {path}; run `lean-scale calibrate` first")
    return Config(**load_json(path))


def sample(camera: Camera, title: str, fps: float) -> float:
    input(f"\n{title}\nFace the webcam, then press Enter. Hold still for 5 seconds… ")
    # Discard buffered frames and let auto-exposure settle before collecting.
    start = time.monotonic()
    samples = []
    deadline = start + 6
    while time.monotonic() < deadline:
        before = time.monotonic()
        eye = camera.read()
        if eye is not None and before - start >= 1:
            samples.append(eye)
        remaining = max(0, math.ceil(deadline - before))
        print(f"\r  {remaining}s remaining · {len(samples)} usable readings   ", end="", flush=True)
        time.sleep(max(0, 1 / fps - (time.monotonic() - before)))
    print()
    if len(samples) < 15:
        raise RuntimeError(
            "Too few face readings. Improve lighting and face the camera, then retry."
        )
    median = statistics.median(samples)
    deviation = statistics.median(abs(value - median) for value in samples)
    if deviation / median > 0.06:
        raise RuntimeError("Position was not stable enough. Hold your head still and retry.")
    print(f"  Median eye spacing: {median:.4f} of frame width")
    return median


def calibrate(args):
    require_lua()
    with Lock():
        if recovery_path().exists():
            raise RuntimeError("Recovery state exists; run `lean-scale restore` first")
        monitor = get_monitor(args.monitor)
        normal_scale = float(monitor["scale"])
        desired = args.lean_scale if args.lean_scale is not None else normal_scale * 1.25
        if not math.isfinite(desired) or not normal_scale < desired <= 4:
            raise ValueError("Leaned scale must be greater than current scale and no more than 4")
        leaned_scale = closest_scale(monitor, desired)
        if args.lean_scale is not None and abs(leaned_scale - desired) > 0.005:
            raise ValueError(
                f"Scale {desired:g} gives fractional logical pixels; try --lean-scale {leaned_scale:g}"
            )
        if leaned_scale <= normal_scale + 0.01:
            raise ValueError("Choose a larger leaned-back scale")
        print(f"Monitor: {monitor['name']} · normal {normal_scale:.4g} → leaned {leaned_scale:.4g}")
        print("Calibration activates the webcam, but does not change monitor scaling.")
        camera = Camera(args.camera)
        try:
            normal = sample(camera, "1/2 · Sit in your NORMAL working position.", 8)
            leaned = sample(camera, "2/2 · LEAN BACK comfortably, still facing the camera.", 8)
        finally:
            camera.close()
        config = Config(
            monitor=monitor["name"],
            camera=args.camera,
            normal_eye=normal,
            leaned_eye=leaned,
            normal_scale=normal_scale,
            leaned_scale=leaned_scale,
        )
        save_json(args.config, asdict(config))
        print(f"Saved {args.config}\nNext: lean-scale run --dry-run")


def run(args):
    config = read_config(args.config)
    require_lua()
    with Lock():
        if recovery_path().exists() and not args.dry_run:
            raise RuntimeError("An earlier run did not clean up. Run `lean-scale restore` first.")
        display = Display(config.monitor, args.dry_run)
        if not math.isclose(display.original, config.normal_scale, abs_tol=0.005):
            raise RuntimeError(
                "Monitor scale differs from calibration. Recalibrate at your normal scale."
            )
        controller = Controller(config)
        camera = None
        paused, stopping, tracking = False, False, False
        last_log = 0
        old_signals = {}

        def stop(*_):
            nonlocal stopping
            stopping = True

        def status():
            return {
                "monitor": config.monitor,
                "paused": paused,
                "dry_run": args.dry_run,
                "state": controller.state,
                "scale": display.expected,
                "tracking": tracking,
                "lean": controller.progress,
            }

        def handle(command):
            nonlocal paused, stopping, camera, tracking
            if command == "stop":
                stopping = True
            elif command in {"pause", "resume", "toggle"}:
                new_paused = not paused if command == "toggle" else command == "pause"
                if new_paused != paused:
                    if new_paused:
                        if camera:
                            camera.close()
                            camera = None
                        tracking = False
                        display.restore()
                        log.info("Paused; webcam released and original scale restored")
                    else:
                        log.info("Resumed")
                    paused = new_paused
                    controller.reset()
            elif command != "status":
                return {"error": "Unknown command"}
            return status()

        for signum in (signal.SIGINT, signal.SIGTERM):
            old_signals[signum] = signal.signal(signum, stop)
        try:
            with Server() as server:
                log.info(
                    "%sMonitoring %s. Ctrl+C stops; `lean-scale toggle` pauses/releases webcam.",
                    "DRY RUN — " if args.dry_run else "",
                    config.monitor,
                )
                while not stopping:
                    before = time.monotonic()
                    server.poll(handle)
                    if stopping:
                        break
                    if not paused:
                        if camera is None:
                            camera = Camera(config.camera, config.fps)
                        eye = camera.read()
                        tracking = eye is not None
                        now = time.monotonic()
                        transition = controller.update(eye, now)
                        if transition:
                            scale = (
                                config.leaned_scale
                                if transition == "leaned"
                                else config.normal_scale
                            )
                            display.apply(scale)
                        if now - last_log >= 2:
                            progress = (
                                f"{controller.progress:.0%}" if tracking else "no reliable face"
                            )
                            log.info(
                                "%s · lean %s · scale %.4g",
                                controller.state,
                                progress,
                                display.expected,
                            )
                            last_log = now
                    time.sleep(max(0, 1 / config.fps - (time.monotonic() - before)))
        finally:
            try:
                if camera:
                    camera.close()
            finally:
                try:
                    display.restore()
                finally:
                    for signum, handler in old_signals.items():
                        signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(
        description="Local webcam-driven scaling for Hyprland's Lua API. No video is saved."
    )
    parser.add_argument(
        "--config", type=Path, default=config_path(), help="configuration JSON path"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="download and verify the 233 KB face model; no camera access")
    sub.add_parser("devices", help="list camera nodes and connected monitors; no camera access")
    calibration = sub.add_parser("calibrate", help="capture normal and leaned-back posture")
    calibration.add_argument("--camera", default="0", help="camera index or /dev/videoN path")
    calibration.add_argument("--monitor", help="connector name; defaults to the focused monitor")
    calibration.add_argument(
        "--lean-scale", type=float, help="leaned scale; default about 25%% larger"
    )
    running = sub.add_parser("run", help="start camera tracking in the foreground")
    running.add_argument(
        "--dry-run", action="store_true", help="log decisions without changing scale"
    )
    for command in ("status", "pause", "resume", "toggle", "stop"):
        sub.add_parser(command, help=f"{command} the running daemon")
    sub.add_parser("restore", help="recover original scale after an unclean exit")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )
    try:
        if args.command == "setup":
            print(f"Face model ready: {install_model()}")
        elif args.command == "devices":
            for node in sorted(Path("/sys/class/video4linux").glob("video*")):
                print(f"/dev/{node.name}: {(node / 'name').read_text().strip()}")
            for monitor in monitors():
                print(
                    f"{monitor['name']}: {monitor['width']}×{monitor['height']}, scale {monitor['scale']:.4g}"
                )
        elif args.command == "calibrate":
            calibrate(args)
        elif args.command == "run":
            run(args)
        elif args.command == "restore":
            require_lua()
            with Lock():
                restore_saved()
            print("Original scale restored (or no recovery needed).")
        else:
            print(json.dumps(request(args.command), indent=2))
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
