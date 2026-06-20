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
"""Shared wire constants for the M0 control protocol.

This is the single source of truth the host and the M0 firmware must agree on. The same
numeric values are mirrored in ``firmware/m0/m0_display_client.ino``; keep them in sync.
"""

from __future__ import annotations

from enum import IntEnum

# UDP ports (design spec section 4): DDP live on 4048, M0 control on a separate port.
DDP_PORT = 4048
M0_CONTROL_PORT = 4049


class Encoding(IntEnum):
    """Stored-frame encodings (design spec section 5.2). INDEXED16 is the sweet spot."""

    RAW_RGB888 = 0
    RGB565 = 1
    INDEXED16 = 2
    INDEXED256 = 3
    BIT1 = 4


class ResumePolicy(IntEnum):
    """What the M0 does after a live DDP frame stops arriving (spec section 8, Q5)."""

    IDLE_TIMEOUT = 0  # resume the stored loop after `idle_ms` with no DDP frames
    EXPLICIT = 1  # stay blank/last-frame until an explicit PLAY message


class Op(IntEnum):
    """One-byte opcodes for the M0 control protocol (spec section 4.2)."""

    STORE = 0x01
    PLAY = 0x02
    STOP = 0x03
    CLEAR = 0x04
    INFO = 0x05
    CONFIG = 0x06


#: A reply sets this high bit in the opcode byte (e.g. STORE ack = 0x01 | 0x80 = 0x81).
ACK_FLAG = 0x80

#: Status byte values in an ack reply.
STATUS_OK = 0x00
STATUS_ERR = 0x01
