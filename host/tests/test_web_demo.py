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
"""The web playground renders through the real pattern registry."""

import pytest

from host.patterns import PATTERNS
from host.tools.web_demo import MAX_DIM, pattern_specs, render_frame


def test_specs_cover_every_registered_pattern():
    names = {spec["name"] for spec in pattern_specs()}
    assert names == set(PATTERNS)


def test_specs_expose_constructor_params():
    by_name = {spec["name"]: spec["params"] for spec in pattern_specs()}
    plasma = {p["name"]: p for p in by_name["plasma"]}
    assert plasma["scale"]["kind"] == "float"
    assert plasma["scale"]["default"] == pytest.approx(8.0)
    # solid's color tuple becomes a color picker, not a slider.
    solid = {p["name"]: p for p in by_name["solid"]}
    assert solid["color"]["kind"] == "color"


def test_render_frame_returns_rgb888_bytes():
    body = render_frame("plasma", 8, 32, 0.5, {})
    assert len(body) == 8 * 32 * 3


def test_render_frame_clamps_oversized_geometry():
    body = render_frame("solid", 9999, 1, 0.0, {})
    assert len(body) == MAX_DIM * 1 * 3


def test_render_frame_applies_query_params():
    red = render_frame("solid", 2, 2, 0.0, {"p_color": "ff0000"})
    assert red[:3] == bytes((255, 0, 0))


def test_render_frame_ignores_bad_params():
    # A malformed value must fall back to the constructor default, not raise.
    body = render_frame("plasma", 4, 4, 0.0, {"p_scale": "not-a-number"})
    assert len(body) == 4 * 4 * 3


def test_render_frame_unknown_pattern_raises():
    with pytest.raises(KeyError):
        render_frame("does-not-exist", 4, 4, 0.0, {})
