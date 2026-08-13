import sys
import os
import time
import asyncio
from typing import Dict, Any

# Ensure project directory is in PATH
PROJECT_ROOT = r"C:\Users\denpo\OneDrive\Desktop\Project2"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import (
    load_dataset,
    _new_rf,
    get_tele_nursing_dispatcher,
    create_app,
    evaluate_rf,
    STATUS_TEXT_MAP,
)
from fastapi.testclient import TestClient

def measure_server_startup(iterations: int = 5) -> Dict[str, Any]:
    print("--- 1. Measuring Server Startup Latency ---")
    startup_times = []
    dataset_times = []
    fit_times = []
    app_creation_times = []

    for i in range(iterations):
        t0 = time.perf_counter()
        ds = load_dataset("kalman", False, verbose=False)
        t1 = time.perf_counter()
        model = _new_rf(42).fit(ds.X, ds.y) if ds is not None and len(ds.X) > 0 else None
        t2 = time.perf_counter()
        holder = {
            "model": model,
            "use_gradient": False,
            "calibration": "kalman",
            "dispatcher": get_tele_nursing_dispatcher(),
        }
        app = create_app(holder)
        t3 = time.perf_counter()

        dt_ds = (t1 - t0) * 1000
        dt_fit = (t2 - t1) * 1000
        dt_app = (t3 - t2) * 1000
        dt_total = (t3 - t0) * 1000

        dataset_times.append(dt_ds)
        fit_times.append(dt_fit)
        app_creation_times.append(dt_app)
        startup_times.append(dt_total)

        print(f"  Run {i+1}: dataset={dt_ds:.2f}ms, fit={dt_fit:.2f}ms, app_create={dt_app:.2f}ms -> TOTAL={dt_total:.2f}ms")

    avg_startup = sum(startup_times) / len(startup_times)
    max_startup = max(startup_times)
    min_startup = min(startup_times)

    print(f"  Summary: Min={min_startup:.2f}ms, Max={max_startup:.2f}ms, Avg={avg_startup:.2f}ms")
    print(f"  Target: < 1000.0ms | PASS: {max_startup < 1000.0}\n")
    
    return {
        "avg_ms": avg_startup,
        "max_ms": max_startup,
        "min_ms": min_startup,
        "all_ms": startup_times,
        "pass": max_startup < 1000.0,
    }

