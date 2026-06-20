# Claude Code handoff prompt

> Paste the block below into Claude Code from the root of a fresh repo, with
> `led_control_design.md` present in the repo. Adjust the device IPs/SSID notes as needed.

---

Build a networked LED display control system per the spec in `led_control_design.md`. Read
that file first and treat it as the source of truth for architecture and rationale; this prompt
covers deliverables, structure, and how to validate.

**System summary:** one Python host process drives heterogeneous WiFi LED displays. Two device
classes: (1) an Adafruit Feather M0 WiFi + RGB Matrix FeatherWing driving a 32×32 HUB75 panel,
needing custom Arduino/C++ firmware we write; (2) stock-firmware WLED arrays (8×32, 256 px) we
control over their native network protocol. The live-streaming path is unified on DDP for all
targets; standalone playback uses each device's native mechanism (M0 slot ring; WLED presets).

## Deliverables & layout

```
/firmware/m0/            Arduino C++ sketch + libs notes
  m0_display_client.ino  WiFi join, Protomatter, DDP live receive, store/play slot ring
  README.md              build/flash steps, library versions, measured free-RAM number
/host/                   Python package
  frame.py               Frame (logical row-major RGB888)
  patterns/              Pattern protocol + procedural examples (plasma/scroll) + fixed-asset loader
  transports/
    ddp.py               DDPTransport (live, shared by M0 + WLED)
    m0_control.py        STORE/PLAY/STOP over UDP
    wled_control.py      preset/playlist trigger via WLED HTTP/JSON API
  encoder.py             arbitrary image -> 16-color palette + packed indices (M0 store path)
  targets.py             DisplayTarget, M0Target, WLEDTarget
  orchestrator.py        tick loop, geometry validation, concurrent drive
  cli.py                 run a pattern on named target(s) at a given fps
  tests/
/README.md               quickstart: bring up a WLED array first, then the M0
```

Language/library constraints (from the spec — do not substitute without flagging):
- Firmware: **Adafruit_Protomatter** + **WiFi101** (ATWINC1500). **Not** WiFiNINA. Pin the
  library versions in the firmware README.
- Host: Python 3.11+, standard library sockets where possible; `Pillow` allowed for the encoder.

## Hard constraints

- **Host holds the generality, firmware stays thin.** Don't push display-type logic into the M0.
- **Do not reflash, fork, or reconfigure-beyond-2D-matrix the WLED devices.** Control them only
  over the network. WLED standalone = its own presets/playlists, triggered, not reimplemented.
- **Host framebuffers are always logical row-major RGB.** No serpentine/scan remap on the host;
  that's the device or WLED-config's job.
- **Measure M0 SRAM, don't assume.** Before sizing the slot ring, print free heap on the real
  build and put that number in the firmware README. The slot-ring capacity is computed from the
  measured pool and the chosen encoding, not hardcoded optimistically.

## Build order (validate each step before the next)

1. **Host live path against a WLED array first.** `Frame` + one procedural pattern +
   `DDPTransport`, driving a stock WLED 8×32. This is the fastest path to real pixels and proves
   the live path end to end. Confirm the array has WLED ≥ 0.14 with 2D matrix configured.
2. **M0 live receive.** Firmware: WiFi join + Protomatter + DDP receiver. The *same* host code
   from step 1 must now drive the 32×32 panel with no host-side special-casing.
3. **M0 standalone loop.** Slot ring + `STORE`/`PLAY`/`STOP` + host `encoder.py` (16-color). Upload
   a loop, confirm it runs untethered (host disconnected), confirm a live DDP frame preempts it
   and it resumes per the configured policy.
4. **Concurrency.** `WLEDControl` preset/playlist trigger + `Orchestrator` driving the panel and
   the array(s) at once — same pattern and different patterns.

## Acceptance criteria

- One `cli.py` invocation can drive: the M0 panel live, a WLED array live, and both concurrently.
- A 16-color animation uploads to the M0 and loops standalone with correct per-frame dwell.
- Adding a hypothetical new display type requires only a new transport/target, no pattern changes
  (demonstrate with a stub target or a unit test asserting the seam).
- Procedural patterns render correctly at both 32×32 and 8×32 from the same code.
- Firmware README states the measured free-RAM figure and the resulting slot count.

## Working agreement

- Resolve the spec's §8 open questions empirically and record answers in the relevant README.
- If hardware to test against isn't available in your environment, build to the protocols, add
  tests/mocks for the host, and clearly mark the on-hardware validation steps as TODO for me to
  run — don't fake passing hardware tests.
- Flag any point where reality contradicts the spec rather than silently diverging.

Start by reading `led_control_design.md`, then propose the repo skeleton and step-1 plan before
writing the bulk of the code.
