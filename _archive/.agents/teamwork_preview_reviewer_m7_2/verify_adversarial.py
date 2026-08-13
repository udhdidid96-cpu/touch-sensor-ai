import time
import asyncio
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from main import (
    TeleNursingDispatcher,
    TeleNursingConfig,
    SerialFrameSource,
    LivePipeline,
    STATUS_TEXT_MAP,
    signals_to_pads,
    PAD_ORDER,
)
import numpy as np

def test_adversarial_stress():
    print("=== ADVERSARIAL STRESS TEST 1: Rapid Dispatch Trigger (10,000 calls) ===")
    config = TeleNursingConfig(enabled=True, cooldown_seconds=5.0)
    dispatcher = TeleNursingDispatcher(config)
    
    t0 = time.perf_counter()
    for _ in range(10000):
        dispatcher.check_and_trigger_async({
            "severity_level": 3,
            "status": STATUS_TEXT_MAP[3],
            "cpri_percent": 99.0,
            "deltas": [1000] * 25
        })
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"10,000 check_and_trigger_async calls completed in {elapsed:.2f} ms ({elapsed/10000:.6f} ms/call)")
    assert elapsed < 500.0, "Rapid dispatch trigger failed latency test!"

    print("\n=== ADVERSARIAL STRESS TEST 2: Serial Frame Remapping ===")
    raw_25 = np.arange(1, 26, dtype=float)
    mapped = signals_to_pads(raw_25)
    assert len(mapped) == 25
    assert len(PAD_ORDER) == 25
    print(f"Signal-to-pad remapping verified: PAD_ORDER len={len(PAD_ORDER)}.")

    print("\n=== ADVERSARIAL STRESS TEST 3: Pipeline Warmup & Baseline Settling ===")
    pipe = LivePipeline(model=None, warmup_frames=5)
    frame0 = np.full(25, 2000.0)
    out0 = pipe.process(frame0)
    assert out0["warming_up"] == True
    assert out0["severity_level"] == 0, "Frame 0 during warmup must be held at Level 0!"
    print(f"Frame 0 held at Level 0 during baseline warmup (status: '{out0['status']}').")

    for i in range(1, 6):
        out_i = pipe.process(np.full(25, 2000.0))
    assert out_i["warming_up"] == False
    print("Baseline settled after 5 warmup frames; pipeline active.")

    print("\nALL ADVERSARIAL STRESS TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_adversarial_stress()
