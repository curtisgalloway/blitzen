# Copyright 2026 The Blitzen Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""``blitzen`` command-line entry point.

Targets live in a TOML config (``devices.toml`` by default). One invocation can drive the
M0 panel live, a WLED array live, or both at once; other subcommands upload a standalone M0
loop, trigger WLED presets/playlists, and probe devices.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from typing import Dict, List, Optional, Tuple

from host.orchestrator import Orchestrator
from host.patterns import get_pattern
from host.patterns.asset import load_asset
from host.protocol import DDP_PORT, M0_CONTROL_PORT, ResumePolicy
from host.targets import DisplayTarget, M0Target, WLEDTarget
from host.transports.ddp import DDPTransport
from host.transports.m0_control import M0Error
from host.transports.wled_control import WLEDError

_DEFAULT_CONFIG_CANDIDATES = ("devices.toml", os.path.join("host", "devices.toml"))


class CLIError(Exception):
    """A user-facing error (bad target name, wrong target type, etc.)."""


# -- config ----------------------------------------------------------------------------


def _resolve_config(path: Optional[str]) -> str:
    if path:
        if not os.path.exists(path):
            raise CLIError(f"config file not found: {path}")
        return path
    for candidate in _DEFAULT_CONFIG_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise CLIError(
        "no device config found. Copy host/devices.example.toml to devices.toml, "
        "or pass --config PATH."
    )


def _load_targets(path: Optional[str]) -> Dict[str, dict]:
    resolved = _resolve_config(path)
    with open(resolved, "rb") as handle:
        config = tomllib.load(handle)
    targets = config.get("targets", {})
    if not targets:
        raise CLIError(f"no [targets.*] entries in {resolved}")
    return targets


def _target_cfg(targets: Dict[str, dict], name: str) -> dict:
    try:
        return targets[name]
    except KeyError:
        available = ", ".join(sorted(targets))
        raise CLIError(f"no target named {name!r}; available: {available}") from None


def build_target(name: str, cfg: dict) -> DisplayTarget:
    """Construct a target from its config dict."""
    try:
        ttype = cfg["type"]
        width = int(cfg["width"])
        height = int(cfg["height"])
    except KeyError as exc:
        raise CLIError(f"target {name!r} missing required field {exc}") from None
    host = cfg.get("host")
    ddp_port = int(cfg.get("ddp_port", DDP_PORT))
    if ttype in ("wled", "m0", "ddp") and not host:
        raise CLIError(f"target {name!r} of type {ttype!r} requires a host")
    if ttype == "wled":
        return WLEDTarget(
            name,
            width,
            height,
            host,
            ddp_port=ddp_port,
            http_port=int(cfg.get("http_port", 80)),
        )
    if ttype == "m0":
        return M0Target(
            name,
            width,
            height,
            host,
            ddp_port=ddp_port,
            control_port=int(cfg.get("control_port", M0_CONTROL_PORT)),
        )
    if ttype == "ddp":
        return DisplayTarget(name, width, height, DDPTransport(host, ddp_port))
    raise CLIError(f"target {name!r} has unknown type {ttype!r} (expected wled|m0|ddp)")


# -- run -------------------------------------------------------------------------------


def _parse_assignments(args) -> List[Tuple[str, str, Optional[float]]]:
    """Resolve --assign / --target+--pattern into (target, pattern, fps) tuples."""
    assigns: List[Tuple[str, str, Optional[float]]] = []
    if args.assign:
        for spec in args.assign:
            name, sep, rest = spec.partition("=")
            if not sep or not rest:
                raise CLIError(f"--assign expects NAME=PATTERN[@FPS], got {spec!r}")
            pattern, _, fps_str = rest.partition("@")
            fps = float(fps_str) if fps_str else None
            assigns.append((name, pattern, fps))
    elif args.pattern and args.target:
        for name in args.target:
            assigns.append((name, args.pattern, None))
    else:
        raise CLIError("run needs --pattern and --target, or one or more --assign")
    return assigns


def cmd_run(args) -> int:
    targets_cfg = _load_targets(args.config)
    assigns = _parse_assignments(args)
    built: Dict[str, DisplayTarget] = {}

    def target(name: str) -> DisplayTarget:
        if name not in built:
            built[name] = build_target(name, _target_cfg(targets_cfg, name))
        return built[name]

    orch = Orchestrator()
    for name, pattern_name, fps in assigns:
        orch.assign(target(name), get_pattern(pattern_name), fps)

    summary = ", ".join(f"{n}:{p}" + (f"@{f}fps" if f else "") for n, p, f in assigns)
    tail = f" for {args.duration}s" if args.duration else ""
    print(f"driving {summary} at {args.fps} fps{tail}")
    try:
        orch.run(fps=args.fps, duration=args.duration)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        orch.close()
    return 0


# -- upload ----------------------------------------------------------------------------


def _require_m0(name: str, cfg: dict) -> M0Target:
    target = build_target(name, cfg)
    if not isinstance(target, M0Target):
        raise CLIError(f"target {name!r} is not an m0 target")
    return target


