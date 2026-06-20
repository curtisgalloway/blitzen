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
"""WLED standalone control over its native HTTP/JSON API.

We never reflash or reimplement WLED (design spec section 7). Standalone loops are WLED
presets/playlists configured on the device; the host just *triggers* them by id. The live
path for WLED is plain DDP, same as the M0 — this module is only the standalone trigger
plus a one-shot capability probe.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple


class WLEDError(Exception):
    """The WLED device returned an unexpected response."""


def _parse_version(text: str) -> Tuple[int, ...]:
    """Parse a leading dotted-int version (``"0.14.0-b1"`` -> ``(0, 14, 0)``)."""
    parts = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


class WLEDControl:
    """Trigger WLED presets/playlists and probe device capabilities via HTTP/JSON."""

    #: Minimum WLED version with 2D-matrix support (design spec section 4.3).
    MIN_2D_VERSION = (0, 14)

    def __init__(
        self,
        host: str,
        port: int = 80,
        *,
        timeout: float = 2.0,
        urlopen: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        # Injectable for tests; defaults to the stdlib opener (no third-party HTTP dep).
        self._urlopen = urlopen or urllib.request.urlopen
        self.base = f"http://{host}" if port == 80 else f"http://{host}:{port}"

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        with self._urlopen(req, timeout=self.timeout) as resp:
            body = resp.read()
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WLEDError(f"invalid JSON from {self.base}{path}: {exc}") from exc

    # -- standalone triggers -----------------------------------------------------------

    def set_state(self, state: dict) -> dict:
        """POST a partial state object to ``/json/state``."""
        return self._request("POST", "/json/state", state)

    def select_preset(self, preset_id: int) -> dict:
        """Load saved preset ``preset_id`` (begins its standalone effect)."""
        return self.set_state({"ps": int(preset_id)})

    def start_playlist(self, playlist_id: int) -> dict:
        """Start a saved playlist. In WLED a playlist is stored as a preset, so triggering
        it is loading that preset id."""
        return self.set_state({"ps": int(playlist_id)})

    def set_power(self, on: bool = True, brightness: Optional[int] = None) -> dict:
        """Turn the array on/off and optionally set master brightness (0..255)."""
        state: Dict[str, Any] = {"on": bool(on)}
        if brightness is not None:
            state["bri"] = int(brightness)
        return self.set_state(state)

    # -- capability probe --------------------------------------------------------------

    def get_info(self) -> dict:
        """Return the raw ``/json/info`` document."""
        return self._request("GET", "/json/info")

    def probe(self) -> dict:
        """Check WLED version and 2D-matrix config (spec open question 3).

        Returns ``{version, version_ok, is_2d, matrix, raw}``. ``version_ok`` is True when
        the firmware is >= 0.14; ``is_2d`` is True when a matrix layout is reported.
        """
        info = self.get_info()
        version = str(info.get("ver", ""))
        version_ok = _parse_version(version) >= self.MIN_2D_VERSION
        matrix = None
        leds = info.get("leds")
        if isinstance(leds, dict) and isinstance(leds.get("matrix"), dict):
            matrix = leds["matrix"]
        return {
            "version": version,
            "version_ok": version_ok,
            "is_2d": matrix is not None,
            "matrix": matrix,
            "raw": info,
        }
