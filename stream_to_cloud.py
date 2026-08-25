"""
Bridge Script: Read Arduino Touch Sensor from local USB (COM port)
and stream real-time sensor frames to Google Cloud Run.
"""
import os
import sys
import time
import json
import argparse
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("[ERROR] pyserial is required. Install with: pip install pyserial")
    sys.exit(1)

# websockets is imported where it is used, inside main(), so the friendly
# pyserial error above is reachable even without it installed.

import urllib.parse

DEFAULT_CLOUD_URL = "https://touch-sensor-ai-156577365290.asia-southeast1.run.app"
N_PADS = 25


def find_default_com_port() -> Optional[str]:
    """Auto-detect Arduino or USB Serial COM port."""
    ports = list(list_ports.comports())
    if not ports:
        return None
    for p in ports:
        desc = (p.description or "").lower()
        if "arduino" in desc or "usb" in desc or "ch340" in desc or "cp210" in desc or "ftdi" in desc:
            return p.device
    return ports[0].device


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream Arduino Touch Sensor to Cloud Web App")
    parser.add_argument("--port", type=str, default=None, help="Serial port (e.g. COM3). Auto-detected if omitted.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default: 115200)")
    parser.add_argument("--cloud", type=str, default=DEFAULT_CLOUD_URL, help="Target Cloud Web App URL")
    parser.add_argument("--key", type=str, default=os.environ.get("PROJECT2_ACCESS_KEY", ""),
                        help="access key for a gated server (defaults to $PROJECT2_ACCESS_KEY)")
    args = parser.parse_args()

    port = args.port or find_default_com_port() or "COM3"
    print("=" * 65)
    print(" 🏥 SMART EXTUBATION - ARDUINO SENSOR BRIDGE TO CLOUD")
    print("=" * 65)
    print(f" ► Arduino USB Port : {port} ({args.baud} baud)")
    print(f" ► Cloud Destination: {args.cloud}")
    print("=" * 65)

    ws_url = args.cloud.replace("http://", "ws://").replace("https://", "wss://")
    if not ws_url.endswith("/"):
        ws_url += "/"
    # source=client is the server's ingest branch: it calls ws.receive_json() in
    # a loop, classifies each {"raw_frame": [...]} through the one shared
    # LivePipeline, and sends the result back.
    #
    # This used to say source=webserial. main.py treated any unrecognised
    # source= as "replay" and contained no ws.receive_* call anywhere, so every
    # frame this script sent was discarded and the dashboard was fed a canned
    # replay of Normal Mix/N_Mix_01.csv - while this console printed
    # ">>> SENSOR STREAMING ACTIVE! <<<" and a live frame rate. A demo run looked
    # perfect and showed nothing from the patch. The confirmation printed below
    # is now the server's own reply to a frame, not our own optimism.
    ws_endpoint = f"{ws_url}ws/live_sensor?source=client"
    if args.key:
        ws_endpoint += f"&key={urllib.parse.quote(args.key)}"

    while True:
        print(f"\n[1/2] Connecting to Arduino on {port}...")
        ser = None
        try:
            ser = serial.Serial(port=port, baudrate=args.baud, timeout=2.0)
            print(" [OK] Arduino USB port opened successfully!")
        except Exception as e:
            print(f" [WAIT] Could not open {port}: {e}")
            print(" Retrying in 3 seconds... (Make sure Arduino Serial Monitor is closed)")
            time.sleep(3)
            continue

        print("[2/2] Connecting to the server WebSocket...")
        try:
            import websockets.sync.client as ws_client
            with ws_client.connect(ws_endpoint, open_timeout=20) as ws:
                # The server announces the ingest contract on connect. If we do
                # not get it, we are not talking to an ingest endpoint and we say
                # so instead of streaming into a void.
                hello = json.loads(ws.recv())
                if hello.get("source") != "client":
                    print(f" [FAIL] {args.cloud} did not accept a client ingest session "
                          f"(replied: {hello}).\n        That server is too old for this "
                          f"bridge - it needs the ?source=client branch in main.py.")
                    ser.close()
                    return
                print(" [OK] Server accepted the ingest session.")
                print("\n >>> STREAMING. Levels below are the SERVER's classification. <<<")
                print(" (Press Ctrl+C to stop)\n")

                count = 0
                acked = 0
                last_fps_time = time.time()
                while True:
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p for p in line.replace(",", " ").split() if p]
                    if len(parts) < N_PADS:
                        continue
                    try:
                        # A garbled token drops the whole frame. Filtering the bad
                        # value out and taking the first 25 of the rest would
                        # shift every later channel by one position, which reads
                        # as valid data from a mis-wired patch.
                        vals = [float(p) for p in parts[:N_PADS]]
                    except ValueError:
                        continue

                    ws.send(json.dumps({"raw_frame": vals}))
                    count += 1

                    reply = json.loads(ws.recv())
                    if "error" in reply:
                        print(f"\n [SERVER REJECTED FRAME] {reply['error']}")
                        continue
                    acked += 1

                    if acked % 10 == 0:
                        now = time.time()
                        dt = now - last_fps_time
                        fps = 10 / dt if dt > 0 else 0
                        last_fps_time = now
                        lvl = reply.get("severity_level", "?")
                        cpri = reply.get("cpri_percent", 0.0)
                        span = max(vals) - min(vals)
                        print(f"\r[LIVE] frame #{acked:05d} | {fps:4.1f} Hz | "
                              f"L{lvl} | CPRI {cpri:5.1f}% | span {span:7.1f}   ",
                              end="", flush=True)
        except KeyboardInterrupt:
            print("\n[STOP] Stopped by user.")
            if ser.is_open:
                ser.close()
            break
        except Exception as ws_err:
            print(f"\n[WARN] Connection dropped: {ws_err}. Reconnecting in 2s...")
            if ser.is_open:
                ser.close()
            time.sleep(2)


if __name__ == "__main__":
    main()
