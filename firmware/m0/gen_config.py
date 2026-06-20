#!/usr/bin/env python3
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
"""Generate the M0 build-time config.h from secrets.yaml.

The Arduino sketch needs C #defines, so this bridges the human-friendly secrets.yaml into
the build's config.h. Uses PyYAML if available, otherwise a minimal flat key:value parser
(quote any value containing ':' or '#').
"""

from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_DEFAULT_OUT = os.path.join(_REPO, "build", "m0_display_client", "config.h")
_DEFAULT_SECRETS = os.path.join(_HERE, "secrets.yaml")


def load_yaml(path: str) -> dict:
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except ImportError:
        pass
    data: dict = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"')
            if not quoted and " #" in value:  # strip inline comment on unquoted values
                value = value.split(" #", 1)[0].strip()
            if quoted:
                value = value[1:-1]
            data[key] = value
    return data


def c_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="secrets.yaml -> M0 config.h")
    parser.add_argument("--secrets", default=_DEFAULT_SECRETS)
    parser.add_argument("--out", default=_DEFAULT_OUT)
    args = parser.parse_args(argv)

    if not os.path.exists(args.secrets):
        print(f"error: {args.secrets} not found (copy secrets.example.yaml)", file=sys.stderr)
        return 1

    cfg = load_yaml(args.secrets)
    ssid = str(cfg.get("ssid", ""))
    password = str(cfg.get("password", ""))
    ddp_port = int(cfg.get("ddp_port", 4048))
    ctrl_port = int(cfg.get("ctrl_port", 4049))

    if not ssid or ssid.startswith("your-"):
        print("warning: ssid looks unset in secrets.yaml", file=sys.stderr)

    content = (
        "// Generated from secrets.yaml by gen_config.py -- do not edit by hand.\n"
        "#pragma once\n\n"
        f'#define WIFI_SSID "{c_escape(ssid)}"\n'
        f'#define WIFI_PASS "{c_escape(password)}"\n\n'
        f"#define DDP_PORT_CFG {ddp_port}\n"
        f"#define CTRL_PORT_CFG {ctrl_port}\n"
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(content)
    # Print SSID/ports only -- never echo the password.
    print(f"wrote {args.out} (ssid={ssid!r}, ddp_port={ddp_port}, ctrl_port={ctrl_port})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
