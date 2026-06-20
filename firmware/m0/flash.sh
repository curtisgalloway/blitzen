#!/usr/bin/env bash
# Copyright 2026 The Blitzen Authors
# SPDX-License-Identifier: Apache-2.0
#
# Generate config.h from secrets.yaml, compile, and upload the M0 sketch.
# Usage:  firmware/m0/flash.sh [SERIAL_PORT]
# (port defaults to the first /dev/cu.usbmodem*; arduino-cli auto-enters the bootloader)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="$REPO/build/m0_display_client"
FQBN="adafruit:samd:adafruit_feather_m0"

mkdir -p "$BUILD"
cp "$HERE/m0_display_client.ino" "$BUILD/"
python3 "$HERE/gen_config.py" --out "$BUILD/config.h"

arduino-cli compile --fqbn "$FQBN" "$BUILD"

PORT="${1:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [ -z "$PORT" ]; then
  echo "no /dev/cu.usbmodem* port found (double-tap reset to enter bootloader)" >&2
  exit 1
fi
echo "uploading to $PORT"
arduino-cli upload -p "$PORT" --fqbn "$FQBN" "$BUILD"
