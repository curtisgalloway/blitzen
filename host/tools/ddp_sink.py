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
"""A software DDP receiver — a virtual display for hardware-free validation.

Binds a UDP port, reassembles DDP frames (using the same :class:`DDPReassembler` the M0
firmware mirrors), and previews them as truecolor half-blocks in the terminal (or dumps a
PNG). Lets the whole live path be exercised end to end before any real pixels exist::

    python -m host.tools.ddp_sink --geometry 32x32 &
    blitzen run --pattern plasma --target localsink --config host/devices.example.toml
"""

from __future__ import annotations

import argparse
import socket
import sys
from typing import Optional

from host.frame import Frame
from host.protocol import DDP_PORT
from host.transports.ddp import DDPReassembler

# Two vertically-stacked pixels per character cell: fg = top, bg = bottom.
_HALF_BLOCK = "▀"  # upper half block
_RESET = "\x1b[0m"
_CLEAR_HOME = "\x1b[2J\x1b[H"


def frame_to_ansi(frame: Frame) -> str:
    """Render a frame as ANSI truecolor half-blocks (one cell = two stacked pixels)."""
    lines = []
    for y in range(0, frame.height, 2):
        cells = []
        for x in range(frame.width):
            tr, tg, tb = frame.get_pixel(x, y)
            if y + 1 < frame.height:
                br, bg, bb = frame.get_pixel(x, y + 1)
            else:
                br, bg, bb = 0, 0, 0
            cells.append(
                f"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m{_HALF_BLOCK}"
            )
        lines.append("".join(cells) + _RESET)
    return "\n".join(lines)


def _parse_geometry(text: str) -> tuple:
    try:
        w_str, h_str = text.lower().split("x")
        return int(w_str), int(h_str)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"geometry must be WxH, got {text!r}"
        ) from None


def run_sink(
    width: int,
    height: int,
    *,
    bind: str = "0.0.0.0",
    port: int = DDP_PORT,
    once: bool = False,
    png: Optional[str] = None,
    clear: bool = True,
    out=sys.stdout,
) -> Optional[Frame]:
    """Receive DDP frames until interrupted (or one frame if ``once``).

    Returns the last completed :class:`Frame` (useful in tests), or None.
    """
    expected = width * height * 3
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind, port))
    reassembler = DDPReassembler()
    last: Optional[Frame] = None
    print(f"DDP sink listening on {bind}:{port} for {width}x{height} frames", file=out)
    try:
        while True:
            packet, _addr = sock.recvfrom(65535)
            payload = reassembler.feed(packet)
            if payload is None:
                continue
            if len(payload) != expected:
                print(
                    f"warning: got {len(payload)} bytes, expected {expected} "
                    f"for {width}x{height}",
                    file=out,
                )
                continue
            last = Frame(width, height, bytearray(payload))
            if png:
                from PIL import Image

                Image.frombytes("RGB", (width, height), payload).save(png)
            else:
                if clear:
                    out.write(_CLEAR_HOME)
                out.write(frame_to_ansi(last) + "\n")
                out.flush()
            if once:
                return last
    except KeyboardInterrupt:
        print("\nsink stopped", file=out)
        return last
    finally:
        sock.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Software DDP sink (virtual display).")
    parser.add_argument(
        "--geometry", type=_parse_geometry, default=(32, 32), help="WxH (default 32x32)"
    )
    parser.add_argument(
        "--bind", default="0.0.0.0", help="bind address (default 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=DDP_PORT, help=f"UDP port (default {DDP_PORT})"
    )
    parser.add_argument(
        "--once", action="store_true", help="exit after one complete frame"
    )
    parser.add_argument(
        "--png", help="write each frame to this PNG path instead of the terminal"
    )
    parser.add_argument(
        "--no-clear",
        dest="clear",
        action="store_false",
        help="do not clear the screen between frames",
    )
    args = parser.parse_args(argv)
    width, height = args.geometry
    run_sink(
        width,
        height,
        bind=args.bind,
        port=args.port,
        once=args.once,
        png=args.png,
        clear=args.clear,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
