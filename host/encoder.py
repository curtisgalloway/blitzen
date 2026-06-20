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
"""Palette encoder for the M0 store path.

Turns an arbitrary :class:`~host.frame.Frame` into a small palette + packed indices so a
loop fits in the M0's tiny SRAM (design spec section 5.2). 16-color indexed is the sweet
spot: 32x32 -> 512 bytes of 4-bit indices + a 48-byte palette. This runs host-side only;
the live DDP path stays full RGB888.
"""

from __future__ import annotations

from typing import Tuple

from PIL import Image

from host.frame import Frame
from host.protocol import Encoding


def _pack_nibbles(indices: bytes) -> bytes:
    """Pack 4-bit values two-per-byte, first pixel in the high nibble."""
    out = bytearray((len(indices) + 1) // 2)
    for i, idx in enumerate(indices):
        if i % 2 == 0:
            out[i // 2] = (idx & 0x0F) << 4
        else:
            out[i // 2] |= idx & 0x0F
    return bytes(out)


def _unpack_nibbles(packed: bytes, count: int) -> bytes:
    """Inverse of :func:`_pack_nibbles` for ``count`` indices."""
    out = bytearray(count)
    for i in range(count):
        byte = packed[i // 2]
        out[i] = (byte >> 4) & 0x0F if i % 2 == 0 else byte & 0x0F
    return bytes(out)


def encode_indexed(frame: Frame, colors: int = 16) -> Tuple[bytes, bytes]:
    """Quantize ``frame`` to ``colors`` and return ``(palette, packed_indices)``.

    ``palette`` is ``colors * 3`` RGB bytes. ``packed_indices`` is 4-bit-packed when
    ``colors <= 16``, otherwise one byte per pixel.
    """
    if not 2 <= colors <= 256:
        raise ValueError("colors must be between 2 and 256")
    img = Image.frombytes("RGB", (frame.width, frame.height), frame.to_bytes())
    quantized = img.quantize(colors=colors)  # default = median cut for RGB
    raw_palette = quantized.getpalette() or []
    needed = colors * 3
    palette = bytes((raw_palette + [0] * needed)[:needed])
    indices = quantized.tobytes()
    packed = _pack_nibbles(indices) if colors <= 16 else indices
    return palette, packed


def decode_indexed(
    palette: bytes, packed: bytes, width: int, height: int, colors: int = 16
) -> Frame:
    """Inverse of :func:`encode_indexed`: rebuild a :class:`Frame` (used by tests/preview)."""
    count = width * height
    indices = _unpack_nibbles(packed, count) if colors <= 16 else packed[:count]
    data = bytearray(count * 3)
    for i, idx in enumerate(indices):
        base = idx * 3
        data[i * 3 : i * 3 + 3] = palette[base : base + 3]
    return Frame(width, height, data)


def encode_frame(frame: Frame, encoding: Encoding) -> Tuple[bytes, bytes]:
    """Encode ``frame`` for a STORE message: returns ``(palette, payload)``.

    ``palette`` is empty for encodings that do not use one. Only RAW_RGB888 and INDEXED16
    are implemented today; others raise so a silent wrong-format never reaches the device.
    """
    if encoding == Encoding.RAW_RGB888:
        return b"", frame.to_bytes()
    if encoding == Encoding.INDEXED16:
        return encode_indexed(frame, 16)
    if encoding == Encoding.INDEXED256:
        return encode_indexed(frame, 256)
    raise NotImplementedError(f"encoding {encoding!r} not implemented host-side yet")
