<!--
Copyright 2026 The Blitzen Authors
SPDX-License-Identifier: Apache-2.0
-->

# Blitzen — agent instructions

Networked LED display control. One Python host process drives heterogeneous WiFi LED
displays; a thin custom firmware runs on an Adafruit Feather M0 + RGB Matrix FeatherWing.
The authoritative design is `led_control_design.md`; the build contract is
`claude_code_handoff.md`. Read those before making non-trivial changes.

## Core principle

**Generality lives in the host, firmware stays thin.** The host is the only component that
sees all displays, so the abstraction belongs there. Do not push display-type logic into the
M0 firmware.

## Hard constraints (do not violate without flagging)

- **Never reflash, fork, or reconfigure-beyond-2D-matrix the WLED devices.** Control them only
  over the network (DDP for live, HTTP/JSON for presets/playlists).
- **Host framebuffers are always logical row-major RGB888** (`host/frame.py`). No
  serpentine/scan remap on the host — that is the device's or WLED-config's job.
- **The live path is unified on DDP/UDP:4048 for every target.** Standalone playback uses each
  device's native mechanism (M0 slot ring; WLED presets/playlists).
- **Measure M0 SRAM, don't assume.** Slot-ring capacity is computed from the measured free pool,
  not hardcoded. The measured number lives in `firmware/m0/README.md`.
- **Adding a new display type = one new transport + target.** Pattern code never changes. The
  `StubTarget` seam test in `host/tests/` guards this.

## Layout

- `host/` — the importable Python package (`import host.frame`, etc.).
  - `frame.py`, `patterns/`, `transports/` (`ddp`, `m0_control`, `wled_control`), `encoder.py`,
    `targets.py`, `orchestrator.py`, `cli.py`, `tools/ddp_sink.py`, `tests/`.
- `firmware/m0/` — Arduino C++ thin client (Adafruit_Protomatter + WiFi101).

## Conventions

- Python 3.11+, managed with `uv`. Stdlib sockets/urllib/tomllib; `Pillow` only for the
  image/asset/encoder paths. `uv run pytest` runs the suite. Format with `pyink`, lint with
  `pylint` (88-col).
- Firmware: **Adafruit_Protomatter + WiFi101** (ATWINC1500) — **not** WiFiNINA. Pin library
  versions in the firmware README.
- Apache-2.0 headers on all source files. Real device config is local-only: copy
  `host/devices.example.toml` → `host/devices.toml` and `firmware/m0/config.h.example` →
  `firmware/m0/config.h` (both gitignored).

## Validation

- Hardware-free: `uv run pytest`, plus the software DDP sink demo
  (`uv run python -m host.tools.ddp_sink` + `uv run blitzen run ...`).
- On-hardware steps (real pixels, free-RAM measurement, WLED version check) are run by the user
  and tracked as TODO in the READMEs. Do not fake passing hardware tests.
