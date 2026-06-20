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


def _hash01(*ints: int) -> float:
    """Deterministic pseudo-random float in ``[0, 1)`` from integer coordinates.

    A small FNV-1a hash with an avalanche finalizer. Unlike Python's builtin
    ``hash``, it is *not* salted per process, so patterns that scatter pixels
    (stars, rain columns) stay reproducible run-to-run — the determinism the
    pattern tests rely on.
    """
    h = 0x811C9DC5
    for v in ints:
        h = ((h ^ (v & 0xFFFFFFFF)) * 0x01000193) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0x5BD1E995) & 0xFFFFFFFF
    h ^= h >> 15
    return (h & 0xFFFFFF) / float(0x1000000)


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


def _fire_palette(heat: float) -> Tuple[int, int, int]:
    """Map a 0..1 heat value onto a black -> red -> orange -> yellow -> white ramp."""
    r = min(255, int(heat * 3.0 * 255))
    g = min(255, int(max(0.0, heat - 1.0 / 3.0) * 3.0 * 255))
    b = min(255, int(max(0.0, heat - 2.0 / 3.0) * 3.0 * 255))
    return r, g, b


@register("fire")
class Fire:
    """A flickering flame — coolest (black) at the top, white-hot at the bottom."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, speed: float = 1.0, scale: float = 4.0) -> None:
        # ``speed``: flicker rate. ``scale``: turbulence spatial frequency.
        self.speed = speed
        self.scale = scale

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        tt = t * self.speed
        k = self.scale
        i = 0
        for y in range(height):
            ny = y / height  # 0 at top, ->1 at the bottom (where the fire lives)
            for x in range(width):
                nx = x / width
                turb = (
                    math.sin(nx * k * 1.7 + tt * 2.0)
                    + math.sin((nx + ny) * k + tt * 1.3)
                    + math.sin(nx * k * 0.5 - tt * 1.1)
                )
                heat = ny + 0.15 * turb  # hotter low, modulated by turbulence
                heat = 0.0 if heat < 0.0 else 1.0 if heat > 1.0 else heat
                data[i], data[i + 1], data[i + 2] = _fire_palette(heat)
                i += 3
        return Frame(width, height, data)


@register("ripple")
class Ripple:
    """Concentric waves rippling outward from the center, like rain on water."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, speed: float = 1.5, wavelength: float = 0.18) -> None:
        # ``speed``: rings per second. ``wavelength``: spacing as a fraction of size.
        self.speed = speed
        self.wavelength = wavelength

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        tt = t * self.speed
        two_pi = 2.0 * math.pi
        i = 0
        for y in range(height):
            dy = (y + 0.5) / height - 0.5
            for x in range(width):
                dx = (x + 0.5) / width - 0.5
                d = math.sqrt(dx * dx + dy * dy)
                v = math.sin((d / self.wavelength - tt) * two_pi)
                hue = (0.55 + 0.15 * v) % 1.0  # drift around cyan/blue
                val = 0.5 + 0.5 * v
                r, g, b = colorsys.hsv_to_rgb(hue, 0.85, val)
                data[i] = int(r * 255)
                data[i + 1] = int(g * 255)
                data[i + 2] = int(b * 255)
                i += 3
        return Frame(width, height, data)


@register("swirl")
class Swirl:
    """A rotating multi-arm color spiral about the center."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, arms: float = 3.0, speed: float = 0.5, twist: float = 4.0) -> None:
        self.arms = arms
        self.speed = speed
        self.twist = twist

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        tt = t * self.speed
        two_pi = 2.0 * math.pi
        i = 0
        for y in range(height):
            dy = (y + 0.5) / height - 0.5
            for x in range(width):
                dx = (x + 0.5) / width - 0.5
                ang = math.atan2(dy, dx)
                rad = math.sqrt(dx * dx + dy * dy)
                hue = (self.arms * ang / two_pi + self.twist * rad - tt) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                data[i] = int(r * 255)
                data[i + 1] = int(g * 255)
                data[i + 2] = int(b * 255)
                i += 3
        return Frame(width, height, data)


@register("sparkle")
class Sparkle:
    """A starfield of pixels twinkling independently, each at its own fixed phase."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, density: float = 0.4, speed: float = 1.0) -> None:
        # ``density``: fraction of pixels that are stars. ``speed``: twinkle rate.
        self.density = density
        self.speed = speed

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        tt = t * self.speed
        two_pi = 2.0 * math.pi
        i = 0
        for y in range(height):
            for x in range(width):
                if _hash01(x, y, 99) < self.density:
                    phase = _hash01(x, y)  # fixed per-star offset
                    tw = 0.5 + 0.5 * math.sin((tt + phase) * two_pi)
                    tw *= tw  # sharpen into brief sparkles
                    hue = _hash01(x, y, 7)
                    r, g, b = colorsys.hsv_to_rgb(hue, 0.3, tw)
                    data[i] = int(r * 255)
                    data[i + 1] = int(g * 255)
                    data[i + 2] = int(b * 255)
                i += 3
        return Frame(width, height, data)


