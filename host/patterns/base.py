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
"""Pattern protocol and a name -> factory registry.

A pattern renders into an abstract :class:`~host.frame.Frame` and never knows what
hardware drives it (design spec section 3).

- *Procedural* patterns compute per normalized ``(x/w, y/h, t)`` and are valid at any
  geometry (``procedural = True``, ``native_size = None``).
- *Fixed-asset* patterns declare a ``native_size`` and are only valid on matching
  geometry (``procedural = False``). The orchestrator enforces this.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Protocol, Tuple, runtime_checkable

from host.frame import Frame


@runtime_checkable
class Pattern(Protocol):
    """Anything that can render a frame at a requested geometry and time."""

    #: True -> renders at any geometry; False -> only at ``native_size``.
    procedural: bool
    #: ``(width, height)`` for fixed-asset patterns, else ``None``.
    native_size: Optional[Tuple[int, int]]

    def render(self, width: int, height: int, t: float) -> Frame:
        """Render one frame for time ``t`` (seconds) at ``width`` x ``height``."""
        ...


# Registry of pattern name -> factory. A factory is any callable returning a Pattern
# (typically the pattern class itself). The CLI resolves ``--pattern NAME`` through this.
PATTERNS: Dict[str, Callable[..., Pattern]] = {}


def register(name: str) -> Callable[[Callable[..., Pattern]], Callable[..., Pattern]]:
    """Class/factory decorator that records it in :data:`PATTERNS` under ``name``."""

    def decorator(factory: Callable[..., Pattern]) -> Callable[..., Pattern]:
        if name in PATTERNS:
            raise ValueError(f"pattern name {name!r} already registered")
        PATTERNS[name] = factory
        return factory

    return decorator


def get_pattern(name: str, **kwargs) -> Pattern:
    """Instantiate the registered pattern ``name`` with ``kwargs``."""
    try:
        factory = PATTERNS[name]
    except KeyError:
        available = ", ".join(sorted(PATTERNS)) or "(none registered)"
        raise KeyError(f"unknown pattern {name!r}; available: {available}") from None
    return factory(**kwargs)
