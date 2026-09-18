#!/usr/bin/env python3
"""Unified CLI runner for Project2 (Smart Extubation Early Warning).

Replaces Windows .bat files with cross-platform Python commands:
  python run.py             -> Start local web dashboard
  python run.py share       -> Expose public link via Cloudflare Tunnel
  python run.py stream      -> Bridge USB serial sensor to cloud
  python run.py test        -> Run automated pytest test suite
  python run.py verify      -> Verify metrics against Data/metrics.json
  python run.py pads        -> Verify pad order against 1-by-1 sweep
  python run.py audit       -> Audit Data/ corpus against spec
  python run.py benchmark   -> Run ML architectures benchmark
"""
import sys
import subprocess
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    args = sys.argv[2:]

    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    elif cmd in ("dashboard", "web", "server", "start"):
        print("--- Starting Smart Extubation Early Warning Dashboard ---")
        return subprocess.call([sys.executable, "-u", os.path.join(PROJECT_ROOT, "main.py")] + args)
    
    elif cmd in ("share", "public", "tunnel"):
        print("--- Starting Public Tunnel Dashboard ---")
        return subprocess.call([sys.executable, "-u", os.path.join(PROJECT_ROOT, "share_public.py")] + args)
    
    elif cmd in ("stream", "bridge", "serial"):
        print("--- Starting Sensor Stream Bridge ---")
        return subprocess.call([sys.executable, "-u", os.path.join(PROJECT_ROOT, "stream_to_cloud.py")] + args)
    
    elif cmd in ("test", "pytest", "tests"):
        print("--- Running Automated Pytest Suite ---")
        return subprocess.call([sys.executable, "-m", "pytest", "tests/", "-q"] + args)
    
    elif cmd in ("verify", "verify-metrics"):
        print("--- Verifying Metrics Reproduction ---")
        return subprocess.call([sys.executable, os.path.join(PROJECT_ROOT, "main.py"), "--verify-metrics"] + args)
    
    elif cmd in ("pads", "verify-pads"):
        print("--- Verifying Pad Order ---")
        return subprocess.call([sys.executable, os.path.join(PROJECT_ROOT, "main.py"), "--verify-pads"] + args)
    
    elif cmd in ("audit", "audit-data"):
        print("--- Auditing Corpus Data ---")
        target_dir = args[0] if args else "Data"
        return subprocess.call([sys.executable, os.path.join(PROJECT_ROOT, "main.py"), "--audit", target_dir])
    
    elif cmd in ("benchmark", "ml"):
        print("--- Running ML Architecture Benchmark ---")
        return subprocess.call([sys.executable, os.path.join(PROJECT_ROOT, "benchmark_ml_architectures.py")] + args)
    
    else:
        print(__doc__)
        print(f"Unknown command: '{cmd}'")
        return 1

if __name__ == "__main__":
    sys.exit(main())
