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
"""The tick loop: render each target's frame at its geometry and push it live.

One single-threaded scheduler drives every target. Each assignment has its own period, so
targets can run at the same or different fps concurrently (handoff acceptance criterion).
Single-threaded keeps patterns free of locking; UDP sends do not block meaningfully. The
clock and sleep are injectable so the scheduler is deterministically testable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from host.frame import Frame
from host.patterns.base import Pattern
from host.targets import DisplayTarget


@dataclass
class _Assignment:
    target: DisplayTarget
    pattern: Pattern
    period: Optional[float]  # seconds between frames; None -> use the run() default
    next_due: float = 0.0


class Orchestrator:
    """Holds (target, pattern) assignments and drives them on a frame clock."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._assignments: List[_Assignment] = []
        self._clock = clock
        self._sleep = sleep

    def assign(
        self, target: DisplayTarget, pattern: Pattern, fps: Optional[float] = None
    ) -> "Orchestrator":
        """Bind ``pattern`` to ``target``. Validates geometry for fixed-asset patterns."""
        if not getattr(pattern, "procedural", True):
            if pattern.native_size != target.geometry:
                raise ValueError(
                    f"fixed pattern {pattern.native_size} cannot drive target "
                    f"{target.name} {target.geometry}"
                )
        if fps is not None and fps <= 0:
            raise ValueError("fps must be positive")
        period = (1.0 / fps) if fps else None
        self._assignments.append(_Assignment(target, pattern, period))
        return self

    @property
    def assignments(self) -> List[_Assignment]:
        return self._assignments

    def tick(self, t: float) -> None:
        """Render and push every assignment once at scene time ``t`` (seconds)."""
        for a in self._assignments:
            frame = a.pattern.render(a.target.width, a.target.height, t)
            a.target.send_live(frame)

    def run(self, fps: float = 30.0, duration: Optional[float] = None) -> None:
        """Drive all assignments until ``duration`` seconds elapse (or forever if None)."""
        if fps <= 0:
            raise ValueError("fps must be positive")
        if not self._assignments:
            return
        default_period = 1.0 / fps
        start = self._clock()
        for a in self._assignments:
            if a.period is None:
                a.period = default_period
            a.next_due = start

        while True:
            now = self._clock()
            t = now - start
            if duration is not None and t >= duration:
                return
            for a in self._assignments:
                if now >= a.next_due:
                    frame = a.pattern.render(a.target.width, a.target.height, t)
                    a.target.send_live(frame)
                    a.next_due += a.period
                    if a.next_due <= now:  # fell behind; resync to avoid a burst
                        a.next_due = now + a.period
            next_due = min(a.next_due for a in self._assignments)
            sleep_for = next_due - self._clock()
            if duration is not None:
                sleep_for = min(sleep_for, (start + duration) - self._clock())
            if sleep_for > 0:
                self._sleep(sleep_for)

    def close(self) -> None:
        for a in self._assignments:
            a.target.close()
