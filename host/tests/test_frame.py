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
"""Tests for the logical framebuffer."""

import pytest

from host.frame import Frame, clamp8


def test_blank_fills_color_row_major():
    f = Frame.blank(2, 2, (10, 20, 30))
    assert f.width == 2 and f.height == 2
    assert len(f.data) == 2 * 2 * 3
    assert f.get_pixel(0, 0) == (10, 20, 30)
    assert f.get_pixel(1, 1) == (10, 20, 30)


def test_len_is_pixel_count():
    assert len(Frame.blank(8, 32)) == 256


def test_set_and_get_pixel():
    f = Frame.blank(4, 4)
    f.set_pixel(3, 2, 1, 2, 3)
    assert f.get_pixel(3, 2) == (1, 2, 3)
    # Verify byte offset is row-major: (y*w + x)*3.
    offset = (2 * 4 + 3) * 3
    assert bytes(f.data[offset : offset + 3]) == bytes((1, 2, 3))


def test_set_pixel_clamps_channels():
    f = Frame.blank(1, 1)
    f.set_pixel(0, 0, -5, 300, 128)
    assert f.get_pixel(0, 0) == (0, 255, 128)


def test_out_of_bounds_raises():
    f = Frame.blank(2, 2)
    with pytest.raises(IndexError):
        f.get_pixel(2, 0)
    with pytest.raises(IndexError):
        f.set_pixel(0, 2, 0, 0, 0)


def test_bad_data_length_raises():
    with pytest.raises(ValueError):
        Frame(2, 2, bytearray(3))


def test_nonpositive_dimensions_raise():
    with pytest.raises(ValueError):
        Frame(0, 4, bytearray(0))


def test_copy_is_independent():
    a = Frame.blank(2, 2, (5, 5, 5))
    b = a.copy()
    b.set_pixel(0, 0, 9, 9, 9)
    assert a.get_pixel(0, 0) == (5, 5, 5)
    assert b.get_pixel(0, 0) == (9, 9, 9)


def test_equality_compares_pixels():
    assert Frame.blank(2, 2, (1, 2, 3)) == Frame.blank(2, 2, (1, 2, 3))
    assert Frame.blank(2, 2, (1, 2, 3)) != Frame.blank(2, 2, (3, 2, 1))


def test_clamp8():
    assert clamp8(-1) == 0
    assert clamp8(256) == 255
    assert clamp8(200) == 200
