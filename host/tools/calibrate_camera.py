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
"""Camera-based pixel-mapping calibration for a DDP display (e.g. WLED).

Some matrices (tiled 8x8 sub-panels, odd serpentine, chained panels) don't map cleanly
from a flat 2D config, so logical row-major frames come out scrambled. This calibrates the
*actual* DDP->physical pipeline as a black box: it lights each LED in turn, finds its
position with a webcam, and writes a ledmap (DDP index -> physical grid (col,row)). Render
through that map with :mod:`host.tools.render_mapped`.

One LED at a time is robust to bloom/auto-exposure (a single lit dot is always a clean
blob). Requires the optional vision extra: ``uv sync --extra vision`` (OpenCV + NumPy).

Usage::

    python -m host.tools.calibrate_camera --ip 10.0.0.5 --gw 64 --gh 8 --cam 0

Prereqs: the WLED device must already be set for ``gw*gh`` LEDs; aim a webcam so the whole
panel is framed, in focus, on a dark background; keep camera + panel still during the scan.
"""

from __future__ import annotations

import argparse
import json
import time

import cv2
import numpy as np

from host.frame import Frame
from host.protocol import DDP_PORT
from host.transports.ddp import DDPTransport


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Webcam pixel-mapping calibration for a DDP panel.")
    ap.add_argument("--ip", required=True, help="DDP/WLED device IP")
    ap.add_argument("--cam", type=int, default=0, help="OpenCV camera index")
    ap.add_argument("--gw", type=int, default=32, help="logical grid width")
    ap.add_argument("--gh", type=int, default=8, help="logical grid height")
    ap.add_argument("--out", default="ledmap.json", help="output ledmap path")
    ap.add_argument("--threshold", type=float, default=60.0, help="min peak brightness to accept")
    args = ap.parse_args(argv)
    gw, gh, n = args.gw, args.gh, args.gw * args.gh

    cap = cv2.VideoCapture(args.cam)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    tx = DDPTransport(args.ip, DDP_PORT)

    def onehot(j):
        d = bytearray(n * 3)
        if j >= 0:
            d[j * 3] = d[j * 3 + 1] = d[j * 3 + 2] = 255
        return Frame(gw, gh, d)

    def grab():
        img = None
        for _ in range(5):  # flush buffered frames; keep a fresh one
            ok, f = cap.read()
            if ok and f is not None:
                img = f
        return img

    for _ in range(3):
        tx.send_live(onehot(-1))
    time.sleep(0.3)
    allon = grab()  # for the debug overlay

    cents = {}
    for j in range(n):
        for _ in range(2):
            tx.send_live(onehot(j))
        time.sleep(0.06)
        g = cv2.GaussianBlur(cv2.cvtColor(grab(), cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 2.0)
        _, mx, _, loc = cv2.minMaxLoc(g)
        if mx > args.threshold:
            cents[j] = (float(loc[0]), float(loc[1]))

    tx.send_live(onehot(-1))
    cap.release()
    tx.close()
    print(f"detected {len(cents)}/{n} LEDs")
    if len(cents) < n * 0.9:
        print("warning: many LEDs undetected — improve framing/brightness and re-run")

    idxs = sorted(cents)
    pts = np.array([cents[k] for k in idxs])
    centered = pts - pts.mean(0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    proj_long = centered @ vt[0]
    proj_short = centered @ vt[1]

    def quant(v, count):
        lo, hi = float(v.min()), float(v.max())
        return np.clip(np.round((v - lo) / (hi - lo) * (count - 1)).astype(int), 0, count - 1)

    if gw >= gh:
        cols, rows = quant(proj_long, gw), quant(proj_short, gh)
    else:
        cols, rows = quant(proj_short, gw), quant(proj_long, gh)

    jmap = {str(k): [int(cols[i]), int(rows[i])] for i, k in enumerate(idxs)}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"GW": gw, "GH": gh, "map": jmap}, f)
    print(f"wrote {args.out} ({len(jmap)} entries)")

    if allon is not None:
        for i, k in enumerate(idxs):
            cx, cy = cents[k]
            cv2.circle(allon, (int(cx), int(cy)), 2, (0, 0, 255), -1)
        cv2.imwrite("calib_grid.png", allon)
        print("wrote calib_grid.png (detected-centroid overlay)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
