import time
import asyncio
import json
import re
import sys
import os

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient
from main import (
    get_app,
    TeleNursingDispatcher,
    TeleNursingConfig,
    SerialFrameSource,
    pick_port,
    STATUS_TEXT_MAP,
    DASHBOARD_HTML,
)

def run_tests():
    results = {}
    
    print("=== 1. VERIFYING TELENURSING DISPATCHER ===")
    config = TeleNursingConfig(
        enabled=True,
        line_token="test_line",
        telegram_token="test_tg",
        telegram_chat_id="1234",
        bed_number="Bed-99",
        cooldown_seconds=1.0
    )
    dispatcher = TeleNursingDispatcher(config)

    t0 = time.perf_counter()
    dispatcher.check_and_trigger_async({
        "severity_level": 3,
        "status": STATUS_TEXT_MAP[3],
        "cpri_percent": 98.5,
        "deltas": [500] * 25,
    })
    t_check = (time.perf_counter() - t0) * 1000
    print(f"check_and_trigger_async execution time: {t_check:.4f} ms (< 500ms non-blocking check passed: {t_check < 500})")

    async def test_dispatch():
        t_disp0 = time.perf_counter()
        res = await dispatcher.dispatch_alert({
            "bed_number": "Bed-99",
            "severity_level": 3,
            "status": "Level 3: CRITICAL EXTUBATION PULL ALARM",
            "cpri_percent": 98.5
        })
        t_disp = (time.perf_counter() - t_disp0) * 1000
        print(f"dispatch_alert direct execution time: {t_disp:.2f} ms (status: {res['status']})")
        return t_disp

    disp_time = asyncio.run(test_dispatch())
    assert t_check < 500.0, "check_and_trigger_async degraded frame latency!"
    results["t_check_ms"] = round(t_check, 4)
    results["disp_time_ms"] = round(disp_time, 2)

    print("\n=== 2. VERIFYING SERVER STARTUP TIME AND PORT 8081 ===")
    t_start0 = time.perf_counter()
    app = get_app()
    t_startup = time.perf_counter() - t_start0
    print(f"FastAPI get_app() total startup time: {t_startup:.4f} seconds (< 1.0s requirement passed: {t_startup < 1.0})")
    p = pick_port(8081, "127.0.0.1")
    print(f"Default port check: pick_port(8081) returned {p}")
    assert t_startup < 1.0, f"Server startup time {t_startup:.2f}s exceeded 1.0s!"
    results["startup_time_s"] = round(t_startup, 4)
    results["default_port"] = p

    print("\n=== 3. VERIFYING AUDIO-VISUAL ICU EMERGENCY SIREN ===")
    assert "960" in DASHBOARD_HTML and "770" in DASHBOARD_HTML, "960Hz / 770Hz frequencies missing from siren HTML!"
    siren_lines = [line.strip() for line in DASHBOARD_HTML.splitlines() if "960" in line and "770" in line]
    print(f"Siren dual-tone code snippet: {siren_lines}")
    print(f"Level 3 Status Map text: '{STATUS_TEXT_MAP[3]}'")
    results["siren_code_snippet"] = siren_lines[0] if siren_lines else ""
    results["level_3_status"] = STATUS_TEXT_MAP[3]

    print("\n=== 4. VERIFYING SERIAL PORTS & WEBSOCKET ENDPOINTS ===")
    client = TestClient(app)

    res_ports = client.get("/api/v5/serial/ports")
    print(f"GET /api/v5/serial/ports: status={res_ports.status_code}, data={res_ports.json()}")
    assert res_ports.status_code == 200

    res_conn = client.post("/api/v5/serial/connect", json={"port": "LOOPBACK", "baudrate": 115200})
    print(f"POST /api/v5/serial/connect: status={res_conn.status_code}, data={res_conn.json()}")
    assert res_conn.status_code == 200

    with client.websocket_connect("/ws/sensor") as ws:
        time.sleep(0.1)
        frame = ws.receive_json()
        print(f"WS /ws/sensor frame received: keys={list(frame.keys())}")
        print(f"  signals count: {len(frame['signals'])}, deltas count: {len(frame['delta'])}")
        print(f"  rbf_matrix shape: {len(frame['rbf_matrix'])}x{len(frame['rbf_matrix'][0])}")
        print(f"  severity_level: {frame['severity_level']}, status: {frame['status']}")
        assert len(frame["signals"]) == 25
        assert len(frame["delta"]) == 25
        assert len(frame["rbf_matrix"]) == 60 and len(frame["rbf_matrix"][0]) == 80

    res_disc = client.post("/api/v5/serial/disconnect")
    print(f"POST /api/v5/serial/disconnect: status={res_disc.status_code}, data={res_disc.json()}")
    assert res_disc.status_code == 200

    print("\nALL VERIFICATIONS PASSED PERFECTLY!")
    return results

if __name__ == "__main__":
    run_tests()
