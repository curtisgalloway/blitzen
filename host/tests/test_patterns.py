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
"""Procedural patterns render correctly at any geometry, from the same code."""

import pytest

from host.frame import Frame
from host.patterns import PATTERNS, get_pattern
from host.patterns.base import Pattern

# The handoff requires correct rendering at both the 32x32 panel and the 8x32 array.
GEOMETRIES = [(32, 32), (8, 32), (1, 1)]
NAMES = sorted(PATTERNS)


def test_expected_patterns_registered():
    assert {"plasma", "scroll", "solid", "gradient"} <= set(PATTERNS)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("size", GEOMETRIES)
def test_renders_valid_frame_at_geometry(name, size):
    width, height = size
    pattern = get_pattern(name)
    frame = pattern.render(width, height, 0.7)
    assert isinstance(frame, Frame)
    assert (frame.width, frame.height) == (width, height)
    assert len(frame.data) == width * height * 3


@pytest.mark.parametrize("name", NAMES)
def test_render_is_deterministic(name):
    a = get_pattern(name).render(8, 32, 1.25)
    b = get_pattern(name).render(8, 32, 1.25)
    assert a == b


@pytest.mark.parametrize("name", ["plasma", "scroll"])
def test_animation_changes_over_time(name):
    pattern = get_pattern(name)
    assert pattern.render(32, 32, 0.0) != pattern.render(32, 32, 2.0)


def test_patterns_satisfy_protocol():
    assert isinstance(get_pattern("plasma"), Pattern)


def test_get_unknown_pattern_raises():
    with pytest.raises(KeyError):
        get_pattern("does-not-exist")
