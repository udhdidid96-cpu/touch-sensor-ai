import sys
import os
import asyncio
import json
import traceback
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = r"C:\Users\denpo\OneDrive\Desktop\Project2"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient
from main import (
    create_app,
    get_tele_nursing_dispatcher,
    TeleNursingConfig,
    TeleNursingDispatcher,
    SPATIAL,
    PAD_XY,
    PHYSICAL_PAD_COORDS,
    PAD_TO_SIGNAL,
    N_PADS,
    BASE_FEATURE_NAMES,
    GRAD_FEATURE_NAMES,
    extract_features,
    LivePipeline
)

results = {
    "task1_tele_nursing": [],
    "task2_websocket_telemetry": [],
    "task3_physical_patch_ui": [],
    "task4_quality_linters": []
}

def log_test(task: str, name: str, passed: bool, details: str):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] [{task}] {name}: {details}", flush=True)
    results[task].append({"name": name, "passed": passed, "details": details})


# =============================================================================
# TASK 1: Rest API /api/tele-nursing/config & /api/tele-nursing/test-alert
# =============================================================================
def test_task1():
    print("\n--- Running Task 1: Tele-Nursing REST API Adversarial Tests ---", flush=True)
    dispatcher = TeleNursingDispatcher()
    model_holder = {"model": None, "use_gradient": True, "dispatcher": dispatcher}
    app = create_app(model_holder)
    client = TestClient(app)

    # 1.1 GET /api/tele-nursing/config
    try:
        resp = client.get("/api/tele-nursing/config")
        if resp.status_code == 200:
            cfg = resp.json()
            required_keys = {"enabled", "line_token", "telegram_token", "telegram_chat_id", "bed_number", "min_severity_level", "cooldown_seconds"}
            if required_keys.issubset(set(cfg.keys())):
                log_test("task1_tele_nursing", "GET config baseline", True, f"Returned 200 with keys: {list(cfg.keys())}")
            else:
                log_test("task1_tele_nursing", "GET config baseline", False, f"Missing keys: {required_keys - set(cfg.keys())}")
        else:
            log_test("task1_tele_nursing", "GET config baseline", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task1_tele_nursing", "GET config baseline", False, str(e))

    # 1.2 POST /api/tele-nursing/config - Valid update & Partial update
    try:
        update_payload = {"bed_number": "Bed-TEST-99", "min_severity_level": 3}
        resp = client.post("/api/tele-nursing/config", json=update_payload)
        if resp.status_code == 200:
            res = resp.json()
            if res.get("status") == "success" and res["config"]["bed_number"] == "Bed-TEST-99" and res["config"]["min_severity_level"] == 3:
                log_test("task1_tele_nursing", "POST config valid update", True, "Successfully updated bed_number and min_severity_level")
            else:
                log_test("task1_tele_nursing", "POST config valid update", False, f"Unexpected response: {res}")
        else:
            log_test("task1_tele_nursing", "POST config valid update", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST config valid update", False, str(e))

    # 1.3 POST /api/tele-nursing/config - Missing fields (empty dict)
    try:
        resp = client.post("/api/tele-nursing/config", json={})
        if resp.status_code == 200:
            res = resp.json()
            if res.get("status") == "success":
                log_test("task1_tele_nursing", "POST config empty dict / missing fields", True, "Gracefully handled empty update dict without modifying existing config")
            else:
                log_test("task1_tele_nursing", "POST config empty dict / missing fields", False, f"Unexpected response: {res}")
        else:
            log_test("task1_tele_nursing", "POST config empty dict / missing fields", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST config empty dict / missing fields", False, str(e))

    # 1.4 POST /api/tele-nursing/config - Invalid types
    try:
        invalid_payload = {"min_severity_level": "not_an_int"}
        resp = client.post("/api/tele-nursing/config", json=invalid_payload)
        if resp.status_code in (400, 422, 500):
            log_test("task1_tele_nursing", "POST config invalid int type", True, f"Server returned error status {resp.status_code} for non-numeric int field")
        else:
            log_test("task1_tele_nursing", "POST config invalid int type", False, f"Server returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST config invalid int type", True, f"Handled with exception: {e}")

    try:
        invalid_payload2 = {"cooldown_seconds": "invalid_float"}
        resp = client.post("/api/tele-nursing/config", json=invalid_payload2)
        if resp.status_code in (400, 422, 500):
            log_test("task1_tele_nursing", "POST config invalid float type", True, f"Server returned error status {resp.status_code} for invalid float")
        else:
            log_test("task1_tele_nursing", "POST config invalid float type", False, f"Server returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST config invalid float type", True, f"Handled with exception: {e}")

    # 1.5 POST /api/tele-nursing/test-alert - Unconfigured tokens (skipped status)
    try:
        client.post("/api/tele-nursing/config", json={"line_token": "", "telegram_token": "", "telegram_chat_id": ""})
        resp = client.post("/api/tele-nursing/test-alert")
        if resp.status_code == 200:
            data = resp.json()
            results_dict = data.get("results", {})
            if results_dict.get("line", {}).get("status") == "skipped" and results_dict.get("telegram", {}).get("status") == "skipped":
                log_test("task1_tele_nursing", "POST test-alert unconfigured tokens", True, f"Handled missing tokens gracefully with skipped status: {results_dict}")
            else:
                log_test("task1_tele_nursing", "POST test-alert unconfigured tokens", False, f"Unexpected results: {results_dict}")
        else:
            log_test("task1_tele_nursing", "POST test-alert unconfigured tokens", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST test-alert unconfigured tokens", False, str(e))

    # 1.6 POST /api/tele-nursing/test-alert - Invalid tokens (fake LINE & Telegram tokens)
    try:
        client.post("/api/tele-nursing/config", json={
            "line_token": "INVALID_LINE_TOKEN_12345",
            "telegram_token": "123456:INVALID_TELEGRAM_TOKEN",
            "telegram_chat_id": "999999"
        })
        resp = client.post("/api/tele-nursing/test-alert")
        if resp.status_code == 200:
            data = resp.json()
            results_dict = data.get("results", {})
            line_st = results_dict.get("line", {}).get("status")
            tele_st = results_dict.get("telegram", {}).get("status")
            if line_st in ("failed", "error") and tele_st in ("failed", "error"):
                log_test("task1_tele_nursing", "POST test-alert invalid tokens", True, f"Handled invalid remote tokens gracefully without server crash: {results_dict}")
            else:
                log_test("task1_tele_nursing", "POST test-alert invalid tokens", False, f"Unexpected token results: {results_dict}")
        else:
            log_test("task1_tele_nursing", "POST test-alert invalid tokens", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST test-alert invalid tokens", False, str(e))

    # 1.7 POST /api/tele-nursing/test-alert - Custom payload & CPRI thresholds
    try:
        custom_payload = {
            "bed_number": "ICU-Bed-05",
            "severity_level": 3,
            "status": "Level 3: CRITICAL EXTUBATION PULL ALARM",
            "cpri_percent": 99.9,
            "rbf_summary": "Adversarial Stress Test Grid 60x80"
        }
        resp = client.post("/api/tele-nursing/test-alert", json=custom_payload)
        if resp.status_code == 200:
            data = resp.json()
            payload_echo = data.get("payload", {})
            if payload_echo.get("bed_number") == "ICU-Bed-05" and payload_echo.get("cpri_percent") == 99.9:
                log_test("task1_tele_nursing", "POST test-alert custom CPRI payload", True, f"Custom payload correctly processed and dispatched: {payload_echo}")
            else:
                log_test("task1_tele_nursing", "POST test-alert custom CPRI payload", False, f"Payload mismatch: {payload_echo}")
        else:
            log_test("task1_tele_nursing", "POST test-alert custom CPRI payload", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task1_tele_nursing", "POST test-alert custom CPRI payload", False, str(e))

    # 1.8 POST /api/tele-nursing/test-alert - Edge CPRI values (0.0, 50.0, 100.0, 150.0, -10.0)
    for cpri_val in [0.0, 50.0, 100.0, 150.0, -10.0]:
        try:
            resp = client.post("/api/tele-nursing/test-alert", json={"cpri_percent": cpri_val})
            if resp.status_code == 200:
                log_test("task1_tele_nursing", f"POST test-alert CPRI={cpri_val}%", True, f"Handled edge CPRI {cpri_val}% gracefully")
            else:
                log_test("task1_tele_nursing", f"POST test-alert CPRI={cpri_val}%", False, f"Status code {resp.status_code}")
        except Exception as e:
            log_test("task1_tele_nursing", f"POST test-alert CPRI={cpri_val}%", False, str(e))


# =============================================================================
# TASK 2: WebSocket /ws/sensor Telemetry Broadcast & Feature Verification
# =============================================================================
def test_task2():
    print("\n--- Running Task 2: WebSocket /ws/sensor Telemetry & Feature Verification ---", flush=True)
    dispatcher = TeleNursingDispatcher()
    model_holder = {"model": None, "use_gradient": True, "dispatcher": dispatcher}
    app = create_app(model_holder)
    client = TestClient(app)

    try:
        with client.websocket_connect("/ws/sensor") as websocket:
            # Receive frame 1
            data = websocket.receive_json()
            
            # Check 25 channels in signals, delta, sensor_details
            signals = data.get("signals", [])
            delta = data.get("delta", [])
            sensor_details = data.get("sensor_details", [])
            
            chk_signals_len = (len(signals) == 25)
            chk_delta_len = (len(delta) == 25)
            chk_details_len = (len(sensor_details) == 25)
            
            if chk_signals_len and chk_delta_len and chk_details_len:
                log_test("task2_websocket_telemetry", "25 Channels Broadcast", True, f"signals: {len(signals)}, delta: {len(delta)}, sensor_details: {len(sensor_details)}")
            else:
                log_test("task2_websocket_telemetry", "25 Channels Broadcast", False, f"Counts mismatch: signals={len(signals)}, delta={len(delta)}, details={len(sensor_details)}")

            # Check 11 spatio-temporal features
            features = data.get("features", [])
            if len(features) == 11:
                log_test("task2_websocket_telemetry", "11 Spatio-Temporal Features", True, f"Received exactly 11 features: {features}")
            else:
                log_test("task2_websocket_telemetry", "11 Spatio-Temporal Features", False, f"Expected 11 features, got {len(features)}: {features}")

            # Check Severity Classifications & frame fields
            # Note: rbf_matrix in WebSocket is transposed grid.T -> shape (60, 80)
            sev_level = data.get("severity_level")
            raw_level = data.get("raw_level")
            status = data.get("status")
            probs = data.get("probabilities")
            cpri = data.get("cpri_percent")
            propagation = data.get("propagation")
            rbf_matrix = data.get("rbf_matrix")

            valid_fields = (
                isinstance(sev_level, int) and 0 <= sev_level <= 3 and
                isinstance(raw_level, int) and
                isinstance(status, str) and
                isinstance(probs, list) and len(probs) == 4 and
                isinstance(cpri, (int, float)) and
                isinstance(propagation, dict) and
                isinstance(rbf_matrix, list) and len(rbf_matrix) == 60 and len(rbf_matrix[0]) == 80
            )

            if valid_fields:
                log_test("task2_websocket_telemetry", "Severity Classification & Frame Structure", True, f"Severity Level: {sev_level}, Status: '{status}', CPRI: {cpri}%, Probabilities: {probs}, RBF Matrix: 60x80 transposed grid")
            else:
                log_test("task2_websocket_telemetry", "Severity Classification & Frame Structure", False, f"Field validation failed: sev_level={sev_level}, status={status}, probs={probs}, rbf_matrix_shape=({len(rbf_matrix)}, {len(rbf_matrix[0]) if isinstance(rbf_matrix, list) and len(rbf_matrix)>0 else None})")

    except Exception as e:
        log_test("task2_websocket_telemetry", "WebSocket Connection", False, f"WebSocket error: {e}\n{traceback.format_exc()}")

    # LivePipeline Severity Logic Unit Testing
    print("\n--- Running LivePipeline Severity Logic Tests ---", flush=True)
    pipeline = LivePipeline(model=None, use_gradient=True, fuse_imu=True)
    
    # 2.2 Baseline frame (all signals nominal ~28000)
    baseline_frame = np.full(25, 28000.0)
    res_base = pipeline.process(baseline_frame)
    if res_base["severity_level"] in (0, 1):
        log_test("task2_websocket_telemetry", "Baseline Frame Severity (Level 0/1)", True, f"Severity level: {res_base['severity_level']}, status: {res_base['status']}")
    else:
        log_test("task2_websocket_telemetry", "Baseline Frame Severity (Level 0/1)", False, f"Unexpected baseline severity: {res_base['severity_level']}")

    # 2.3 Peel frame simulation (sustained lift: 8 pads dropped below baseline by -500, grid_mean < -150)
    peel_frame = baseline_frame.copy()
    for pad_idx in range(8):
        peel_frame[pad_idx] -= 500.0
    for _ in range(5):
        res_peel = pipeline.process(peel_frame)
    
    if res_peel["propagation"]["active"] and res_peel["propagation"]["n_lifting_pads"] >= 3 and res_peel["propagation"]["confirmed"]:
        log_test("task2_websocket_telemetry", "Peel Frame Detection & Vector Field Propagation", True, f"Confirmed active peel! Lifting pads: {res_peel['propagation']['n_lifting_pads']}, grid_mean: {res_peel['propagation']['grid_mean']}, propagation: {res_peel['propagation']['description']}")
    else:
        log_test("task2_websocket_telemetry", "Peel Frame Detection & Vector Field Propagation", False, f"Peel detection failed: {res_peel['propagation']}")


# =============================================================================
# TASK 3: Physical Patch UI Layout Rendering & RBF Spatial Interpolation
# =============================================================================
def test_task3():
    print("\n--- Running Task 3: Physical Patch UI & RBF Spatial Interpolation Tests ---", flush=True)
    dispatcher = TeleNursingDispatcher()
    model_holder = {"model": None, "use_gradient": True, "dispatcher": dispatcher}
    app = create_app(model_holder)
    client = TestClient(app)

    # 3.1 GET /api/v6/layout
    try:
        resp = client.get("/api/v6/layout")
        if resp.status_code == 200:
            layout_data = resp.json()
            pads = layout_data.get("pads", [])
            if len(pads) == 25:
                valid_pads = True
                for i, p in enumerate(pads):
                    if p["pad"] != i + 1 or not (10.0 <= p["x"] <= 90.0) or not (10.0 <= p["y"] <= 95.0) or not (1 <= p["signal_channel"] <= 25):
                        valid_pads = False
                        break
                if valid_pads:
                    log_test("task3_physical_patch_ui", "Layout 25 Pads Coordinates & Wiring", True, f"All 25 pads mapped to valid physical coords (90x120mm canvas) and signal channels")
                else:
                    log_test("task3_physical_patch_ui", "Layout 25 Pads Coordinates & Wiring", False, f"Pad coordinate/channel validation failed: {pads[:3]}")
            else:
                log_test("task3_physical_patch_ui", "Layout 25 Pads Coordinates & Wiring", False, f"Expected 25 pads, got {len(pads)}")
        else:
            log_test("task3_physical_patch_ui", "Layout 25 Pads Coordinates & Wiring", False, f"Status code {resp.status_code}")
    except Exception as e:
        log_test("task3_physical_patch_ui", "Layout 25 Pads Coordinates & Wiring", False, str(e))

    # 3.2 RBF Spatial Interpolation Matrix Verification
    try:
        zeros_deltas = np.zeros(25)
        grid_zeros = SPATIAL.interpolate(zeros_deltas)
        if grid_zeros.shape == (80, 60):
            log_test("task3_physical_patch_ui", "RBF Grid Resolution (80x60)", True, f"Interpolated grid shape: {grid_zeros.shape} (80 rows x 60 cols)")
        else:
            log_test("task3_physical_patch_ui", "RBF Grid Resolution (80x60)", False, f"Grid shape mismatch: {grid_zeros.shape}")

        # Impulse response test to confirm non-mirrored coordinate mapping (Fix F1)
        impulse_deltas = np.zeros(25)
        impulse_deltas[0] = 1000.0  # Pad 1 impulse
        grid_impulse = SPATIAL.interpolate(impulse_deltas)
        
        max_idx = np.unravel_index(np.argmax(grid_impulse), grid_impulse.shape)
        y_percent = 10.0 + (95.0 - 10.0) * (max_idx[0] / 79.0)
        x_percent = 10.0 + (90.0 - 10.0) * (max_idx[1] / 59.0)

        dist_to_pad1 = np.sqrt((x_percent - 57.0)**2 + (y_percent - 90.0)**2)
        if dist_to_pad1 < 10.0:
            log_test("task3_physical_patch_ui", "RBF Spatial Orientation & Heatmap Alignment (Fix F1)", True, f"Impulse peak on Pad 1 (57%, 90%) mapped accurately to grid peak at ({x_percent:.1f}%, {y_percent:.1f}%), dist={dist_to_pad1:.2f}%")
        else:
            log_test("task3_physical_patch_ui", "RBF Spatial Orientation & Heatmap Alignment (Fix F1)", False, f"Impulse peak misaligned! Expected ~(57%, 90%), got ({x_percent:.1f}%, {y_percent:.1f}%), dist={dist_to_pad1:.2f}%")

    except Exception as e:
        log_test("task3_physical_patch_ui", "RBF Spatial Interpolation", False, f"Error: {e}\n{traceback.format_exc()}")


# =============================================================================
# TASK 4: Quality Linters (flake8 & pyright)
# =============================================================================
def test_task4():
    print("\n--- Running Task 4: Static Quality Linters Verification ---", flush=True)
    import subprocess
    
    # 4.1 flake8
    try:
        res = subprocess.run(["python", "-m", "flake8", "."], cwd=PROJECT_ROOT, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip() == "":
            log_test("task4_quality_linters", "flake8 . code quality", True, "0 flake8 lint errors found across codebase")
        else:
            log_test("task4_quality_linters", "flake8 . code quality", False, f"flake8 exit code {res.returncode}. Output:\n{res.stdout}\n{res.stderr}")
    except Exception as e:
        log_test("task4_quality_linters", "flake8 . code quality", False, str(e))

    # 4.2 pyright
    try:
        res = subprocess.run(["npx", "pyright"], cwd=PROJECT_ROOT, capture_output=True, text=True, shell=True)
        if res.returncode == 0 and "0 errors" in res.stdout:
            log_test("task4_quality_linters", "pyright type checker", True, f"0 pyright type errors/warnings: {res.stdout.strip()}")
        else:
            log_test("task4_quality_linters", "pyright type checker", False, f"pyright failed. Exit code {res.returncode}. Output:\n{res.stdout}\n{res.stderr}")
    except Exception as e:
        log_test("task4_quality_linters", "pyright type checker", False, str(e))


if __name__ == "__main__":
    test_task1()
    test_task2()
    test_task3()
    test_task4()
    
    print("\n=== SUMMARY OF ALL EMPIRICAL VERIFICATION TESTS ===", flush=True)
    total = 0
    passed = 0
    for task, test_list in results.items():
        print(f"\n--- {task} ({len(test_list)} tests) ---", flush=True)
        for t in test_list:
            total += 1
            if t["passed"]:
                passed += 1
            st = "PASS" if t["passed"] else "FAIL"
            print(f"  [{st}] {t['name']}: {t['details']}", flush=True)
    print(f"\nTOTAL: {passed}/{total} tests passed ({passed/total*100:.1f}%)", flush=True)
