# Networked LED Display Control — Design & Implementation Spec

## 1. Goal & scope

A single host process drives multiple, heterogeneous WiFi-connected LED displays with
static and animated patterns, and is general enough to add new display types with one
adapter and no changes to pattern code.

Initial targets:

- **HUB75 panel** — Adafruit Feather M0 WiFi (SAMD21 + ATWINC1500) + RGB Matrix
  FeatherWing driving a 32×32 panel. Needs **custom thin-client firmware** (this repo).
- **WLED arrays** — one or more 8×32 addressable matrices (256 px) running **stock WLED**.
  No firmware work; we speak its native network protocol.

The system must drive all displays from one process, same pattern or different, and support
two playback modes per display: **live streaming** (host pushes every frame) and
**standalone loop** (display runs untethered after upload/config).

## 2. Core principle

**Generalization lives in the host, not the firmware.** The host is the only component that
sees all displays, so the abstraction belongs there. Do not try to make the on-device
protocol universal.

This is driven by an asymmetry between the two device classes:

| | HUB75 panel (M0) | WLED array |
|---|---|---|
| Hardware | Dumb panel; MCU does bit-plane modulation | Addressable LEDs + ESP running WLED |
| Role | Thin client **we build** | Thin client that **already exists** |
| Live frames | Custom firmware receives them | WLED already speaks several frame protocols |
| Standalone loop | We provide (slot ring + timing) | WLED provides (presets/playlists) |

Unifying at the firmware level would mean either dumbing WLED down (losing the reason to use
it) or bloating the M0 to match WLED. Instead: **unify the *live* path on one wire protocol,
and let each device's *standalone* mode use whatever it natively provides.**

## 3. System architecture

Three host-side layers, plus the two device roles.

```
  Pattern layer          render(width, height, t) -> Frame (logical row-major RGB)
        |
  Orchestrator           ticks at fps; for each target, get frame at its geometry, push
        |
  Target layer           DisplayTarget: geometry + transport adapter
        |   |
   M0Target  WLEDTarget   transports: DDP (live), M0 control proto (store/play), WLED config
        |        |
   [M0 firmware]  [stock WLED]
```

**Pattern layer.** A pattern renders into an abstract `Frame` of (w, h) RGB pixels.
- *Procedural* patterns (plasma, fire, scroll) compute per normalized `(x/w, y/h, t)` and are
  valid at any geometry — the same code fills 32×32 and 8×32.
- *Fixed-asset* patterns declare a native size and are only valid on matching geometry.
- A pattern never knows what hardware it drives.

**Target layer.** Each physical display is a `DisplayTarget` carrying its pixel geometry and a
transport adapter. Adding a new display type = one new adapter, nothing else.

**Orchestrator.** Ticks at a frame rate; for each active target, asks the scene for a frame at
that target's geometry and pushes it through the target's transport. Can drive all displays
concurrently, same or different patterns, same or different fps.

**Frame convention.** The host framebuffer is **always logical row-major RGB**. No target gets
special pixel ordering on the host side — physical remap (serpentine, panel scan) is the
device's or its config's job (see §4).

## 4. Transport protocols

### 4.1 DDP — the universal live path (all targets, including M0)

Use **DDP (Distributed Display Protocol)** over UDP port **4048** as the single live-streaming
format for every target. Teaching the M0 a small DDP receiver costs about the same as a bespoke
live-frame format would, and collapses the host's live path to one code path and one wire format.

