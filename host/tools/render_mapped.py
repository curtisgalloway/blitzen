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
"""Drive a DDP display through a calibrated ledmap (from calibrate_camera).

Renders a desired image on the *physical* grid, then places each pixel into the DDP frame
via the ledmap so it lands correctly — handy for panels whose wiring a flat 2D config can't
express. Modes: ``probe`` / ``cols`` / ``rows`` (geometry checks), ``text`` (static) and
``scroll`` (marquee), using a small built-in 5x7 font.

Usage::

    python -m host.tools.render_mapped --ip 10.0.0.5 --map ledmap.json --mode scroll \\
        --text "FOUR SCORE AND SEVEN YEARS"

NOTE: the bundled FONT is a minimal 5x7 set (uppercase letters used by the demos + space).
Extend FONT for full coverage. ``--capture`` needs the optional vision extra (OpenCV).
"""

from __future__ import annotations

import argparse
import json
import time

from host.frame import Frame
from host.protocol import DDP_PORT
from host.transports.ddp import DDPTransport

# Minimal 5x7 uppercase font (rows top->bottom). Extend as needed.
FONT = {
    " ": ["00000"] * 7,
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "N": ["10001", "11001", "11001", "10101", "10011", "10011", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
}


def build_columns(msg, h):
    cols = []
    for ch in msg.upper():
        glyph = FONT.get(ch, FONT[" "])
        for cx in range(5):
            col = [0] * h
            for ry in range(7):
                if ry < h and glyph[ry][cx] == "1":
                    col[ry] = 1
            cols.append(col)
        cols.append([0] * h)  # inter-char gap
    return cols


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render through a calibrated ledmap over DDP.")
    ap.add_argument("--ip", required=True, help="DDP/WLED device IP")
    ap.add_argument("--map", default="ledmap.json", help="ledmap from calibrate_camera")
    ap.add_argument("--mode", default="scroll", choices=("probe", "cols", "rows", "text", "scroll"))
    ap.add_argument("--text", default="FOUR SCORE AND SEVEN YEARS")
    ap.add_argument("--color", default="255,170,30", help="R,G,B for text")
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--offset", type=int, default=0, help="text scroll offset (static mode)")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--capture", action="store_true", help="save verify.png (needs OpenCV)")
    args = ap.parse_args(argv)

    with open(args.map, encoding="utf-8") as f:
        m = json.load(f)
    gw, gh = m["GW"], m["GH"]
    jmap = {int(k): tuple(v) for k, v in m["map"].items()}
    n = gw * gh
    color = tuple(int(x) for x in args.color.split(","))

    def blank():
        return [[(0, 0, 0)] * gw for _ in range(gh)]

    def send(desired, tx):
        data = bytearray(n * 3)
        for j, (col, row) in jmap.items():
            if 0 <= row < gh and 0 <= col < gw:
                r, g, b = desired[row][col]
                data[j * 3], data[j * 3 + 1], data[j * 3 + 2] = r, g, b
        tx.send_live(Frame(gw, gh, data))

    def window(cols, off):
        d = blank()
        for c in range(gw):
            sc = off + c
            if 0 <= sc < len(cols):
                for r in range(gh):
                    if cols[sc][r]:
                        d[r][c] = color
        return d

    tx = DDPTransport(args.ip, DDP_PORT)
    if args.mode == "scroll":
        cols = build_columns("  " + args.text + "  ", gh)
        period = 1.0 / args.fps
        span = max(1, len(cols) - gw)
        end = time.time() + args.seconds
        while time.time() < end:
            for off in range(span):
                if time.time() >= end:
                    break
                send(window(cols, off), tx)
                time.sleep(period)
        tx.close()
        return 0

    desired = blank()
    if args.mode == "probe":
        for c in range(gw):
            desired[0][c] = (150, 0, 0)
        for r in range(gh):
            desired[r][0] = (0, 150, 0)
        desired[0][0] = (255, 255, 255)
    elif args.mode == "cols":
        pal = [(160, 0, 0), (0, 160, 0), (0, 0, 160), (150, 150, 150)]
        for r in range(gh):
            for c in range(gw):
                desired[r][c] = pal[min(len(pal) - 1, (c * len(pal)) // gw)]
    elif args.mode == "rows":
        pal = [(160, 0, 0), (0, 0, 160)]
        for r in range(gh):
            for c in range(gw):
                desired[r][c] = pal[min(len(pal) - 1, (r * len(pal)) // gh)]
    elif args.mode == "text":
        desired = window(build_columns("  " + args.text + "  ", gh), args.offset)

    end = time.time() + args.seconds
    while time.time() < end:
        send(desired, tx)
        time.sleep(0.1)

    if args.capture:
        import cv2

        cap = cv2.VideoCapture(args.cam)
        img = None
        for _ in range(8):
            ok, f = cap.read()
            if ok and f is not None:
                img = f
        cap.release()
        if img is not None:
            cv2.imwrite("verify.png", img)
            print("captured verify.png")
    tx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
