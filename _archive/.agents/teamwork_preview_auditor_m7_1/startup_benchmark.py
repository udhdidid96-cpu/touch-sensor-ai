import time
import subprocess
import urllib.request
import sys

def measure_startup():
    cmd = [sys.executable, "-c", "import uvicorn; from main import get_app; uvicorn.run(get_app(), host='127.0.0.1', port=8081, log_level='error')"]
    start_time = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=r"C:\Users\denpo\OneDrive\Desktop\Project2")
    
    success = False
    elapsed = 0.0
    try:
        while time.perf_counter() - start_time < 5.0:
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:8081/api/v6/health", timeout=0.5)
                if resp.status == 200:
                    elapsed = time.perf_counter() - start_time
                    success = True
                    break
            except Exception:
                time.sleep(0.02)
    finally:
        proc.terminate()
        proc.wait()
    
    print(f"Server Startup Time: {elapsed*1000:.2f} ms ({elapsed:.4f} s), Success: {success}")
    assert success, "Server failed to start within timeout"
    assert elapsed < 1.0, f"Server startup time {elapsed:.4f}s >= 1.0s limit"
    print("PASS: Server startup time < 1.0s")

if __name__ == "__main__":
    measure_startup()
