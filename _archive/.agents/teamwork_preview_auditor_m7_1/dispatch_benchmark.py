import sys
import os
import time
import asyncio

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import TeleNursingDispatcher, TeleNursingConfig
from fastapi.testclient import TestClient
from main import get_app

async def benchmark_dispatch_direct():
    config = TeleNursingConfig(enabled=True, bed_number="Bed-BENCH-01")
    dispatcher = TeleNursingDispatcher(config)
    
    payload = {
        "bed_number": "Bed-BENCH-01",
        "severity_level": 3,
        "status": "Level 3: CRITICAL EXTUBATION PULL ALARM",
        "cpri_percent": 99.5,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rbf_summary": "Test Benchmark Matrix"
    }
    
    # Perform 5 dispatches and record latencies
    latencies = []
    for i in range(5):
        t0 = time.perf_counter()
        result = await dispatcher.dispatch_alert(payload)
        t1 = time.perf_counter()
        lat_ms = (t1 - t0) * 1000
        latencies.append(lat_ms)
        print(f"Dispatch #{i+1}: internal_latency={result['latency_ms']} ms, total_latency={lat_ms:.2f} ms")
        assert lat_ms < 500.0, f"Alert dispatch latency {lat_ms:.2f}ms >= 500ms threshold!"

    avg_lat = sum(latencies) / len(latencies)
    print(f"Direct Alert Dispatch Average Latency: {avg_lat:.2f} ms (max: {max(latencies):.2f} ms)")
    print("PASS: Alert dispatch time < 500ms (direct call)")

def benchmark_dispatch_endpoint():
    app = get_app()
    client = TestClient(app)
    
    latencies = []
    for i in range(5):
        t0 = time.perf_counter()
        resp = client.post("/api/tele-nursing/test-alert", json={
            "bed_number": "Bed-BENCH-01",
            "severity_level": 3,
            "status": "Level 3: CRITICAL EXTUBATION PULL ALARM",
            "cpri_percent": 99.5,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rbf_summary": "Test Benchmark Matrix"
        })
        t1 = time.perf_counter()
        lat_ms = (t1 - t0) * 1000
        assert resp.status_code == 200
        data = resp.json()
        latencies.append(lat_ms)
        print(f"HTTP Endpoint Dispatch #{i+1}: internal_latency={data.get('latency_ms')} ms, total_http_latency={lat_ms:.2f} ms")
        assert lat_ms < 500.0, f"HTTP Endpoint dispatch latency {lat_ms:.2f}ms >= 500ms threshold!"
        
    avg_lat = sum(latencies) / len(latencies)
    print(f"HTTP Endpoint Alert Dispatch Average Latency: {avg_lat:.2f} ms (max: {max(latencies):.2f} ms)")
    print("PASS: Alert dispatch time < 500ms (HTTP endpoint)")

if __name__ == "__main__":
    print("--- 1. Direct Dispatch Benchmark ---")
    asyncio.run(benchmark_dispatch_direct())
    print("\n--- 2. HTTP Endpoint Dispatch Benchmark ---")
    benchmark_dispatch_endpoint()
