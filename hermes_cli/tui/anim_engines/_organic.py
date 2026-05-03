"""Organic-family animation engines: NeuralPulseEngine, FlockSwarmEngine, ConwayLifeEngine."""
from __future__ import annotations

import math
import random

from ._base import (
    AnimParams,
    _BOID_CELL_SIZE,
    _BaseEngine,
    _make_canvas,
    _make_trail_canvas,
    _safe_dims,
)


class NeuralPulseEngine(_BaseEngine):
    """Directed graph of nodes; charge propagates and fires in cascades."""

    def __init__(self) -> None:
        self._nodes: list[tuple[float, float]] = []
        self._edges: dict[int, list[int]] = {}
        self._charge: list[float] = []
        self._fire_queue: list[int] = []
        self._edge_steps: dict[tuple[int, int], int] = {}
        self._init_done = False
        self._w = 0
        self._h = 0
        self._extra_fires = 0  # set by on_signal
        self._slow_decay_ticks: int = 0  # for "complete" slow-decay

    def _init(self, w: int, h: int, n: int) -> None:
        import random as _r
        self._nodes = [(_r.random() * w, _r.random() * h) for _ in range(n)]
        # knn graph k=3
        self._edges = {}
        for i, (ax, ay) in enumerate(self._nodes):
            dists = []
            for j, (bx, by) in enumerate(self._nodes):
                if i != j:
                    dists.append((math.hypot(ax - bx, ay - by), j))
            dists.sort()
            self._edges[i] = [j for _, j in dists[:3]]
        self._charge = [0.0] * n
        # Cache edge step lengths to avoid per-frame hypot recomputation
        self._edge_steps = {}
        for i, (ax, ay) in enumerate(self._nodes):
            for j in self._edges[i]:
                bx, by = self._nodes[j]
                self._edge_steps[(i, j)] = max(int(math.hypot(bx - ax, by - ay)), 1)
        self._w = w
        self._h = h
        self._init_done = True

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "thinking":
            self._extra_fires = int(value * 3)
        elif signal == "reasoning":
            self._extra_fires = 1
        elif signal == "tool":
            # Boost charge in random 5 nodes immediately
            if self._nodes:
                for _ in range(min(5, len(self._nodes))):
                    idx = random.randrange(len(self._nodes))
                    self._fire_queue.append(idx)
        elif signal == "complete":
            # Halve charge decay rate for 20 ticks (slow settle)
            self._slow_decay_ticks = 20
            self._fire_queue = list(range(len(self._nodes)))
        elif signal == "error":
            # Discharge all nodes → silence
            self._charge = [0.0] * len(self._charge)
            self._fire_queue = []

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        n = max(5, min(50, params.particle_count // 3))
        if not self._init_done or len(self._nodes) != n or self._w != w or self._h != h:
            self._init(w, h, n)
        canvas = _make_trail_canvas(params.trail_decay) if params.trail_decay > 0 else _make_canvas()

        fire_rate = 0.05 + params.heat * 0.3
        if random.random() < fire_rate:
            self._fire_queue.append(random.randrange(len(self._nodes)))
        for _ in range(self._extra_fires):
            self._fire_queue.append(random.randrange(len(self._nodes)))
        self._extra_fires = 0

        new_queue: list[int] = []
        for node_i in set(self._fire_queue):
            nx, ny = self._nodes[node_i]
            ix, iy = int(nx), int(ny)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if 0 <= ix + dx < w and 0 <= iy + dy < h:
                        canvas.set(ix + dx, iy + dy)
            for nb in self._edges.get(node_i, []):
                self._charge[nb] += 0.4
        self._fire_queue = []

        decay_rate = 0.4 if self._slow_decay_ticks > 0 else 0.8
        if self._slow_decay_ticks > 0:
            self._slow_decay_ticks -= 1
        for i, c in enumerate(self._charge):
            if c > 1.0:
                new_queue.append(i)
                self._charge[i] = 0.0
            else:
                self._charge[i] *= decay_rate
        self._fire_queue = new_queue

        # Draw edges
        for i, (ax, ay) in enumerate(self._nodes):
            for j in self._edges.get(i, []):
                bx, by = self._nodes[j]
                steps = self._edge_steps.get((i, j), 1)
                for s in range(0, steps, 2):
                    fx = ax + (bx - ax) * s / steps
                    fy = ay + (by - ay) * s / steps
                    if 0 <= int(fx) < w and 0 <= int(fy) < h:
                        canvas.set(int(fx), int(fy))

        return canvas.frame() if hasattr(canvas, "frame") else ""


class FlockSwarmEngine(_BaseEngine):
    """Reynolds boids with toroidal wrap and wandering attractor."""

    def __init__(self) -> None:
        self._boids: list[list[float]] = []  # [x, y, vx, vy]
        self._attractor = [0.0, 0.0]
        self._attr_vel = [0.5, 0.3]
        self._init_done = False
        self._scatter = False
        self._w: int = 0
        self._h: int = 0
        self._speed_modifier: float = 1.0
        self._grid: dict[tuple[int, int], list[int]] = {}

    def _init(self, w: int, h: int, n: int) -> None:
        self._boids = [
            [random.random() * w, random.random() * h,
             random.uniform(-1, 1), random.uniform(-1, 1)]
            for _ in range(n)
        ]
        self._attractor = [w / 2, h / 2]
        self._w = w
        self._h = h
        self._init_done = True

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "thinking":
            # Move attractor to center, reduce speed 30%
            if self._w > 0 and self._h > 0:
                self._attractor = [self._w / 2, self._h / 2]
            self._speed_modifier = 0.7
        elif signal == "reasoning":
            # Move attractor to top-center
            if self._w > 0 and self._h > 0:
                self._attractor = [self._w / 2, self._h / 4]
        elif signal == "tool":
            # Move attractor to random corner, boost speed 50%
            if self._w > 0 and self._h > 0:
                corner = random.randint(0, 3)
                corners = [
                    [0.0, 0.0],
                    [float(self._w), 0.0],
                    [0.0, float(self._h)],
                    [float(self._w), float(self._h)],
                ]
                self._attractor = corners[corner]
            self._speed_modifier = 1.5
        elif signal == "complete":
            self._scatter = True
            self._speed_modifier = 1.0
        elif signal == "error":
            # Scatter mode; double speed for 10 ticks
            self._scatter = True
            self._speed_modifier *= 2

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        n = max(5, min(100, params.particle_count))
        if not self._init_done or len(self._boids) != n or self._w != w or self._h != h:
            self._init(w, h, n)

        canvas = _make_trail_canvas(0.7) if params.trail_decay <= 0 else _make_trail_canvas(params.trail_decay)

        max_speed = (1.5 + params.heat * 3.0) * self._speed_modifier
        # Move attractor
        self._attractor[0] += self._attr_vel[0]
        self._attractor[1] += self._attr_vel[1]
        if self._attractor[0] < 0 or self._attractor[0] > w:
            self._attr_vel[0] *= -1
        if self._attractor[1] < 0 or self._attractor[1] > h:
            self._attr_vel[1] *= -1

        # Build spatial grid O(n) — reuse dict to avoid per-frame allocation.
        # Uses distinct loop variables (gi, boid) to avoid shadowing the outer
        # steering loop variables (i, b).
        self._grid.clear()
        for gi, boid in enumerate(self._boids):
            key = (int(boid[0] / _BOID_CELL_SIZE), int(boid[1] / _BOID_CELL_SIZE))
            cell = self._grid.get(key)
            if cell is None:
                self._grid[key] = [gi]
            else:
                cell.append(gi)
        # Max cell index for a pixel in [0, w-1] is (w-1)//cell_size; +1 gives count.
        _n_cols = max(1, (w - 1) // _BOID_CELL_SIZE + 1)
        _n_rows = max(1, (h - 1) // _BOID_CELL_SIZE + 1)
        # _n_cols/_n_rows are used by the steering loop below; compute once per frame.

        for i, b in enumerate(self._boids):
            if self._scatter:
                angle = random.random() * 2 * math.pi
                b[2] += math.cos(angle) * 3
                b[3] += math.sin(angle) * 3
                continue

            sep_x = sep_y = 0.0
            ali_x = ali_y = 0.0
            coh_x = coh_y = 0.0
            sep_n = ali_n = coh_n = 0

            bx_cell = int(b[0] / _BOID_CELL_SIZE)
            by_cell = int(b[1] / _BOID_CELL_SIZE)
            for _dc in (-1, 0, 1):
                for _dr in (-1, 0, 1):
                    _nc = bx_cell + _dc
                    _nr = by_cell + _dr
                    if _nc < 0 or _nc >= _n_cols or _nr < 0 or _nr >= _n_rows:
                        continue
                    for j in self._grid.get((_nc, _nr), ()):
                        if j == i:
                            continue
                        other = self._boids[j]
                        dx = other[0] - b[0]
                        dy = other[1] - b[1]
                        dist = math.hypot(dx, dy)
                        if dist < 8:
                            sep_x -= dx / max(dist, 0.1)
                            sep_y -= dy / max(dist, 0.1)
                            sep_n += 1
                        if dist < 16:
                            ali_x += other[2]
                            ali_y += other[3]
                            ali_n += 1
                        if dist < 20:
                            coh_x += other[0]
                            coh_y += other[1]
                            coh_n += 1

            if sep_n > 0:
                b[2] += sep_x / sep_n * 0.1
                b[3] += sep_y / sep_n * 0.1
            if ali_n > 0:
                b[2] += (ali_x / ali_n - b[2]) * 0.05
                b[3] += (ali_y / ali_n - b[3]) * 0.05
            if coh_n > 0:
                b[2] += (coh_x / coh_n - b[0]) * 0.01
                b[3] += (coh_y / coh_n - b[1]) * 0.01

            # Attractor pull
            ax, ay = self._attractor
            b[2] += (ax - b[0]) * 0.001
            b[3] += (ay - b[1]) * 0.001

        self._scatter = False

        for b in self._boids:
            spd = math.hypot(b[2], b[3])
            if spd > max_speed:
                b[2] = b[2] / spd * max_speed
                b[3] = b[3] / spd * max_speed
            b[0] = (b[0] + b[2]) % w
            b[1] = (b[1] + b[3]) % h
            if 0 <= int(b[0]) < w and 0 <= int(b[1]) < h:
                canvas.set(int(b[0]), int(b[1]))

        return canvas.frame() if hasattr(canvas, "frame") else ""


class ConwayLifeEngine(_BaseEngine):
    """Conway's Game of Life in braille pixel space, set-based."""

    _GOSPER_GUN = [
        (24, 0), (22, 1), (24, 1),
        (12, 2), (13, 2), (20, 2), (21, 2), (34, 2), (35, 2),
        (11, 3), (15, 3), (20, 3), (21, 3), (34, 3), (35, 3),
        (0, 4), (1, 4), (10, 4), (16, 4), (20, 4), (21, 4),
        (0, 5), (1, 5), (10, 5), (14, 5), (16, 5), (17, 5), (22, 5), (24, 5),
        (10, 6), (16, 6), (24, 6),
        (11, 7), (15, 7),
        (12, 8), (13, 8),
    ]
    _ACORN = [(0, 2), (1, 0), (1, 2), (3, 1), (4, 2), (5, 2), (6, 2)]
    _R_PENTOMINO = [(1, 0), (2, 0), (0, 1), (1, 1), (1, 2)]

    def __init__(self) -> None:
        self._alive: set[tuple[int, int]] = set()
        self._peak = 1
        self._ticks = 0
        self._gens_per_tick = 1
        self._init_done = False
        self._w = 0
        self._h = 0

    def _seed(self, seed: str, w: int, h: int) -> None:
        cx, cy = w // 2 - 18, h // 2 - 5
        if seed == "gosper":
            self._alive = {(cx + x, cy + y) for x, y in self._GOSPER_GUN}
        elif seed == "acorn":
            cx, cy = w // 2, h // 2
            self._alive = {(cx + x, cy + y) for x, y in self._ACORN}
        elif seed == "puffer":
            # Simple puffer (block + glider combos)
            self._alive = {(cx + x, cy + y) for x, y in self._GOSPER_GUN}
            for i in range(5):
                self._alive.add((cx + 40 + i * 3, cy + 5))
        else:  # random
            self._alive = {
                (random.randrange(w), random.randrange(h))
                for _ in range(w * h // 8)
            }

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._gens_per_tick = max(1, self._ticks % 3)
        elif signal == "tool":
            self._gens_per_tick = 2
        elif signal == "error":
            # Re-seed with R-pentomino
            if self._w > 0 and self._h > 0:
                cx, cy = self._w // 2, self._h // 2
                self._alive = {((cx + x) % self._w, (cy + y) % self._h) for x, y in self._R_PENTOMINO}

    def _step(self, w: int, h: int) -> None:
        neighbor_counts: dict[tuple[int, int], int] = {}
        for cx, cy in self._alive:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nb = ((cx + dx) % w, (cy + dy) % h)
                    neighbor_counts[nb] = neighbor_counts.get(nb, 0) + 1
        new_alive: set[tuple[int, int]] = set()
        for cell, cnt in neighbor_counts.items():
            if cnt == 3 or (cnt == 2 and cell in self._alive):
                new_alive.add(cell)
        self._alive = new_alive

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        if not self._init_done or self._w != w or self._h != h:
            self._w, self._h = w, h
            self._seed(params.life_seed, w, h)
            self._init_done = True

        for _ in range(self._gens_per_tick):
            self._step(w, h)

        # Dead board reseed (D5)
        if len(self._alive) == 0 and self._ticks % 60 == 0:
            cx, cy = w // 2, h // 2
            self._alive = {
                (cx - 1, cy),
                (cx,     cy - 1),
                (cx,     cy),
                (cx,     cy + 1),
                (cx + 1, cy + 1),
            }

        # Anti-stagnation
        alive_count = len(self._alive)
        if alive_count > self._peak:
            self._peak = alive_count
        if self._peak > 0 and alive_count < self._peak * 0.05:
            rx, ry = random.randrange(w), random.randrange(h)
            for x, y in self._R_PENTOMINO:
                self._alive.add(((rx + x) % w, (ry + y) % h))
        if alive_count > w * h * 0.8:
            self._alive = {c for c in self._alive if random.random() < 0.5}

        self._ticks += 1
        canvas = _make_canvas()
        for x, y in self._alive:
            if 0 <= x < w and 0 <= y < h:
                canvas.set(x, y)
        return canvas.frame()