async def measure_tele_nursing_latency(iterations: int = 10) -> Dict[str, Any]:
    print("--- 2. Measuring Tele-Nursing Alert Latency ---")
    ds = load_dataset("kalman", False, verbose=False)
    model = _new_rf(42).fit(ds.X, ds.y) if ds is not None and len(ds.X) > 0 else None
    dispatcher = get_tele_nursing_dispatcher()
    holder = {
        "model": model,
        "use_gradient": False,
        "calibration": "kalman",
        "dispatcher": dispatcher,
    }
    app = create_app(holder)
    client = TestClient(app)

    # Endpoint latency
    test_alert_times = []
    for i in range(iterations):
        t0 = time.perf_counter()
        resp = client.post("/api/tele-nursing/test-alert", json={
            "bed_number": "Bed-01",
            "severity_level": 3,
            "status": STATUS_TEXT_MAP[3],
            "cpri_percent": 98.5,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rbf_summary": "Benchmark Test Snapshot",
        })
        t1 = time.perf_counter()
        assert resp.status_code == 200
        dt = (t1 - t0) * 1000
        test_alert_times.append(dt)

    avg_alert_endpoint = sum(test_alert_times) / len(test_alert_times)
    max_alert_endpoint = max(test_alert_times)
    print(f"  /api/tele-nursing/test-alert Latency over {iterations} runs: Avg={avg_alert_endpoint:.2f}ms, Max={max_alert_endpoint:.2f}ms")

    # check_and_trigger_async execution latency
    trigger_times = []
    frame_data = {
        "severity_level": 3,
        "status": STATUS_TEXT_MAP[3],
        "cpri_percent": 99.0,
        "deltas": [-400] * 5 + [0] * 20,
        "rbf_matrix": [[0.0] * 60] * 80,
    }
    for i in range(iterations):
        # ensure cooldown doesn't skip
        dispatcher.last_dispatch_time = 0.0
        t0 = time.perf_counter()
        dispatcher.check_and_trigger_async(frame_data)
        t1 = time.perf_counter()
        dt = (t1 - t0) * 1000
        trigger_times.append(dt)

    avg_trigger = sum(trigger_times) / len(trigger_times)
    max_trigger = max(trigger_times)
    print(f"  check_and_trigger_async Latency over {iterations} runs: Avg={avg_trigger:.3f}ms, Max={max_trigger:.3f}ms")

    # Direct dispatch_alert coroutine latency
    direct_dispatch_times = []
    payload = {
        "bed_number": "Bed-01",
        "severity_level": 3,
        "status": STATUS_TEXT_MAP[3],
        "cpri_percent": 98.5,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rbf_summary": "Benchmark Test Direct Dispatch",
    }
    for i in range(iterations):
        t0 = time.perf_counter()
        res = await dispatcher.dispatch_alert(payload)
        t1 = time.perf_counter()
        dt = (t1 - t0) * 1000
        direct_dispatch_times.append(dt)

    avg_dispatch = sum(direct_dispatch_times) / len(direct_dispatch_times)
    max_dispatch = max(direct_dispatch_times)
    print(f"  dispatch_alert Coroutine Latency over {iterations} runs: Avg={avg_dispatch:.2f}ms, Max={max_dispatch:.2f}ms")

    passed = max_alert_endpoint < 500.0 and max_trigger < 500.0 and max_dispatch < 500.0
    print(f"  Target: < 500.0ms | PASS: {passed}\n")

    return {
        "endpoint_avg_ms": avg_alert_endpoint,
        "endpoint_max_ms": max_alert_endpoint,
        "trigger_avg_ms": avg_trigger,
        "trigger_max_ms": max_trigger,
        "dispatch_avg_ms": avg_dispatch,
        "dispatch_max_ms": max_dispatch,
        "pass": passed,
    }

def measure_logocv_accuracy() -> Dict[str, Any]:
    print("--- 3. Measuring LOGO-CV Model Accuracy ---")
    # Base configuration (gradient=False)
    ds_base = load_dataset("kalman", False, verbose=False)
    rf_base = evaluate_rf(ds_base, seeds=[42], cv="file", verbose=False)
    acc_base = rf_base["accuracy_mean"] * 100.0
    macro_f1_base = rf_base["macro_f1_mean"]

    # Gradient-enhanced configuration (gradient=True)
    ds_grad = load_dataset("kalman", True, verbose=False)
    rf_grad = evaluate_rf(ds_grad, seeds=[42], cv="file", verbose=False)
    acc_grad = rf_grad["accuracy_mean"] * 100.0
    macro_f1_grad = rf_grad["macro_f1_mean"]

    print(f"  Default (Kalman, Base features 9D): Accuracy = {acc_base:.2f}% (Macro F1: {macro_f1_base:.4f})")
    print(f"  Enhanced (Kalman, Spatial Gradient 11D): Accuracy = {acc_grad:.2f}% (Macro F1: {macro_f1_grad:.4f})")
    print(f"  Target: >= 95.0% | PASS (Enhanced): {acc_grad >= 95.0} | PASS (Default): {acc_base >= 95.0}\n")

    return {
        "base_accuracy_pct": acc_base,
        "base_macro_f1": macro_f1_base,
        "grad_accuracy_pct": acc_grad,
        "grad_macro_f1": macro_f1_grad,
        "pass": acc_grad >= 95.0,
    }

async def run_all_benchmarks():
    t_start = time.perf_counter()
    startup_res = measure_server_startup()
    tele_res = await measure_tele_nursing_latency()
    logocv_res = measure_logocv_accuracy()
    t_end = time.perf_counter()
    print(f"All benchmarks finished in {t_end - t_start:.2f}s")
    return {
        "startup": startup_res,
        "tele_nursing": tele_res,
        "logocv": logocv_res,
    }

if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