@register("rain")
class Rain:
    """Matrix-style digital rain: green drops fall down each column with a bright tip."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, speed: float = 0.8, trail: float = 0.5) -> None:
        # ``speed``: fall rate. ``trail``: comet length as a fraction of column height.
        self.speed = speed
        self.trail = trail

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        tt = t * self.speed
        for x in range(width):
            col_speed = 0.5 + _hash01(x, 1)  # each column falls at its own rate
            col_off = _hash01(x, 2)
            head = (tt * col_speed + col_off) % 1.0
            for y in range(height):
                ny = (y + 0.5) / height
                d = (head - ny) % 1.0  # distance below the head, wrapping
                if d >= self.trail:
                    continue
                b = 1.0 - d / self.trail  # bright at the head, fading down the trail
                tip = max(0.0, b - 0.8) * 5.0  # white-green flare at the very head
                i = (y * width + x) * 3
                data[i] = int(200 * tip * b)
                data[i + 1] = int(255 * b)
                data[i + 2] = int(120 * tip * b)
        return Frame(width, height, data)


@register("bounce")
class Bounce:
    """A glowing dot bouncing around the frame, DVD-logo style, slowly cycling hue."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, speed: float = 0.7, radius: float = 0.18) -> None:
        self.speed = speed
        self.radius = radius

    @staticmethod
    def _tri(p: float) -> float:
        """Triangle wave in ``[0, 1]`` — linear bounce between the two walls."""
        p %= 1.0
        return 2.0 * p if p < 0.5 else 2.0 * (1.0 - p)

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        tt = t * self.speed
        cx = 0.1 + 0.8 * self._tri(tt * 0.53)
        cy = 0.1 + 0.8 * self._tri(tt * 0.37 + 0.25)
        cr, cg, cb = colorsys.hsv_to_rgb((tt * 0.1) % 1.0, 1.0, 1.0)
        i = 0
        for y in range(height):
            ny = (y + 0.5) / height
            for x in range(width):
                nx = (x + 0.5) / width
                dx = nx - cx
                dy = ny - cy
                d = math.sqrt(dx * dx + dy * dy)
                glow = max(0.0, 1.0 - d / self.radius)
                glow *= glow  # soft-edged falloff
                data[i] = int(cr * 255 * glow)
                data[i + 1] = int(cg * 255 * glow)
                data[i + 2] = int(cb * 255 * glow)
                i += 3
        return Frame(width, height, data)


#: The TOS computer-panel palette — saturated primaries plus white, the colors of
#: Wah Chang's blinking "Christmas light" props.
_M5_PALETTE = (
    (220, 40, 40),    # red
    (240, 150, 30),   # amber
    (230, 215, 60),   # yellow
    (70, 200, 100),   # green
    (60, 120, 235),   # blue
    (235, 235, 245),  # white
)


