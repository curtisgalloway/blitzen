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
"""M0 control protocol: store/play/stop the untethered slot-ring loop.

This is the *only* custom on-device protocol — it carries just what WLED gives us for free
but the M0 does not (uploading frames for a standalone loop). Live frames travel over DDP
(:mod:`host.transports.ddp`) and preempt the loop.

Wire format: every request is ``[opcode][seq][body...]`` on UDP (default port 4049). The
device replies ``[opcode | 0x80][seq][status][reply-body...]``. Control messages are rare
and must be reliable, so each is sent with a bounded ACK + retry; live DDP frames stay
fire-and-forget. See :mod:`host.protocol` for the shared constants.
"""

from __future__ import annotations

import socket
import struct
from typing import Dict, Optional

from host.protocol import (
    ACK_FLAG,
    M0_CONTROL_PORT,
    STATUS_OK,
    Encoding,
    Op,
    ResumePolicy,
)

_U16_MAX = 0xFFFF


class M0Error(Exception):
    """The M0 replied with a non-OK status or could not be reached."""


def _u16(name: str, value: int) -> bytes:
    if not 0 <= value <= _U16_MAX:
        raise ValueError(f"{name} must be 0..{_U16_MAX}, got {value}")
    return struct.pack(">H", value)


def _u8(name: str, value: int) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be 0..255, got {value}")
    return value


class M0Control:
    """Reliable (ACK + retry) UDP client for the M0 store/play control protocol."""

    def __init__(
        self,
        host: str,
        port: int = M0_CONTROL_PORT,
        *,
        timeout: float = 0.5,
        retries: int = 3,
        sock: Optional[socket.socket] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = max(1, retries)
        self._seq = 0
        self._owns_sock = sock is None
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(timeout)

    # -- low level ---------------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq = self._seq % 255 + 1  # 1..255, never 0
        return self._seq

    def _transact(self, opcode: Op, body: bytes = b"") -> bytes:
        """Send one request, wait for its matching ack, retrying on timeout."""
        seq = self._next_seq()
        packet = bytes((int(opcode), seq)) + body
        expected = int(opcode) | ACK_FLAG
        last_error: Optional[Exception] = None
        for _ in range(self.retries):
            self._sock.sendto(packet, (self.host, self.port))
            try:
                while True:
                    reply, _addr = self._sock.recvfrom(1024)
                    if len(reply) >= 3 and reply[0] == expected and reply[1] == seq:
                        status = reply[2]
                        if status != STATUS_OK:
                            raise M0Error(
                                f"{opcode.name} failed: device status {status}"
                            )
                        return reply[3:]
                    # Stale/mismatched datagram: keep reading until the socket times out.
            except socket.timeout:
                last_error = TimeoutError(
                    f"no ack for {opcode.name} (seq {seq}) within {self.timeout}s"
                )
        raise last_error or M0Error(f"{opcode.name} failed")

    # -- operations --------------------------------------------------------------------

    def store(
        self,
        slot: int,
        payload: bytes,
        dwell_ms: int,
        encoding: Encoding = Encoding.INDEXED16,
        palette: bytes = b"",
    ) -> None:
        """Write one already-encoded frame into RAM slot ``slot``.

        ``payload`` and ``palette`` come from :func:`host.encoder.encode_indexed` (or are
        raw RGB888 for ``Encoding.RAW_RGB888``). ``palette`` length must be a multiple of 3.
        """
        if len(palette) % 3 != 0:
            raise ValueError("palette length must be a multiple of 3 (RGB triples)")
        palette_count = len(palette) // 3
        body = (
            bytes((_u8("slot", slot),))
            + _u16("dwell_ms", dwell_ms)
            + bytes((int(encoding), _u8("palette_count", palette_count)))
            + palette
            + payload
        )
        self._transact(Op.STORE, body)

    def play(self, start_slot: int, end_slot: int, repeat: int = 0) -> None:
        """Begin the autonomous loop over slots ``start_slot..end_slot``.

        ``repeat`` is the loop count; 0 means loop forever.
        """
        body = bytes((_u8("start_slot", start_slot), _u8("end_slot", end_slot)))
        body += _u16("repeat", repeat)
        self._transact(Op.PLAY, body)

    def stop(self) -> None:
        """Halt the autonomous loop."""
        self._transact(Op.STOP)

    def clear(self) -> None:
        """Halt and free all stored slots."""
        self._transact(Op.CLEAR)

    def config(self, resume_policy: ResumePolicy, idle_ms: int = 2000) -> None:
        """Set the loop-resume policy after a live DDP frame (spec section 8, Q5)."""
        body = bytes((int(resume_policy),)) + _u16("idle_ms", idle_ms)
        self._transact(Op.CONFIG, body)

    def info(self) -> Dict[str, int]:
        """Query the device: free RAM, slot capacity, slots in use.

        Serves the spec's open question 1 — the measured free SRAM and resulting slot
        count — by reading them back from a running device.
        """
        data = self._transact(Op.INFO)
        if len(data) < 6:
            raise M0Error(f"INFO reply too short: {len(data)} bytes")
        free_ram, capacity, used = struct.unpack(">IBB", data[:6])
        return {"free_ram": free_ram, "slot_capacity": capacity, "slots_used": used}

    def close(self) -> None:
        if self._owns_sock:
            self._sock.close()
