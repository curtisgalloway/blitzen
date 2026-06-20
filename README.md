<!--
Copyright 2026 The Blitzen Authors
SPDX-License-Identifier: Apache-2.0
-->

# Blitzen

One Python host process drives multiple, heterogeneous WiFi LED displays — same pattern or
different, live or standalone — and is general enough to add a new display type with one
adapter and **no pattern changes**.

Two device classes today:

- **HUB75 panel** — Adafruit Feather M0 WiFi + RGB Matrix FeatherWing (32×32), running the
  thin custom firmware in `firmware/m0/`.
- **WLED arrays** — stock-firmware 8×32 matrices, controlled over their native network
  protocols (never reflashed).

The **live path is unified on DDP** (UDP/4048) for every target. **Standalone** playback
uses each device's native mechanism: an M0 RAM slot ring, or WLED presets/playlists.

Design rationale: `led_control_design.md` (authoritative). Build contract:
`claude_code_handoff.md`. Agent guide: `AGENTS.md`.

```
 Pattern  render(w, h, t) -> Frame (logical row-major RGB888)
    |
 Orchestrator  ticks per target at its fps; renders at its geometry; pushes
    |
 Target    DisplayTarget = geometry + transport (+ optional standalone API)
    |   \
 M0Target  WLEDTarget   transports: DDP (live) · M0 control (store/play) · WLED HTTP
```

## Install

```bash
uv sync          # Python 3.11+ (uv fetches 3.12), installs Pillow + the blitzen CLI
uv run pytest    # 83 host tests, no hardware required
```

## Quickstart

### 0. Hardware-free demo (proves the live path end to end)

```bash
# terminal 1: a software DDP "display" that previews frames in the terminal
uv run python -m host.tools.ddp_sink --geometry 32x32

# terminal 2: drive it
uv run blitzen --config host/devices.example.toml run --pattern plasma --target localsink --duration 5
```

Copy and edit the device map for real hardware:

```bash
cp host/devices.example.toml devices.toml   # then set each target's host/IP
```

### 1. Bring up a WLED array first (fastest path to real pixels)

```bash
uv run blitzen probe --target arr1                      # confirm WLED >= 0.14 + 2D matrix
uv run blitzen run   --pattern plasma --target arr1     # live DDP
uv run blitzen wled  --target arr1 --preset 3           # trigger a standalone preset
```

### 2. The M0 panel — same host code, no special-casing

Flash the firmware (see `firmware/m0/README.md`), then:

```bash
uv run blitzen run  --pattern plasma --target panel     # same command shape as WLED
uv run blitzen info --target panel                      # free RAM / slot capacity
```

### 3. Standalone M0 loop

```bash
uv run blitzen upload --target panel --asset clip.gif --resume idle
# unplug the host: the loop keeps running. A live `run` frame preempts it; it resumes.
```

### 4. Everything at once

```bash
# same pattern on both
uv run blitzen run --pattern plasma --target panel --target arr1 --fps 30
# different patterns / fps per target
uv run blitzen run --assign panel=plasma@30 --assign arr1=scroll@15
```

## WLED array bring-up

Validated rig: an **Adafruit Sparkle Motion Stick** (ESP32) driving an **8×32** (256 px)
addressable matrix, running WLED **16.0.0**.

