import time
import subprocess
import urllib.request
import json
import sys

def verify():
    print("Starting main.py on port 8081...")
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, "main.py", "--port", "8081"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    health_url = "http://127.0.0.1:8081/api/v6/health"
    startup_time = None
    
    # Wait for server to become responsive
    for _ in range(50):
        try:
            req = urllib.request.urlopen(health_url, timeout=0.2)
            if req.status == 200:
                startup_time = (time.time() - t0) * 1000
                break
        except Exception:
            time.sleep(0.02)

    if startup_time is None:
        proc.kill()
        raise RuntimeError("Server failed to respond within timeout")

    print(f"[PASS] Server startup time: {startup_time:.2f} ms (< 1000 ms)")

    # 1. Test GET /api/tele-nursing/config
    config_url = "http://127.0.0.1:8081/api/tele-nursing/config"
    req_cfg = urllib.request.urlopen(config_url)
    cfg_data = json.loads(req_cfg.read().decode('utf-8'))
    print(f"[PASS] GET /api/tele-nursing/config response: {cfg_data}")
    assert "enabled" in cfg_data and "bed_number" in cfg_data

    # 2. Test POST /api/tele-nursing/config
    post_cfg_data = json.dumps({"enabled": True, "bed_number": "Bed-ICU-09", "line_token": "TEST_LINE_TOKEN"}).encode('utf-8')
    req_post_cfg = urllib.request.Request(config_url, data=post_cfg_data, headers={"Content-Type": "application/json"})
    res_post_cfg = json.loads(urllib.request.urlopen(req_post_cfg).read().decode('utf-8'))
    print(f"[PASS] POST /api/tele-nursing/config response: {res_post_cfg}")
    assert res_post_cfg.get("status") == "success"
    assert res_post_cfg["config"]["bed_number"] == "Bed-ICU-09"

    # 3. Test POST /api/tele-nursing/test-alert
    test_alert_url = "http://127.0.0.1:8081/api/tele-nursing/test-alert"
    alert_payload = {
        "bed_number": "Bed-ICU-09",
        "severity_level": 3,
        "status": "Level 3: CRITICAL EXTUBATION PULL ALARM",
        "cpri_percent": 99.8,
        "timestamp": "2026-07-31 16:30:00",
        "rbf_summary": "60x80 Grid (active pads: 12)"
    }
    t_alert_start = time.time()
    req_alert = urllib.request.Request(test_alert_url, data=json.dumps(alert_payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    alert_res_raw = urllib.request.urlopen(req_alert).read().decode('utf-8')
    t_alert_end = time.time()
    alert_latency = (t_alert_end - t_alert_start) * 1000
    alert_res = json.loads(alert_res_raw)

    print(f"[PASS] POST /api/tele-nursing/test-alert response: {alert_res}")
    print(f"[PASS] Test alert HTTP dispatch latency: {alert_latency:.2f} ms (< 500 ms)")
    print(f"[PASS] Dispatcher internal latency: {alert_res.get('latency_ms')} ms")

    assert alert_res.get("status") == "dispatched"
    assert alert_latency < 500.0, f"Latency {alert_latency} ms exceeded 500 ms target"
    assert alert_res["payload"]["bed_number"] == "Bed-ICU-09"
    assert alert_res["payload"]["severity_level"] == 3
    assert alert_res["payload"]["cpri_percent"] == 99.8
    assert "rbf_summary" in alert_res["payload"]

    proc.terminate()
    proc.wait(timeout=2)
    print("\nALL SERVER VERIFICATION CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    verify()
