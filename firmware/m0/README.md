<!--
Copyright 2026 The Blitzen Authors
SPDX-License-Identifier: Apache-2.0
-->

# Blitzen M0 firmware

Thin display client for an **Adafruit Feather M0 WiFi** (SAMD21 + ATWINC1500) with an
**RGB Matrix FeatherWing** driving a **32×32 HUB75** panel. It joins WiFi, renders live
DDP frames, and plays a host-uploaded 16-color loop untethered. All the generality lives
in the host (see `../../led_control_design.md` §2); this firmware stays thin on purpose.

## Libraries

Versions below are what this firmware was **built and flashed against** (arduino-cli 1.5.1):

| Library | Version | Notes |
|---|---|---|
| Adafruit Protomatter | `1.7.1` | HUB75 driver; subclasses Adafruit_GFX |
| Adafruit GFX Library | `1.12.6` | pulled in by Protomatter |
| WiFi101 | `0.16.1` | **ATWINC1500** — do **not** use WiFiNINA |
| Adafruit SAMD Boards (core) | `1.7.17` | board package for the Feather M0 |

## Build & flash

One-time toolchain install:

```bash
brew install arduino-cli
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
  https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli core update-index
arduino-cli core install adafruit:samd
arduino-cli lib install "Adafruit Protomatter" "Adafruit GFX Library" "WiFi101"
```

Configure WiFi and flash:

```bash
cp secrets.example.yaml secrets.yaml    # then edit ssid/password -- 2.4 GHz only!
./flash.sh                              # gen config.h + compile + upload
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200   # boot log: free RAM, slots, IP
```

`flash.sh` copies the sketch into `build/m0_display_client/` (a matching-name folder, which
Arduino requires), runs `gen_config.py` to turn `secrets.yaml` into `config.h`, then compiles
and uploads for `adafruit:samd:adafruit_feather_m0`. Override the panel config at build time,
e.g. `arduino-cli compile --build-property "compiler.cpp.extra_flags=-DBIT_DEPTH=2" build/m0_display_client`.

> Reality-vs-spec flags:
> - The handoff specifies `firmware/m0/m0_display_client.ino`, but Arduino requires the sketch
>   folder name to equal the sketch name — `flash.sh` handles this via the `build/` copy.
> - `arduino-cli upload` performs the 1200 bps bootloader touch itself, so you only need to
>   double-tap reset for the first flash (or if the board is wedged).

## FeatherWing pin map

From Adafruit's Protomatter examples for the Feather M0/M4 RGB Matrix FeatherWing — **verify
against the `Adafruit_Protomatter` "simple" example** for your FeatherWing revision before
trusting it:

| Signal | Pin(s) |
|---|---|
| RGB (R1 G1 B1 R2 G2 B2) | 6, 5, 9, 11, 10, 12 |
| Address (A B C D) | A5, A4, A3, A2 |
| Clock / Latch / OE | 13 / 0 / 1 |

ATWINC1500 control pins (Feather M0 WiFi): CS 8, IRQ 7, RST 4, EN 2. Latch/OE use pins 0/1,
so `Serial1` is unavailable; USB `Serial` (the boot log) still works.

## Measured memory (real hardware)

The slot ring is sized **at boot from measured free RAM**, never hardcoded (spec §5.1,
open question 1). Per-config free RAM with the **default 4096 B safety margin** and
INDEXED16 = 560 B/slot + 3 B metadata (`capacity = (free_ram - 4096) / 563`):

| Panel config | free RAM after init | slot capacity |
|---|---|---|
| 4-bit, double-buffered | 3547 B | 0 |
| **3-bit, double-buffered (default)** | **7635 B** | **6** |
| 2-bit, double-buffered | 11739 B | 13 |
| 4-bit, single-buffered | 11739 B | 13 |

RAM breakdown (4-bit double-buffered): 20035 B free at boot → 3619 B right after
`matrix.begin()`, so **Protomatter dominates at ~16 KB**; WiFi101's buffers are static
(counted before boot) and cost only ~72 B dynamically.

**Why the 4096 B margin:** with a 1024 B margin the slot pool grew so far that `freeRam()`
went *negative* (−45, reported over an `INFO` query) — WiFi101's UDP receive path drives the
stack deep enough to collide with the heap. 4096 B keeps `INFO` free RAM healthily positive
(measured 2755 B with 0 slots; ~1275 B with 6 slots loaded after socket traffic — tight but
stable across all the validation runs).

**This corrects the spec.** §5.1 estimated ~4 KB for the panel and named WiFi101 the dominant
unknown — on real hardware it is the reverse: Protomatter dominates and WiFi101 is mostly
static, and §5.2's "~28-frame sweet spot" assumed 12–16 KB of free pool this 32 KB SAMD21
does not have. The default is `BIT_DEPTH 3` (6-frame loop) with double-buffering kept for
tear-free live DDP (answers open question 2). For a longer loop, build with `-DBIT_DEPTH=2`
(13 frames, lower color depth).

## On-hardware validation (all ✓ on a real board)

Validated on a Feather M0 + 32×32 panel joined to WiFi (`10.66.27.190`), default 3-bit build:

1. **Boot** ✓ — diagonal-rainbow fallback shows; serial prints free RAM 7635 B, slot
   capacity 6, and the dotted-quad IP after WiFi join.
2. **Live DDP** ✓ — `blitzen run --pattern plasma --target panel` renders plasma on the panel,
   the same host code path as the software sink (and, in future, WLED).
3. **Control over WiFi** ✓ — `blitzen info --target panel` returns free RAM + slot usage.
4. **Standalone loop** ✓ — `blitzen upload --target panel --asset clip.gif` stores 6 frames and
   plays them untethered after the host process exits.
5. **Preempt + resume** ✓ — a live `run` preempts the loop; ~`idle_ms` after it stops, the loop
   resumes (default idle policy; `--resume explicit` holds the last frame instead).
6. **Concurrency** ✓ — one `blitzen run --assign panel=plasma --assign localsink=scroll` drives
   the panel and a second DDP target at once. *Pending:* the same test against a real WLED array
   (none on the LAN yet) — the host path is identical.

## Resume policy (open question 5)

Both policies are implemented; default is **idle-timeout** (`RESUME_IDLE`, resume the stored
loop `idle_ms` after the last DDP frame). Switch with `blitzen upload --resume explicit` (or
`--resume idle --idle-ms N`), which sends a `CONFIG` message.
