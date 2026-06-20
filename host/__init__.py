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
"""Blitzen host: drive heterogeneous networked LED displays from one process.

Generality lives here, not in the firmware. Patterns render into a logical row-major
RGB888 :class:`~host.frame.Frame`; the orchestrator pushes frames to each target's
transport. The live path is unified on DDP; standalone playback uses each device's
native mechanism (M0 slot ring, WLED presets).
"""

__version__ = "0.1.0"