def cmd_upload(args) -> int:
    targets_cfg = _load_targets(args.config)
    target = _require_m0(args.target, _target_cfg(targets_cfg, args.target))
    asset = load_asset(args.asset, target_size=target.geometry)
    try:
        if args.resume:
            policy = (
                ResumePolicy.IDLE_TIMEOUT
                if args.resume == "idle"
                else ResumePolicy.EXPLICIT
            )
            target.config(policy, args.idle_ms)
        count = target.upload_loop(
            asset, start_slot=args.start_slot, dwell_ms=args.dwell, repeat=args.repeat
        )
    finally:
        # Keep the device playing; only release the host's sockets.
        target.control.close()
        target.transport.close()
    last = args.start_slot + count - 1
    print(f"uploaded {count} frame(s) to slots {args.start_slot}..{last}; loop playing")
    return 0


# -- wled ------------------------------------------------------------------------------


def cmd_wled(args) -> int:
    targets_cfg = _load_targets(args.config)
    target = build_target(args.target, _target_cfg(targets_cfg, args.target))
    if not isinstance(target, WLEDTarget):
        raise CLIError(f"target {args.target!r} is not a wled target")
    if args.preset is not None:
        target.select_preset(args.preset)
        print(f"{args.target}: loaded preset {args.preset}")
    elif args.playlist is not None:
        target.start_playlist(args.playlist)
        print(f"{args.target}: started playlist {args.playlist}")
    elif args.on:
        target.set_power(True, args.brightness)
        print(f"{args.target}: on")
    elif args.off:
        target.set_power(False)
        print(f"{args.target}: off")
    else:
        raise CLIError("wled needs one of --preset/--playlist/--on/--off")
    return 0


# -- info / probe ----------------------------------------------------------------------


def cmd_info(args) -> int:
    targets_cfg = _load_targets(args.config)
    target = _require_m0(args.target, _target_cfg(targets_cfg, args.target))
    try:
        info = target.info()
    finally:
        target.close()
    print(
        f"{args.target}: free_ram={info['free_ram']} B  "
        f"slots_used={info['slots_used']}/{info['slot_capacity']}"
    )
    return 0


def cmd_probe(args) -> int:
    targets_cfg = _load_targets(args.config)
    target = build_target(args.target, _target_cfg(targets_cfg, args.target))
    if not isinstance(target, WLEDTarget):
        raise CLIError(f"target {args.target!r} is not a wled target")
    result = target.probe()
    ok = "OK" if result["version_ok"] else "TOO OLD (need >= 0.14)"
    twod = "yes" if result["is_2d"] else "NO (configure 2D matrix in WLED)"
    print(f"{args.target}: WLED {result['version']} [{ok}]  2D matrix: {twod}")
    if result["matrix"]:
        print(f"  matrix: {result['matrix']}")
    return 0


# -- parser ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blitzen", description="Networked LED display control."
    )
    parser.add_argument("--config", help="device config TOML (default: ./devices.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="drive target(s) live with a pattern")
    run.add_argument("--pattern", help="pattern name for all --target(s)")
    run.add_argument(
        "--target", action="append", default=[], help="target name (repeatable)"
    )
    run.add_argument(
        "--assign",
        action="append",
        default=[],
        help="per-target assignment NAME=PATTERN[@FPS] (repeatable)",
    )
    run.add_argument(
        "--fps", type=float, default=30.0, help="default frame rate (default 30)"
    )
    run.add_argument(
        "--duration", type=float, help="seconds to run (default: until Ctrl-C)"
    )
    run.set_defaults(func=cmd_run)

    upload = sub.add_parser(
        "upload", help="encode an asset and upload an M0 standalone loop"
    )
    upload.add_argument("--target", required=True, help="m0 target name")
    upload.add_argument("--asset", required=True, help="image/GIF path")
    upload.add_argument("--start-slot", type=int, default=0)
    upload.add_argument(
        "--dwell", type=int, help="per-frame dwell ms (default: asset timing)"
    )
    upload.add_argument("--repeat", type=int, default=0, help="loop count, 0 = forever")
    upload.add_argument(
        "--resume", choices=("idle", "explicit"), help="loop-resume policy"
    )
    upload.add_argument(
        "--idle-ms", type=int, default=2000, help="idle-resume timeout ms"
    )
    upload.set_defaults(func=cmd_upload)

    wled = sub.add_parser("wled", help="trigger a WLED preset/playlist or power")
    wled.add_argument("--target", required=True, help="wled target name")
    wled.add_argument("--preset", type=int, help="load preset id")
    wled.add_argument("--playlist", type=int, help="start playlist (preset) id")
    wled.add_argument("--on", action="store_true", help="turn on")
    wled.add_argument("--off", action="store_true", help="turn off")
    wled.add_argument(
        "--brightness", type=int, help="master brightness 0..255 (with --on)"
    )
    wled.set_defaults(func=cmd_wled)

    info = sub.add_parser("info", help="query M0 free RAM / slot usage")
    info.add_argument("--target", required=True, help="m0 target name")
    info.set_defaults(func=cmd_info)

    probe = sub.add_parser("probe", help="check WLED version and 2D-matrix config")
    probe.add_argument("--target", required=True, help="wled target name")
    probe.set_defaults(func=cmd_probe)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        CLIError,
        M0Error,
        WLEDError,
        FileNotFoundError,
        ValueError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
