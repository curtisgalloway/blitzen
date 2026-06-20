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
"""Discover WLED devices on the local network by probing their JSON API.

Handy when a freshly-provisioned WLED board doesn't surface its IP (e.g. the web
installer's Wi-Fi step bounced). Scans the local /24 for hosts answering
``/json/info`` with ``brand == "WLED"``.

    python -m host.tools.find_wled            # auto-detect this host's /24
    python -m host.tools.find_wled --subnet 10.66.27
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import socket
import urllib.request


def local_subnet() -> str:
    """Return this host's /24 prefix (e.g. ``"10.66.27."``)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # no traffic sent; just picks the egress interface
        ip = sock.getsockname()[0]
    finally:
        sock.close()
    return ip.rsplit(".", 1)[0] + "."


def _probe(prefix: str, i: int):
    ip = prefix + str(i)
    try:
        with urllib.request.urlopen("http://" + ip + "/json/info", timeout=0.6) as resp:
            info = json.loads(resp.read().decode("utf-8", "replace"))
        if isinstance(info, dict) and str(info.get("brand", "")).upper() == "WLED":
            return (ip, info.get("ver"), info.get("name"))
    except Exception:
        return None
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Find WLED devices on the local /24.")
    parser.add_argument("--subnet", help='prefix like "10.66.27" (default: auto-detect)')
    args = parser.parse_args(argv)
    prefix = (args.subnet.rstrip(".") + ".") if args.subnet else local_subnet()

    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        for result in pool.map(lambda i: _probe(prefix, i), range(1, 255)):
            if result:
                found.append(result)

    for ip, ver, name in sorted(found):
        print(f"WLED {ver}\t{name}\t{ip}")
    if not found:
        print("no WLED devices found on " + prefix + "0/24")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
