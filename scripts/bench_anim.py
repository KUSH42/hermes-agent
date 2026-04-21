"""Before/after benchmark for drawille animation optimisations."""
import math, time, statistics
from hermes_cli.tui.anim_engines import (
    AnimParams, PerlinFlowEngine, FluidFieldEngine, WaveInterferenceEngine,
    NeuralPulseEngine, FlockSwarmEngine, AuroraRibbonEngine, MandalaBloomEngine,
    LissajousWeaveEngine, _layer_frames,
)
from hermes_cli.tui.drawille_overlay import DrawilleOverlay

REPS = 200
W, H = 120, 40  # typical terminal braille pixel dims (60 cols × 2, 10 rows × 4)
PARAMS = AnimParams(width=W, height=H, t=0.0, dt=1/15, particle_count=60, heat=0.5)

def bench(name, fn):
    # warmup
    for _ in range(10):
        fn()
    times = []
    for i in range(REPS):
        PARAMS.t = i * PARAMS.dt
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(times)
    p95 = sorted(times)[int(REPS * 0.95)]
    print(f"{name:<40} median={med:.3f}ms  p95={p95:.3f}ms")

engines = [
    ("PerlinFlowEngine",       PerlinFlowEngine()),
    ("FluidFieldEngine",       FluidFieldEngine()),
    ("WaveInterferenceEngine", WaveInterferenceEngine()),
    ("NeuralPulseEngine",      NeuralPulseEngine()),
    ("AuroraRibbonEngine",     AuroraRibbonEngine()),
    ("MandalaBloomEngine",     MandalaBloomEngine()),
    ("LissajousWeaveEngine",   LissajousWeaveEngine()),
]
for name, eng in engines:
    bench(name, lambda e=eng: e.next_frame(PARAMS))

# _layer_frames composite cost (2 layers)
pf = PerlinFlowEngine(); wi = WaveInterferenceEngine()
bench("_layer_frames (2 engines, overlay)", lambda: _layer_frames(
    pf.next_frame(PARAMS), wi.next_frame(PARAMS), "overlay", 0.5))