@register("m5")
class M5Computer:
    """The M-5 multitronic computer panel ("The Ultimate Computer").

    A lattice of vertical and horizontal light-lines, each snapping on and off at
    its own rate and phase, brighter where they cross — the busy, pseudo-random
    TOS computer-panel "thinking" look. Off lines stay faintly lit so the grid
    structure reads even between flashes. Geometry-independent and deterministic.
    """

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, spacing: int = 3, rate: float = 1.5, duty: float = 0.5,
                 reroll: bool = False) -> None:
        # ``spacing``: pixels between adjacent lines. ``rate``: blink-rate ceiling
        # (Hz). ``duty``: fraction of each blink cycle a line stays lit.
        # ``reroll``: when True, a bar gets a fresh length/position each time it
        # lights (the panel constantly reshuffles); when False the layout is fixed.
        self.spacing = spacing
        self.rate = rate
        self.duty = duty
        self.reroll = reroll

    def _line(self, seed: int, idx: int, extent: int, t: float):
        """Resolve line ``idx`` on axis ``seed`` for time ``t``.

        Returns ``(color, start, length)`` for a lit bar, or ``None`` when the line
        is dark — off bars are pure black, so only the flashing segments show. Each
        bar is a *segment* of random length (15..70% of ``extent``) at a random
        position, so it never spans the grid; with ``reroll`` the segment is
        re-derived from the blink-cycle index each time the bar lights.
        """
        rate = 0.3 + self.rate * _hash01(seed, idx, 7)
        pos = t * rate + _hash01(seed, idx)
        if (pos % 1.0) >= self.duty:
            return None  # off -> black
        color = _M5_PALETTE[int(_hash01(seed, idx, 3) * len(_M5_PALETTE))
                            % len(_M5_PALETTE)]
        if self.reroll:
            cycle = int(pos)  # which blink this is -> fresh geometry per flash
            frac_h = _hash01(seed, idx, 5, cycle)
            start_h = _hash01(seed, idx, 9, cycle)
        else:
            frac_h = _hash01(seed, idx, 5)
            start_h = _hash01(seed, idx, 9)
        length = max(1, int(round((0.15 + 0.55 * frac_h) * extent)))
        start = int(start_h * (extent - length + 1))
        return color, start, length

    def render(self, width: int, height: int, t: float) -> Frame:
        data = bytearray(width * height * 3)
        step = max(1, int(self.spacing))
        # Resolve each line once per frame (vertical = columns, horizontal = rows);
        # an unlit line is None and contributes nothing (black).
        vert = {x: self._line(11, x, height, t) for x in range(0, width, step)}
        horiz = {y: self._line(22, y, width, t) for y in range(0, height, step)}
        i = 0
        for y in range(height):
            h_line = horiz.get(y)
            for x in range(width):
                r = g = b = 0
                v_line = vert.get(x)
                if v_line is not None:
                    color, start, length = v_line
                    if start <= y < start + length:
                        r += color[0]
                        g += color[1]
                        b += color[2]
                if h_line is not None:
                    color, start, length = h_line
                    if start <= x < start + length:
                        r += color[0]
                        g += color[1]
                        b += color[2]
                # Additive crossings make the lattice nodes pop (clamp to white).
                data[i] = 255 if r > 255 else r
                data[i + 1] = 255 if g > 255 else g
                data[i + 2] = 255 if b > 255 else b
                i += 3
        return Frame(width, height, data)


def _phosphor_rgb(v: float) -> Tuple[int, int, int]:
    """Map a 0..~1.4 beam intensity onto a CRT-phosphor green, white-hot at the head."""
    if v <= 0.0:
        return (0, 0, 0)
    capped = 1.0 if v > 1.0 else v
    white = max(0.0, v - 0.85) * 4.0  # the freshly-struck beam blooms toward white
    r = int(220 * white)
    g = int(60 + 195 * capped)
    b = int(50 * capped + 120 * white)
    return (255 if r > 255 else r, 255 if g > 255 else g, 255 if b > 255 else b)


