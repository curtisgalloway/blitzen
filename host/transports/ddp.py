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
"""DDP (Distributed Display Protocol) over UDP — the single live path for every target.

Header layout (10 bytes, big-endian), matching the DDP spec and WLED's parser::

    byte 0    flags: version (bits 7-6 = 0b01) | PUSH (bit 0)
    byte 1    sequence number (low nibble, 1..15; 0 = unused)
    byte 2    data type (0x01 = RGB pixel data; WLED ignores this field)
    byte 3    destination id (1 = default output device)
    byte 4-7  data offset in bytes (uint32)
    byte 8-9  data length in bytes (uint16)
    byte 10+  payload: row-major RGB888

Reality-vs-spec note (design spec section 4.1): a 32x32 RGB frame is 3072 bytes, which
exceeds the 1500-byte Ethernet MTU and very likely the M0 ATWINC1500/WiFi101 UDP receive
buffer. DDP's data-offset field exists exactly for this, so frames larger than
``max_payload`` are split into several DDP packets with the PUSH bit set only on the last
one; the receiver reassembles by offset and renders on PUSH. The default keeps every
datagram inside one un-fragmented Ethernet frame.
"""

from __future__ import annotations

import socket
import struct
from typing import List, Optional

from host.frame import Frame
from host.protocol import DDP_PORT

DDP_HEADER_LEN = 10

# Flag byte components.
DDP_FLAGS_VERSION1 = 0x40  # version 1 in bits 7-6
DDP_FLAG_PUSH = 0x01

DDP_DATA_TYPE_RGB = 0x01
DDP_ID_DEFAULT_OUTPUT = 1

# 1440 is a multiple of 3 (whole pixels) and keeps header+payload (1450) under 1500 MTU.
DEFAULT_MAX_PAYLOAD = 1440

_HEADER = struct.Struct(">BBBBIH")


def build_packets(
    payload: bytes,
    *,
    sequence: int = 0,
    dest_id: int = DDP_ID_DEFAULT_OUTPUT,
    data_type: int = DDP_DATA_TYPE_RGB,
    max_payload: int = DEFAULT_MAX_PAYLOAD,
) -> List[bytes]:
    """Split ``payload`` into one or more DDP packets; PUSH is set only on the last."""
    if max_payload <= 0:
        raise ValueError("max_payload must be positive")
    seq_nibble = sequence & 0x0F
    total = len(payload)
    packets: List[bytes] = []
    offset = 0
    while True:
        chunk = payload[offset : offset + max_payload]
        is_last = offset + len(chunk) >= total
        flags = DDP_FLAGS_VERSION1 | (DDP_FLAG_PUSH if is_last else 0)
        header = _HEADER.pack(flags, seq_nibble, data_type, dest_id, offset, len(chunk))
        packets.append(header + chunk)
        offset += len(chunk)
        if is_last:
            break
    return packets


class DDPReassembler:
    """Reassembles DDP packets into a complete payload, signalling on PUSH.

    Shared by :mod:`host.tools.ddp_sink` and the tests; mirrors what the M0 firmware does.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._high = 0  # highest byte offset written since the last completed frame

    def feed(self, packet: bytes) -> Optional[bytes]:
        """Consume one packet; return the full payload bytes when PUSH is seen, else None."""
        if len(packet) < DDP_HEADER_LEN:
            raise ValueError(f"DDP packet too short: {len(packet)} bytes")
        flags, _seq, _dtype, _dest, offset, length = _HEADER.unpack(
            packet[:DDP_HEADER_LEN]
        )
        data = packet[DDP_HEADER_LEN : DDP_HEADER_LEN + length]
        end = offset + len(data)
        if end > len(self._buf):
            self._buf.extend(b"\x00" * (end - len(self._buf)))
        self._buf[offset:end] = data
        if end > self._high:
            self._high = end
        if flags & DDP_FLAG_PUSH:
            payload = bytes(self._buf[: self._high])
            self._high = 0
            return payload
        return None


class DDPTransport:
    """Live transport: serialize a :class:`Frame` to DDP and fire it over UDP.

    Used unchanged for both the M0 panel and WLED arrays — that is the point of unifying
    the live path. Sends are fire-and-forget (loss-tolerant).
    """

    def __init__(
        self,
        host: str,
        port: int = DDP_PORT,
        *,
        dest_id: int = DDP_ID_DEFAULT_OUTPUT,
        data_type: int = DDP_DATA_TYPE_RGB,
        max_payload: int = DEFAULT_MAX_PAYLOAD,
        sock: Optional[socket.socket] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.dest_id = dest_id
        self.data_type = data_type
        self.max_payload = max_payload
        self._seq = 0
        self._owns_sock = sock is None
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _next_sequence(self) -> int:
        # DDP sequence cycles 1..15 (0 means "unused"); one value per frame.
        self._seq = self._seq % 15 + 1
        return self._seq

    def send_live(self, frame: Frame) -> None:
        seq = self._next_sequence()
        for packet in build_packets(
            frame.to_bytes(),
            sequence=seq,
            dest_id=self.dest_id,
            data_type=self.data_type,
            max_payload=self.max_payload,
        ):
            self._sock.sendto(packet, (self.host, self.port))

    def close(self) -> None:
        if self._owns_sock:
            self._sock.close()
