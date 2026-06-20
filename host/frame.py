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
"""The logical framebuffer.

A :class:`Frame` is **always** logical row-major RGB888 — the single, hardware-agnostic
pixel convention for the whole host (design spec section 3). No target ever gets special
pixel ordering on the host side: physical remapping (serpentine, panel scan) is the
device's or its config's responsibility.

Byte layout: ``data[(y * width + x) * 3 + c]`` for channel ``c`` in ``(R, G, B)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


def clamp8(value: int) -> int:
    """Clamp an integer into the inclusive 0..255 byte range."""
    return 0 if value < 0 else 255 if value > 255 else int(value)


@dataclass
class Frame:
    """A row-major RGB888 image of ``width`` x ``height`` pixels.

    ``data`` holds exactly ``width * height * 3`` bytes. Equality (provided by the
    dataclass) compares geometry and pixel bytes, which is what the tests rely on.
    """

    width: int
    height: int
    data: bytearray

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"frame dimensions must be positive, got {self.width}x{self.height}"
            )
        expected = self.width * self.height * 3
        if len(self.data) != expected:
            raise ValueError(
                f"data length {len(self.data)} != width*height*3 ({expected}) "
                f"for {self.width}x{self.height}"
            )
        if not isinstance(self.data, bytearray):
            # Accept any bytes-like input but normalise storage to a mutable bytearray.
            self.data = bytearray(self.data)

    # -- construction ------------------------------------------------------------------

    @classmethod
    def blank(
        cls, width: int, height: int, color: Tuple[int, int, int] = (0, 0, 0)
    ) -> "Frame":
        """Return a new frame filled with a single ``color``."""
        r, g, b = (clamp8(c) for c in color)
        return cls(width, height, bytearray(bytes((r, g, b)) * (width * height)))

    def copy(self) -> "Frame":
        """Return a deep copy with an independent ``data`` buffer."""
        return Frame(self.width, self.height, bytearray(self.data))

    # -- pixel access ------------------------------------------------------------------

    def _offset(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(
                f"pixel ({x}, {y}) out of range for {self.width}x{self.height}"
            )
        return (y * self.width + x) * 3

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        """Set the RGB value at ``(x, y)``; channel values are clamped to 0..255."""
        i = self._offset(x, y)
        self.data[i] = clamp8(r)
        self.data[i + 1] = clamp8(g)
        self.data[i + 2] = clamp8(b)

    def get_pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        """Return the ``(r, g, b)`` tuple at ``(x, y)``."""
        i = self._offset(x, y)
        return self.data[i], self.data[i + 1], self.data[i + 2]

    def fill(self, r: int, g: int, b: int) -> None:
        """Fill the whole frame with one color."""
        self.data[:] = bytes((clamp8(r), clamp8(g), clamp8(b))) * (
            self.width * self.height
        )

    # -- conversions -------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Return an immutable copy of the row-major RGB888 buffer."""
        return bytes(self.data)

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    def __len__(self) -> int:
        """Number of *pixels* (not bytes) in the frame."""
        return self.width * self.height
