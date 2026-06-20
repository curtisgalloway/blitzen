<!--
Copyright 2026 The Blitzen Authors
SPDX-License-Identifier: Apache-2.0
-->

# Blitzen M0 firmware

Thin display client for an **Adafruit Feather M0 WiFi** (SAMD21 + ATWINC1500) with an
**RGB Matrix FeatherWing** driving a **32×32 HUB75** panel. It joins WiFi, renders live
DDP frames, and plays a host-uploaded 16-color loop untethered. All the generality lives
in the host (see `../../led_control_design.md` §2); this firmware stays thin on purpose.

## Libraries (pin these)

Install via Library Manager / `arduino-cli`. Record the **exact** versions you build with
in the table — these are the intended pins; bump only deliberately.

| Library | Pinned version | Notes |
|---|---|---|
| Adafruit Protomatter | `1.6.x` | HUB75 driver; subclasses Adafruit_GFX |
| Adafruit GFX Library | `1.11.x` | pulled in by Protomatter |
| WiFi101 | `0.16.x` | **ATWINC1500** — do **not** use WiFiNINA |
| Adafruit SAMD Boards | `1.7.x` | board package for the Feather M0 |

> `TODO (on hardware): replace the x's with the versions you actually compiled against.`

## Build & flash (arduino-cli)

```bash
# one-time: board package + libraries
arduino-cli config add board_manager.additional_urls \
  https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli core update-index
arduino-cli core install adafruit:samd
arduino-cli lib install "Adafruit Protomatter" "Adafruit GFX Library" "WiFi101"

# secrets
cp config.h.example config.h        # then edit WIFI_SSID / WIFI_PASS

# Arduino requires the sketch folder name to match the .ino name. This repo keeps the
# handoff's firmware/m0/m0_display_client.ino path, so build via a matching-name copy:
mkdir -p /tmp/m0_display_client
cp m0_display_client.ino config.h /tmp/m0_display_client/
arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m0 /tmp/m0_display_client
arduino-cli upload  -p /dev/cu.usbmodemXXXX \
  --fqbn adafruit:samd:adafruit_feather_m0 /tmp/m0_display_client

# watch the boot log (free RAM + slot capacity print here)
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200
```

> Reality-vs-spec flag: the handoff specifies `firmware/m0/m0_display_client.ino`, but the
> Arduino toolchain requires the sketch's folder name to equal the sketch name. The
> matching-name copy above is the workaround; alternatively open the file in the Arduino IDE
> and let it create the wrapping folder.

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

## Measured memory (fill in from a real build)

The slot ring is sized **at boot from measured free RAM**, never hardcoded (spec §5.1,
open question 1). The sketch prints both numbers; record them here.

```
free RAM after init      = TODO  bytes   (open question 1; WiFi101 buffers dominate, Q2)
slot capacity (frames)   = TODO

capacity = (free_ram_after_init - 4096 margin) / 563
           where 563 = 560 bytes/slot (48 palette + 512 packed 4-bit indices) + 3 metadata
```

Bit depth is `BIT_DEPTH 4` (≈4 KB panel buffer). Raising it to 5–6 improves color depth and
reduces the slot pool — re-measure if you change it.

## On-hardware validation checklist (run by the operator)

1. **Boot**: panel shows the diagonal-rainbow fallback; serial prints the IP, free RAM, and
   slot capacity. → record the two numbers above.
2. **Live (step 2 of the build order)**: from the host,
   `blitzen run --pattern plasma --target panel` — the panel shows plasma, driven by the
   *same* host code that drives WLED.
3. **Standalone (step 3)**: `blitzen upload --target panel --asset clip.gif` then unplug the
   host — the loop keeps running. Send a live frame → it preempts; stop → it resumes per the
   `--resume` policy (default idle-timeout).
4. **INFO**: `blitzen info --target panel` reports the same free-RAM / slot figures over the
   wire.

## Resume policy (open question 5)

Both policies are implemented; default is **idle-timeout** (`RESUME_IDLE`, resume the stored
loop `idle_ms` after the last DDP frame). Switch with `blitzen upload --resume explicit` (or
`--resume idle --idle-ms N`), which sends a `CONFIG` message.
