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
"""Procedural patterns.

Each computes per normalized ``(x/w, y/h, t)``, so the *same code* fills 32x32 and 8x32
(handoff acceptance criterion). Output is deterministic for a given ``(w, h, t)``.
"""

from __future__ import annotations

import colorsys
import math
from typing import Optional, Tuple

from host.frame import Frame
from host.patterns.base import register


@register("solid")
class SolidColor:
    """A constant color at any geometry. Trivial, deterministic — handy for bring-up."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, color: Tuple[int, int, int] = (255, 255, 255)) -> None:
        self.color = color

    def render(self, width: int, height: int, t: float) -> Frame:
        return Frame.blank(width, height, self.color)


@register("gradient")
class Gradient:
    """Static horizontal gradient from ``start`` to ``end`` across the x axis."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(
        self,
        start: Tuple[int, int, int] = (0, 0, 0),
        end: Tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        self.start = start
        self.end = end

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        span = max(1, width - 1)
        sr, sg, sb = self.start
        er, eg, eb = self.end
        # One row of gradient, repeated for every row.
        row = bytearray(width * 3)
        for x in range(width):
            f = x / span
            row[x * 3] = int(sr + (er - sr) * f)
            row[x * 3 + 1] = int(sg + (eg - sg) * f)
            row[x * 3 + 2] = int(sb + (eb - sb) * f)
        for y in range(height):
            data[y * width * 3 : (y + 1) * width * 3] = row
        return Frame(width, height, data)


@register("scroll")
class Scroll:
    """A rainbow of vertical stripes scrolling horizontally over time."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, speed: float = 0.25, cycles: float = 1.0) -> None:
        # ``speed``: hue revolutions per second. ``cycles``: rainbows across the width.
        self.speed = speed
        self.cycles = cycles

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        phase = t * self.speed
        row = bytearray(width * 3)
        for x in range(width):
            hue = (x / width * self.cycles + phase) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            row[x * 3] = int(r * 255)
            row[x * 3 + 1] = int(g * 255)
            row[x * 3 + 2] = int(b * 255)
        for y in range(height):
            data[y * width * 3 : (y + 1) * width * 3] = row
        return Frame(width, height, data)


@register("plasma")
class Plasma:
    """Classic multi-sine plasma. Smooth, geometry-independent, time-animated."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, scale: float = 8.0, speed: float = 1.0) -> None:
        self.scale = scale
        self.speed = speed

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        k = self.scale
        tt = t * self.speed
        # Moving center for the radial term.
        cx = 0.5 + 0.5 * math.sin(tt / 3.0)
        cy = 0.5 + 0.5 * math.cos(tt / 2.0)
        two_thirds = 2.0 * math.pi / 3.0
        i = 0
        for y in range(height):
            ny = y / height
            for x in range(width):
                nx = x / width
                v = math.sin(nx * k + tt)
                v += math.sin(ny * k + tt * 1.3)
                v += math.sin((nx + ny) * k * 0.75 + tt * 1.7)
                dx = nx - cx
                dy = ny - cy
                v += math.sin(math.sqrt(dx * dx + dy * dy) * k + tt)
                phase = math.pi * v
                data[i] = int(128 + 127 * math.sin(phase))
                data[i + 1] = int(128 + 127 * math.sin(phase + two_thirds))
                data[i + 2] = int(128 + 127 * math.sin(phase + 2 * two_thirds))
                i += 3
        return Frame(width, height, data)
