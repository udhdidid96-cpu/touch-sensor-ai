#!/usr/bin/env python3
"""Expose the local dashboard on a temporary public HTTPS URL, for remote judges.

READ THIS BEFORE RUNNING IT
---------------------------
main.py serves an **unauthenticated** API. Putting it behind a public tunnel
hands anyone who has the link:

  * every recording under Data/, through /api/v5/dataset/{path};
  * the ability to open a serial port on THIS machine, through
    /ws/live_sensor?source=serial&port=COM3.

That second one is why this script sets an access key by default. A tunnel URL
is guessable enough to be scanned, and "nobody will find it" is not an access
control policy on a machine that is plugged into hardware.

With a key set, main.py requires ?key=<token> (or an X-Access-Key header) on
every API route. This script prints the full URL with the key already embedded
- that is the link you paste to a judge. Pass --no-token for a purely local or
trusted-network demo.

Usage
-----
    python share_public.py                 tunnel, with a generated access key
    python share_public.py --no-token      no gate (local / trusted network)
    python share_public.py --port 8081
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = 8081
URL_RE = re.compile(r"https://[-\w.]+\.(?:trycloudflare\.com|loca\.lt)\S*")


def server_is_up(port: int, key: str = "") -> bool:
    url = f"http://127.0.0.1:{port}/api/v6/health" + (f"?key={key}" if key else "")
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code in (401, 403)      # it is up, it is just gating us
    except Exception:
        return False


def launch_server(port: int, key: str) -> subprocess.Popen:
    env = dict(os.environ)
    if key:
        env["PROJECT2_ACCESS_KEY"] = key
    cmd = [sys.executable, "-u", "main.py", "--port", str(port)]
    print(f"[*] starting: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(__file__)), env=env)
    for _ in range(60):                    # up to ~30 s; the model has to train first
        time.sleep(0.5)
        if server_is_up(port, key):
            print("[+] local server is up")
            return proc
        if proc.poll() is not None:
            raise SystemExit(f"[!] main.py exited with code {proc.returncode}")
    print("[!] server did not answer within 30 s - tunnelling anyway")
    return proc


def _announce(public_url: str, key: str) -> None:
    full = public_url + (f"?key={key}" if key else "")
    bar = "=" * 78
    print(f"\n{bar}\n  PUBLIC URL - send this exact link, the key is part of it:\n\n"
          f"    {full}\n\n{bar}")
    if not key:
        print("  WARNING: no access key. Anyone with this URL can read Data/ and\n"
              "           open a serial port on this machine. Ctrl-C to stop.\n" + bar)


def tunnel(port: int, key: str) -> int:
    exe = shutil.which("cloudflared")
    if exe:
        print("[+] cloudflared found - opening an HTTPS tunnel")
        cmd = [exe, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    elif shutil.which("npx") or shutil.which("npx.cmd"):
        print("[+] cloudflared not found - falling back to npx localtunnel")
        npx_bin = "npx.cmd" if os.name == "nt" else "npx"
        cmd = [npx_bin, "-y", "localtunnel", "--port", str(port)]
    else:
        print("[!] neither cloudflared nor npx is installed.\n"
              f"    Install one, or demo locally at http://127.0.0.1:{port}")
        return 1

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, shell=(os.name == "nt"))
    announced = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            if not announced:
                found = URL_RE.search(line)
                if found:
                    _announce(found.group(0), key)
                    announced = True
        return proc.wait()
    except KeyboardInterrupt:
        print("\n[*] stopping tunnel")
        proc.terminate()
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().split("\n")[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-token", action="store_true",
                    help="disable the access gate (local or trusted network only)")
    args = ap.parse_args(argv)

    key = "" if args.no_token else secrets.token_urlsafe(12)

    if server_is_up(args.port, key):
        print(f"[+] a server is already listening on port {args.port}")
        if key:
            print("[!] it was not started by this script, so it does not know the\n"
                  "    generated key. Stop it and re-run, or pass --no-token.")
            return 2
    else:
        launch_server(args.port, key)

    return tunnel(args.port, key)


if __name__ == "__main__":
    raise SystemExit(main())