def _scope_render(width: int, height: int, t: float, wave, amp: float,
                  sweep: float, persist: float, thickness: float) -> Frame:
    """Trace ``wave`` (``xn -> [-1,1]``) across a graticule with phosphor persistence.

    Adjacent samples are joined into a band so steep/vertical edges are drawn, and a
    left-to-right beam at ``sweep`` cycles/sec lights the trace brightest just behind
    it, decaying with ``persist`` — the classic glowing sweep.
    """
    data = bytearray(width * height * 3)
    sx = (t * sweep) % 1.0
    persist = 0.02 if persist < 0.02 else persist
    th = thickness
    dx = 1.0 / width
    gw = max(2, width // 8)
    gh = max(2, height // 8)
    cx, cy = width // 2, height // 2
    i = 0
    for y in range(height):
        vy = 1.0 - 2.0 * ((y + 0.5) / height)  # +1 at the top, -1 at the bottom
        grid_row = (y % gh == 0) or y == cy
        for x in range(width):
            xn = (x + 0.5) / width
            w0 = wave(xn) * amp
            w1 = wave(xn + dx) * amp           # next sample -> draw the joining band
            lo, hi = (w0, w1) if w0 < w1 else (w1, w0)
            trace = 0.0
            if lo - th <= vy <= hi + th:
                d = lo - vy if vy < lo else vy - hi if vy > hi else 0.0
                trace = 1.0 - d / th
                if trace > 0.0:
                    trace *= math.exp(-((sx - xn) % 1.0) / persist)  # phosphor decay
            base = 0.18 if (x == cx or y == cy) else \
                0.09 if (grid_row or x % gw == 0) else 0.0
            rgb = _phosphor_rgb(trace if trace > base else base)
            data[i], data[i + 1], data[i + 2] = rgb
            i += 3
    return Frame(width, height, data)


@register("scope")
class Scope:
    """A phosphor oscilloscope trace: a live compound sine sweeping over a graticule."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, freq: float = 1.5, amp: float = 0.8,
                 sweep: float = 0.3, persist: float = 0.35) -> None:
        self.freq = freq
        self.amp = amp
        self.sweep = sweep
        self.persist = persist

    def render(self, width: int, height: int, t: float) -> Frame:
        f = self.freq

        def wave(xn: float) -> float:
            return (0.62 * math.sin(2.0 * math.pi * f * xn - t * 2.0)
                    + 0.30 * math.sin(2.0 * math.pi * f * 2.0 * xn - t * 3.1))

        return _scope_render(width, height, t, wave, self.amp,
                             self.sweep, self.persist, 0.12)


@register("pulse")
class Pulse:
    """A square / pulse-train trace on the scope — flat tops and sharp vertical edges."""

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, freq: float = 2.0, duty: float = 0.5, amp: float = 0.8,
                 sweep: float = 0.3, persist: float = 0.4) -> None:
        self.freq = freq
        self.duty = duty
        self.amp = amp
        self.sweep = sweep
        self.persist = persist

    def render(self, width: int, height: int, t: float) -> Frame:
        f, duty = self.freq, self.duty

        def wave(xn: float) -> float:
            return 1.0 if ((f * xn - t * 0.5) % 1.0) < duty else -1.0

        return _scope_render(width, height, t, wave, self.amp,
                             self.sweep, self.persist, 0.12)


@register("lissajous")
class Lissajous:
    """XY-mode oscilloscope: a glowing Lissajous figure whose phase slowly drifts.

    The electron beam runs the closed curve ``x = sin(a·u + δ)``, ``y = sin(b·u)``;
    points are brightest where the beam just passed and fade with ``persist``, giving
    the bright-head / decaying-tail look of a real XY display.
    """

    procedural = True
    native_size: Optional[Tuple[int, int]] = None

    def __init__(self, a: float = 3.0, b: float = 2.0,
                 speed: float = 0.5, persist: float = 0.5) -> None:
        self.a = a
        self.b = b
        self.speed = speed
        self.persist = persist

    def render(self, width: int, height: int, t: float) -> Frame:
        inten = [0.0] * (width * height)
        gw = max(2, width // 8)
        gh = max(2, height // 8)
        cx, cy = width // 2, height // 2
        for y in range(height):
            for x in range(width):
                if x == cx or y == cy:
                    inten[y * width + x] = 0.16
                elif x % gw == 0 or y % gh == 0:
                    inten[y * width + x] = 0.08
        n = max(240, 10 * max(width, height))
        persist = 0.02 if self.persist < 0.02 else self.persist
        delta = 2.0 * math.pi * (t * 0.3)       # slow phase drift morphs the figure
        u_now = (t * self.speed) % 1.0
        for s in range(n):
            u = s / n
            bright = math.exp(-((u_now - u) % 1.0) / persist)
            px = (math.sin(2.0 * math.pi * self.a * u + delta) * 0.5 + 0.5) * (width - 1)
            py = (math.sin(2.0 * math.pi * self.b * u) * 0.5 + 0.5) * (height - 1)
            ix, iy = int(px), int(py)
            fx, fy = px - ix, py - iy
            for oy in (0, 1):                    # bilinear splat for a smooth trace
                yy = iy + oy
                if yy < 0 or yy >= height:
                    continue
                for ox in (0, 1):
                    xx = ix + ox
                    if 0 <= xx < width:
                        inten[yy * width + xx] += bright * (1 - abs(ox - fx)) * (1 - abs(oy - fy))
        data = bytearray(width * height * 3)
        for k, v in enumerate(inten):
            data[k * 3], data[k * 3 + 1], data[k * 3 + 2] = _phosphor_rgb(v)
        return Frame(width, height, data)
