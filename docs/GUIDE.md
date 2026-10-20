# Setup & tuning

## Requirements

- Linux with a V4L2 webcam.
- A running Hyprland session with the Lua API (`hyprctl eval`; tested on 0.56).
- [uv](https://docs.astral.sh/uv/). It manages the project's Python environment.

Run in a terminal inside Hyprland, without sudo. The wrapper works from any directory; examples below assume you are in the project directory.

## First run

```sh
uv sync --locked
./lean-scale setup
./lean-scale devices
./lean-scale calibrate
./lean-scale run --dry-run
```

Calibration defaults to camera `0` and the currently focused monitor. To choose explicitly:

```sh
./lean-scale calibrate --camera /dev/video0 --monitor HDMI-A-1
```

Look toward the camera in both your normal and leaned-back positions. Calibration turns on the webcam but does not change scaling. It refuses measurements that are unstable or too similar. The default leaned scale is approximately 25% larger than the current scale, snapped to integral logical display dimensions.

Stop the dry run with **Ctrl+C**, then enable real scaling with `./lean-scale run`. Recalibrate when your normal scale, camera position, camera zoom, or seating setup changes.

## Controls & recovery

```sh
./lean-scale status
./lean-scale toggle
./lean-scale pause
./lean-scale resume
./lean-scale stop
./lean-scale restore
```

Pause releases the webcam and attempts to restore the starting scale. Resume reopens the camera. Ctrl+C, SIGTERM, stop, and handled errors also attempt restoration. `restore` recovers the saved scale after an unclean exit such as `kill -9`; stop the daemon before using it. Only one daemon, calibration, or recovery process can hold the lock.

If the app notices an external scale change before a transition or restoration, it avoids overwriting it. Recovery requires the selected monitor to be connected.

## Hyprland hotkey

Add this to your Lua configuration, replacing `/absolute/path/to/lean-scale` with the project directory:

```lua
hl.bind("SUPER + SHIFT + Z", hl.dsp.exec_cmd("/absolute/path/to/lean-scale/lean-scale toggle"))
```

For optional autostart **after testing and calibration**, merge this into your startup handler:

```lua
hl.on("hyprland.start", function()
    hl.exec_cmd("/absolute/path/to/lean-scale/lean-scale run")
end)
```

Neither snippet is installed automatically.

**Use an explicit monitor rule for your chosen connector**, rather than only a wildcard or description rule. Runtime updates use `hl.monitor({output=..., scale=...})`, which merges a rule for that exact connector. Without a matching rule, a new rule can inherit defaults. For example, configure `output = "HDMI-A-1"` with your usual mode, position, and scale.

No Hyprland configuration files are edited by the app. Reloading your configuration can override runtime scaling.

## How tracking works

YuNet detects faces and eye landmarks locally on CPU, at about 8 samples per second. Eye spacing relative to frame width estimates distance; this is not full body-pose analysis or a measurement in centimeters.

- Smoothing, hysteresis, and a **1.8-second stable-posture delay** reduce bouncing. Smoothing adds to total response time.
- Brief tracking loss holds the current level. **Five seconds without reliable tracking** returns to normal.
- Multiple faces, clipped/small faces, and substantial head turns are ignored. Moderate rotation can still look like moving away.
- A failed camera stops the app and attempts restoration.
- Only the calibrated monitor is targeted. Other monitors can move when Hyprland recalculates an automatic layout.
- Scale requests are checked against the reported scale. Rejected changes trigger rollback.

Changing monitor scale reflows windows, changes usable workspace size, and may briefly flicker. XWayland apps may look blurry. Dry-run mode cannot tell you whether the real transition will feel comfortable.

## Configuration

Calibration writes `~/.config/lean-scale/config.json`, respecting `XDG_CONFIG_HOME`. To use another file:

```sh
./lean-scale --config /path/to/config.json calibrate
./lean-scale --config /path/to/config.json run
```

Edit settings while the daemon is stopped:

| Field | Default | Meaning |
| --- | --- | --- |
| `monitor`, `camera` | calibration choice | Fixed connector and camera index/device path |
| `normal_eye`, `leaned_eye` | measured | Normalized eye spacing for each position |
| `normal_scale`, `leaned_scale` | selected | Normal and enlarged display scales |
| `fps` | 8 | Camera processing rate |
| `dwell` | 1.8 | Continuous stable posture required, seconds |
| `smoothing` | 0.6 | Smoothing time constant, seconds |
| `hysteresis` | 0.15 | Dead band around the midpoint of calibrated positions |
| `lost_timeout` | 5 | Seconds before unreliable tracking returns to normal |

To choose a leaned scale explicitly, use e.g. `./lean-scale calibrate --lean-scale 1.6`. Invalid fractional-logical-pixel scales produce a suggested alternative. The active scale must match `normal_scale` when starting.

The model and crash-recovery journal live in `~/.local/share/lean-scale/`, respecting `XDG_DATA_HOME`. The private control socket lives in `$XDG_RUNTIME_DIR/lean-scale/`, with a private per-user `/tmp` fallback. No image data is persisted. Only `setup` downloads the face model; tracking itself needs no network access. See [model source and license](../THIRD_PARTY.md).

## Troubleshooting

- **Cannot open camera:** try another capture node from `devices`; some nodes are metadata or infrared devices. Close other camera apps and check device permissions. Camera URLs and video files are not accepted.
- **Too few readings:** improve lighting, face the camera, and keep only one face visible. Very small/distant faces may not track.
- **Scale differs from calibration:** restore your normal scale or recalibrate at the desired normal scale.
- **Stale recovery state:** stop the daemon, reconnect the selected monitor if necessary, then run `restore`.
- **Slow response:** try `dwell: 1.0` and `smoothing: 0.4`. Faster settings are more susceptible to bouncing.
- **Unexpected reflow:** pause or stop; monitor scaling may not suit your workflow.

## Development

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests use synthetic readings, fake display IPC, and private test sockets—never the webcam or real display changes. Model loading and inference have also been smoke-tested on a synthetic black image. Real posture calibration and actual display transitions require an interactive test.
