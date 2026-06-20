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

The host is fully implemented and tested (run `uv run pytest`); the live path is verified in
software via the DDP sink. The M0 firmware is written **to the protocols** but has not been
compiled or run on a board here — on-hardware steps (real pixels, the free-RAM measurement,
the WLED version check) are the operator's to run and are marked `TODO` in the firmware
README. The host wire format (`host/protocol.py`, `host/transports/ddp.py`) is the contract
the firmware mirrors.

## License

Apache 2.0 — see `LICENSE`.
