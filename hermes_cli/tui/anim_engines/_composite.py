"""Composite/crossfade animation engines."""
from __future__ import annotations

from ._base import AnimParams, _layer_frames


class CompositeEngine:
    """Layers multiple engines and blends their frames."""

    def __init__(self, layers: list, blend_mode: str = "overlay") -> None:
        self.layers = layers
        self.blend_mode = blend_mode

    def next_frame(self, params: AnimParams) -> str:
        if not self.layers:
            return ""
        frames = [e.next_frame(params) for e in self.layers]
        result = frames[0]
        for f in frames[1:]:
            result = _layer_frames(result, f, self.blend_mode, params.heat)
        return result


class CrossfadeEngine:
    """Smooth crossfade transition between two engines."""

    def __init__(self, engine_a: object, engine_b: object, speed: float = 0.04) -> None:
        self.engine_a = engine_a
        self.engine_b = engine_b
        self.progress = 0.0
        self.speed = speed

    def next_frame(self, params: AnimParams) -> str:
        if self.progress >= 1.0:
            return self.engine_b.next_frame(params)
        fa = self.engine_a.next_frame(params)
        fb = self.engine_b.next_frame(params)
        self.progress = min(1.0, self.progress + self.speed)
        return _layer_frames(fa, fb, "overlay")
