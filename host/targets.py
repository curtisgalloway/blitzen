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
"""Target layer: a physical display = geometry + a transport (+ optional standalone API).

Adding a new display type means adding one class here plus its transport — pattern and
orchestrator code never change. :class:`StubTarget` exists to prove exactly that seam.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from host.encoder import encode_frame
from host.frame import Frame
from host.patterns.asset import AssetPattern
from host.protocol import DDP_PORT, M0_CONTROL_PORT, Encoding, ResumePolicy
from host.transports.base import Transport
from host.transports.ddp import DDPTransport
from host.transports.m0_control import M0Control
from host.transports.wled_control import WLEDControl


class DisplayTarget:
    """A live-drivable display: name, pixel geometry, and a live transport."""

    def __init__(
        self, name: str, width: int, height: int, transport: Transport
    ) -> None:
        self.name = name
        self.width = width
        self.height = height
        self.transport = transport

    @property
    def geometry(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def send_live(self, frame: Frame) -> None:
        if (frame.width, frame.height) != self.geometry:
            raise ValueError(
                f"frame {frame.width}x{frame.height} does not match target "
                f"{self.name} {self.width}x{self.height}"
            )
        self.transport.send_live(frame)

    def close(self) -> None:
        self.transport.close()


class M0Target(DisplayTarget):
    """The custom HUB75 panel: DDP for live frames, M0Control for the standalone loop."""

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        host: str,
        *,
        ddp_port: int = DDP_PORT,
        control_port: int = M0_CONTROL_PORT,
        transport: Optional[Transport] = None,
        control: Optional[M0Control] = None,
    ) -> None:
        super().__init__(name, width, height, transport or DDPTransport(host, ddp_port))
        self.control = control or M0Control(host, control_port)

    def store(
        self,
        slot: int,
        frame: Frame,
        dwell_ms: int,
        encoding: Encoding = Encoding.INDEXED16,
    ) -> None:
        if (frame.width, frame.height) != self.geometry:
            raise ValueError("stored frame geometry must match the panel")
        palette, payload = encode_frame(frame, encoding)
        self.control.store(slot, payload, dwell_ms, encoding, palette)

    def play(self, start_slot: int, end_slot: int, repeat: int = 0) -> None:
        self.control.play(start_slot, end_slot, repeat)

    def stop(self) -> None:
        self.control.stop()

    def clear(self) -> None:
        self.control.clear()

    def config(self, resume_policy: ResumePolicy, idle_ms: int = 2000) -> None:
        self.control.config(resume_policy, idle_ms)

    def info(self) -> dict:
        return self.control.info()

    def upload_loop(
        self,
        asset: AssetPattern,
        *,
        start_slot: int = 0,
        dwell_ms: Optional[int] = None,
        repeat: int = 0,
        encoding: Encoding = Encoding.INDEXED16,
    ) -> int:
        """Encode every asset frame into consecutive slots, then PLAY. Returns slot count.

        Per-frame dwell comes from the asset's own timing unless ``dwell_ms`` overrides it.
        """
        if asset.native_size != self.geometry:
            raise ValueError(
                f"asset {asset.native_size} does not match panel {self.geometry}"
            )
        frames = asset.frames
        for i, frame in enumerate(frames):
            if dwell_ms is not None:
                dwell = dwell_ms
            else:
                dwell = (
                    max(1, round(asset.durations[i] * 1000))
                    if asset.durations[i]
                    else 100
                )
            self.store(start_slot + i, frame, dwell, encoding)
        end_slot = start_slot + len(frames) - 1
        self.play(start_slot, end_slot, repeat)
        return len(frames)

    def close(self) -> None:
        super().close()
        self.control.close()


class WLEDTarget(DisplayTarget):
    """A stock WLED array: DDP for live frames, HTTP/JSON to trigger presets/playlists."""

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        host: str,
        *,
        ddp_port: int = DDP_PORT,
        http_port: int = 80,
        transport: Optional[Transport] = None,
        control: Optional[WLEDControl] = None,
    ) -> None:
        super().__init__(name, width, height, transport or DDPTransport(host, ddp_port))
        self.control = control or WLEDControl(host, http_port)

    def select_preset(self, preset_id: int) -> dict:
        return self.control.select_preset(preset_id)

    def start_playlist(self, playlist_id: int) -> dict:
        return self.control.start_playlist(playlist_id)

    def set_power(self, on: bool = True, brightness: Optional[int] = None) -> dict:
        return self.control.set_power(on, brightness)

    def probe(self) -> dict:
        return self.control.probe()


class _MemoryTransport:
    """Captures frames in memory instead of sending them on a wire."""

    def __init__(self) -> None:
        self.frames: List[Frame] = []

    def send_live(self, frame: Frame) -> None:
        self.frames.append(frame)

    def close(self) -> None:  # nothing to release
        pass


class StubTarget(DisplayTarget):
    """A no-hardware target proving the extension seam.

    A new display type required only this class and its (memory) transport — no change to
    any pattern or to the orchestrator. The seam test drives it with a real pattern.
    """

    def __init__(self, name: str, width: int, height: int) -> None:
        super().__init__(name, width, height, _MemoryTransport())

    @property
    def received(self) -> List[Frame]:
        return self.transport.frames  # type: ignore[attr-defined]
