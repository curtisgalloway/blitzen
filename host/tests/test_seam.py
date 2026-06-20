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
"""The extension seam (acceptance): a new display type needs no pattern changes.

``StubTarget`` + ``_MemoryTransport`` were added without touching any pattern or the
orchestrator. These tests drive that brand-new target type with unmodified patterns.
"""

from host.orchestrator import Orchestrator
from host.patterns import get_pattern
from host.patterns.base import Pattern
from host.targets import DisplayTarget, StubTarget, _MemoryTransport
from host.transports.base import Transport


def test_new_target_driven_by_unmodified_pattern():
    pattern = get_pattern("plasma")
    target = StubTarget("virt", 32, 32)
    orch = Orchestrator()
    orch.assign(target, pattern)
    orch.tick(1.0)
    assert len(target.received) == 1
    # The frame the new target captured is exactly what the pattern produced.
    assert target.received[0] == pattern.render(32, 32, 1.0)


def test_same_pattern_drives_two_geometries():
    pattern = get_pattern("plasma")
    panel = StubTarget("panel", 32, 32)
    array = StubTarget("array", 8, 32)
    orch = Orchestrator()
    orch.assign(panel, pattern)
    orch.assign(array, pattern)
    orch.tick(0.5)
    assert (panel.received[0].width, panel.received[0].height) == (32, 32)
    assert (array.received[0].width, array.received[0].height) == (8, 32)


def test_memory_transport_satisfies_transport_protocol():
    assert isinstance(_MemoryTransport(), Transport)


def test_stub_target_is_a_display_target():
    assert isinstance(StubTarget("x", 8, 8), DisplayTarget)


def test_registered_patterns_satisfy_protocol():
    for name in ("plasma", "scroll", "solid", "gradient"):
        assert isinstance(get_pattern(name), Pattern)