1. **Flash WLED + join WiFi** — use the [WLED web installer](https://install.wled.me)
   (Chrome/Edge). If its Wi‑Fi step doesn't appear, join the device's `WLED-AP` (password
   `wled1234`) and set your SSID at `http://4.3.2.1` → WiFi Setup.
2. **Find its IP** — `uv run python -m host.tools.find_wled` (scans your /24 for WLED's API).
3. **Configure LED output + 2D matrix** over the JSON API — GPIO 21 is the Stick's data output;
   the 500 mA cap keeps it USB‑safe. A reboot is required for the 2D map to take effect:
   ```bash
   IP=10.66.27.221
   curl -s -X POST -H "Content-Type: application/json" \
     -d '{"hw":{"led":{"total":256,"maxpwr":500,"ins":[{"start":0,"len":256,"pin":[21],"order":0,"type":22,"ledma":55}]}}}' \
     http://$IP/json/cfg
   curl -s -X POST -H "Content-Type: application/json" \
     -d '{"hw":{"led":{"matrix":{"mpc":1,"panels":[{"s":true,"x":0,"y":0,"h":8,"w":32}]}}}}' \
     http://$IP/json/cfg
   curl -s -X POST -d '{"rb":true}' http://$IP/json/state    # reboot to apply the 2D map
   ```
   (Equivalently, set LED Preferences + 2D Configuration in the WLED UI.) Flip `"s"`
   (serpentine) if alternate rows zigzag.
4. **Add to `devices.toml`** and validate:
   ```bash
   uv run blitzen probe --target arr1                    # WLED >= 0.14 + 2D matrix: yes
   uv run blitzen run   --pattern plasma --target arr1   # live DDP
   uv run blitzen wled  --target arr1 --preset 1         # standalone preset trigger
   ```

> ⚠️ **Power:** 256 WS2812 at full white ≈ 15 A, but the Stick's USB input is fused at 2 A. Keep
> WLED's current limit / brightness low for USB‑only testing, or power the array from external
> 5 V (sharing ground with the Stick). Two arrays (512 px) need an external supply.

## Camera pixel-mapping (auto-calibration)

Some matrices (tiled 8×8 sub‑panels, odd serpentine, several chained panels) don't map cleanly
from a flat WLED 2D config, so logical frames come out scrambled. Instead of guessing the
layout, point a webcam at the panel and let Blitzen learn it: it lights each LED in turn, finds
its position in the camera image, and writes a **ledmap** (DDP index → physical col,row).

```bash
uv sync --extra vision     # OpenCV + NumPy (one-time)

# 1) set the WLED device to gw*gh LEDs (e.g. 64x8 = 512), aim a webcam at the panel
#    (whole panel framed, in focus, dark background; hold still during the ~1 min scan)
uv run python -m host.tools.calibrate_camera --ip 10.0.0.5 --gw 64 --gh 8 --cam 0
#    -> writes ledmap.json (+ calib_grid.png overlay)

# 2) drive it through the map -- geometry check, then scrolling text:
uv run python -m host.tools.render_mapped --ip 10.0.0.5 --map ledmap.json --mode cols --capture
uv run python -m host.tools.render_mapped --ip 10.0.0.5 --map ledmap.json --mode scroll \
    --text "FOUR SCORE AND SEVEN YEARS"
```

Scanning one LED at a time makes detection robust to bloom/auto‑exposure (a single lit dot is
always a clean blob). `render_mapped` carries a minimal 5×7 font (extend `FONT` for full
coverage). Validated on the Sparkle Motion + single 8×32; a chained 64×8 (two panels) just
needs a re‑scan once both panels are powered.

## CLI

| Command | Purpose |
|---|---|
| `run` | drive target(s) live (`--pattern`+`--target`, or `--assign NAME=PATTERN[@FPS]`) |
| `upload` | encode an image/GIF and upload an M0 standalone loop |
| `wled` | trigger a WLED preset/playlist or power |
| `info` | query M0 free RAM / slot usage |
| `probe` | check WLED version + 2D-matrix config |

Patterns: `plasma`, `scroll`, `solid`, `gradient` (all procedural — valid at any geometry).

## Layout

```
host/                Python package (frame, patterns, transports, encoder, targets,
                     orchestrator, cli, tools/ddp_sink, tests)
firmware/m0/         Arduino C++ thin client (Protomatter + WiFi101) + build README
led_control_design.md / claude_code_handoff.md / AGENTS.md
```

## Status

Both display classes are **validated on real hardware** (and `uv run pytest` passes, 83 tests):

- **M0 panel** (Feather M0 + 32×32): WiFi join, live DDP rendering, control over WiFi, an
  untethered RAM loop, and live-preempts-loop with idle-timeout resume. Measured memory + log in
  `firmware/m0/README.md` (Protomatter dominates SRAM → default 3-bit / 6-frame loop). Build with
  `firmware/m0/flash.sh`.
- **WLED array** (Adafruit Sparkle Motion Stick + 8×32, WLED 16.0.0): `probe`, live DDP
  (plasma/scroll), and preset trigger — see [WLED array bring-up](#wled-array-bring-up).
- **Concurrency**: one `blitzen run` drives the M0 panel and the WLED array at once, same or
  different patterns — proven on both devices simultaneously.

## License

Apache 2.0 — see `LICENSE`.
