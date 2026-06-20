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
"""Palette encoder: nibble packing and a clean 16-color round trip."""

from host.encoder import (
    _pack_nibbles,
    _unpack_nibbles,
    decode_indexed,
    encode_frame,
    encode_indexed,
)
from host.frame import Frame
from host.protocol import Encoding


def test_pack_unpack_nibbles_round_trip():
    indices = bytes([0, 15, 1, 14, 7, 8, 3])
    packed = _pack_nibbles(indices)
    assert len(packed) == (len(indices) + 1) // 2
    assert packed[0] == (0 << 4) | 15  # first pair high|low
    assert _unpack_nibbles(packed, len(indices)) == indices


def _four_color_frame(width=8, height=8):
    palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
    data = bytearray(width * height * 3)
    for i in range(width * height):
        r, g, b = palette[i % 4]
        data[i * 3 : i * 3 + 3] = bytes((r, g, b))
    return Frame(width, height, data)


def test_indexed16_round_trip_exact_for_few_colors():
    frame = _four_color_frame()
    palette, packed = encode_indexed(frame, 16)
    assert len(palette) == 16 * 3
    assert len(packed) == frame.pixel_count // 2  # 4-bit packed
    decoded = decode_indexed(palette, packed, frame.width, frame.height, 16)
    assert decoded == frame


def test_indexed16_sizes_for_32x32():
    frame = Frame.blank(32, 32, (20, 40, 60))
    palette, packed = encode_indexed(frame, 16)
    assert len(palette) == 48
    assert len(packed) == 512  # the spec section 5.2 "sweet spot"


def test_encode_frame_raw_passthrough():
    frame = Frame.blank(4, 4, (1, 2, 3))
    palette, payload = encode_frame(frame, Encoding.RAW_RGB888)
    assert palette == b""
    assert payload == frame.to_bytes()


def test_encode_frame_indexed16():
    frame = _four_color_frame()
    palette, payload = encode_frame(frame, Encoding.INDEXED16)
    assert len(palette) == 48
    assert len(payload) == frame.pixel_count // 2
