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
"""Orchestrator: geometry validation and the per-target fps scheduler."""

import pytest
from _fakes import FakeClock

from host.frame import Frame
from host.orchestrator import Orchestrator
from host.patterns import get_pattern
from host.targets import StubTarget


class _FixedPattern:
    """A fake fixed-asset pattern locked to one geometry."""

    procedural = False

    def __init__(self, size):
        self.native_size = size

    def render(self, width, height, t):
        return Frame.blank(width, height)


def test_fixed_pattern_geometry_mismatch_rejected():
    orch = Orchestrator()
    with pytest.raises(ValueError):
        orch.assign(StubTarget("arr", 8, 32), _FixedPattern((32, 32)))


def test_fixed_pattern_matching_geometry_ok():
    orch = Orchestrator()
    orch.assign(StubTarget("panel", 32, 32), _FixedPattern((32, 32)))
    assert len(orch.assignments) == 1


def test_procedural_pattern_any_geometry_ok():
    orch = Orchestrator()
    orch.assign(StubTarget("arr", 8, 32), get_pattern("plasma"))
    assert len(orch.assignments) == 1


def test_tick_drives_each_assignment_once():
    orch = Orchestrator()
    target = StubTarget("a", 16, 16)
    orch.assign(target, get_pattern("solid"))
    orch.tick(0.0)
    assert len(target.received) == 1


def test_scheduler_hits_target_at_fps():
    clock = FakeClock()
    orch = Orchestrator(clock=clock.now, sleep=clock.sleep)
    target = StubTarget("a", 8, 8)
    orch.assign(target, get_pattern("solid"))
    orch.run(fps=8, duration=1.0)
    assert len(target.received) == 8


def test_scheduler_concurrent_different_fps():
    clock = FakeClock()
    orch = Orchestrator(clock=clock.now, sleep=clock.sleep)
    fast = StubTarget("fast", 8, 8)
    slow = StubTarget("slow", 8, 8)
    orch.assign(fast, get_pattern("solid"), fps=8)
    orch.assign(slow, get_pattern("solid"), fps=4)
    orch.run(fps=8, duration=1.0)
    assert len(fast.received) == 8
    assert len(slow.received) == 4


def test_run_with_no_assignments_is_noop():
    Orchestrator().run(fps=10, duration=1.0)  # must not hang or raise


def test_assign_rejects_nonpositive_fps():
    orch = Orchestrator()
    with pytest.raises(ValueError):
        orch.assign(StubTarget("a", 8, 8), get_pattern("solid"), fps=0)
