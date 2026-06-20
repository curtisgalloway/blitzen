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
"""Fixed-asset patterns: load a still image or animation (PNG/GIF/...) via Pillow.

Unlike procedural patterns these declare a ``native_size`` and are only valid at that
geometry (``procedural = False``); the orchestrator rejects a mismatch. They feed both the
live path (``render``) and the M0 store path (``frames`` / ``durations`` -> encoder).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PIL import Image, ImageSequence

from host.frame import Frame

# Fallback per-frame duration for animations whose source carries no timing metadata.
_DEFAULT_FRAME_SECONDS = 0.1


def _pil_to_frame(img: "Image.Image") -> Frame:
    """Convert a PIL image to a row-major RGB888 :class:`Frame`."""
    rgb = img.convert("RGB")
    width, height = rgb.size
    return Frame(width, height, bytearray(rgb.tobytes()))


class AssetPattern:
    """One or more equally-sized frames with per-frame durations (seconds).

    A still image is just a one-frame asset. ``render(t)`` walks the timeline so the same
    object can be live-streamed; ``frames``/``durations`` expose the raw frames for upload.
    """

    procedural = False

    def __init__(self, frames: List[Frame], durations: List[float]) -> None:
        if not frames:
            raise ValueError("AssetPattern requires at least one frame")
        if len(frames) != len(durations):
            raise ValueError("frames and durations must be the same length")
        size = (frames[0].width, frames[0].height)
        if any((f.width, f.height) != size for f in frames):
            raise ValueError("all asset frames must share one geometry")
        self.frames = frames
        self.durations = durations
        self.native_size: Optional[Tuple[int, int]] = size
        self._total = sum(durations)

    def render(self, width: int, height: int, t: float) -> Frame:
        if (width, height) != self.native_size:
            raise ValueError(
                f"asset is {self.native_size[0]}x{self.native_size[1]}, "
                f"cannot render at {width}x{height}"
            )
        if len(self.frames) == 1 or self._total <= 0:
            return self.frames[0].copy()
        tt = t % self._total
        acc = 0.0
        for frame, dur in zip(self.frames, self.durations):
            acc += dur
            if tt < acc:
                return frame.copy()
        return self.frames[-1].copy()


def load_asset(
    path: str, target_size: Optional[Tuple[int, int]] = None
) -> AssetPattern:
    """Load an image/animation from ``path`` into an :class:`AssetPattern`.

    If ``target_size`` is given each frame is resized to it (e.g. to match a panel);
    otherwise the asset keeps its native pixel size.
    """
    frames: List[Frame] = []
    durations: List[float] = []
    with Image.open(path) as img:
        for src in ImageSequence.Iterator(img):
            pic = src.convert("RGB")
            if target_size is not None:
                pic = pic.resize(target_size)
            frames.append(_pil_to_frame(pic))
            durations.append(src.info.get("duration", 0) / 1000.0)
    if len(frames) > 1 and sum(durations) <= 0:
        durations = [_DEFAULT_FRAME_SECONDS] * len(frames)
    return AssetPattern(frames, durations)