DDP frame (verify exact flag bytes against the DDP spec + WLED's parser during implementation):

```
byte 0    flags (version + PUSH bit)
byte 1    sequence (low nibble)
byte 2    data type
byte 3    destination id (default output = 1)
byte 4-7  data offset, bytes, big-endian
byte 8-9  data length, bytes, big-endian
byte 10+  payload: raw RGB888, row-major
```

A 32×32 RGB frame is 3072 bytes and an 8×32 is 768 bytes — both fit in a single datagram, no
fragmentation. WLED's realtime **DRGB** protocol (`[protocol][timeout][R,G,B…]`) is an even
simpler fallback for the arrays; keep it available but build on DDP for generality.

### 4.2 M0 control protocol — store/play (M0 only)

The custom protocol shrinks to just what only the M0 needs: uploading frames for an untethered
loop. Suggested messages (define a 1-byte opcode header on a separate UDP port from DDP):

- `STORE  {slot, dwell_ms, encoding, palette?, payload}` — write one frame into RAM slot.
- `PLAY   {start_slot, end_slot, repeat}` — begin autonomous loop over stored slots.
- `STOP` / `CLEAR` — halt loop / free slots.
- Live frames arrive via DDP (§4.1) and **preempt** the loop; resume on a control message or
  after a configurable idle timeout.

### 4.3 WLED configuration (no protocol work)

- Enable **2D matrix** support (WLED ≥ 0.14) and declare each array's physical layout
  (dimensions + serpentine/boustrophedon) in the WLED UI. After that, realtime protocols
  address a clean logical 2D space and the host stays geometry-agnostic and row-major.
- Standalone loops for WLED arrays = WLED **presets/playlists** configured on the device and
  triggered by the host (HTTP/JSON API). We do not reimplement this.

## 5. M0 firmware spec

Thin display client. Libraries: **Adafruit_Protomatter** (panel, subclasses Adafruit_GFX) +
**WiFi101** (ATWINC1500 — **not** WiFiNINA, which targets different coprocessor boards).

### 5.1 Memory budget (32 KB SRAM — measure on the real build)

| Consumer | Estimate |
|---|---|
| Protomatter display buffer (6-bit, double-buffered) | ~6 KB (~4 KB at 4-bit) |
| WiFi101 / ATWINC driver buffers | ~5–8 KB *(heaviest; measure)* |
| Arduino core, USB, stack, heap headroom | ~4–5 KB |
| **Remaining working pool for stored frames** | **~12–16 KB** |

These are estimates. **Measure free heap on the actual build before sizing the slot ring.**

### 5.2 Frame encoding for stored loops (32×32)

| Encoding | Bytes/frame | Frames in ~14 KB | Notes |
|---|---|---|---|
| RGB888 raw | 3072 | ~4 | avoid for storage |
| RGB565 | 2048 | ~7 | |
| Indexed 256-color (+768 B palette) | 1024 | ~13 | |
| **Indexed 16-color** | **512** | **~28** | **sweet spot** |
| 1-bit / 2-color | 128 | ~110 | |

Palette-indexed is the recommended stored format; a 16-color palette yields a real ~28-frame
loop in RAM with little visible loss at this panel's effective depth. Live DDP frames stay full
RGB888 (no RAM ceiling on the live path — one frame in flight). Static content known at build
time can live in flash as a `const` array (SAMD21 flash is memory-mapped, directly addressable;
~200 KB free holds hundreds of frames) — flash for static, RAM slot ring for host-uploaded loops.

### 5.3 Behavior

- Double-buffered Protomatter; swap on frame complete.
- DDP live frame → decode → blit → swap, preempting any running loop.
- `STORE` → decode-and-pack into slot ring; `PLAY` → walk slots honoring per-frame `dwell_ms`.
- Bake a couple of self-contained fallback patterns into firmware for the host-disconnected,
  nothing-stored state.

## 6. Host spec

Python (per project convention). Sketch of the interfaces — Claude Code should firm these up:

```python
class Frame:                      # logical row-major RGB888 buffer
    width: int; height: int; data: bytearray

class Pattern(Protocol):
    procedural: bool              # True -> any geometry; False -> fixed
    native_size: tuple|None       # required if not procedural
    def render(self, w: int, h: int, t: float) -> Frame: ...

class Transport(Protocol):
    def send_live(self, frame: Frame) -> None: ...          # DDP

class DisplayTarget:
    name: str
    width: int; height: int
    transport: Transport
    # M0Target also: store(slot, frame, dwell_ms, encoding), play(...), stop()
    # WLEDTarget also: select_preset(id) / start_playlist(id) via WLED HTTP API

class Orchestrator:
    targets: list[DisplayTarget]
    def assign(self, target, pattern): ...   # validates geometry for fixed patterns
    def run(self, fps: float): ...           # tick loop, push to all live targets
```

Transports to implement: `DDPTransport` (live, shared by M0 + WLED), `M0Control`
(store/play, UDP), `WLEDControl` (preset/playlist trigger, HTTP). The palette encoder
(arbitrary image → 16-color palette + packed indices) lives host-side, used only by the M0
store path.

## 7. Non-goals

- Reflashing or forking WLED. We use it as-is.
- Reimplementing WLED's standalone playback — use presets/playlists.
- On-device procedural generation beyond stored/fallback loops.
- Scanout/panel electrical bring-up — the FeatherWing + Protomatter handle the panel.

## 8. Open questions — resolve by measuring, not guessing

1. Actual free SRAM on the built M0 firmware → sets slot-ring capacity.
2. WiFi101 buffer footprint (the dominant unknown in the budget).
3. Confirm WLED version on the arrays supports 2D matrix config.
4. Exact DDP flag/type bytes as WLED's parser expects them.
5. Loop-resume policy after a live frame: explicit message vs. idle timeout (pick one, make it
   configurable).

## 9. Suggested build order

1. Host `Frame` + one procedural pattern + `DDPTransport`; prove against a **WLED array first**
   (stock firmware = fastest path to pixels on glass, validates the live path end to end).
2. M0 firmware: WiFi join + Protomatter + DDP live receive. Same host code now drives the panel.
3. M0 store/play slot ring + `M0Control` + host palette encoder; validate untethered loop.
4. `WLEDControl` preset/playlist trigger; `Orchestrator` driving all displays concurrently.
