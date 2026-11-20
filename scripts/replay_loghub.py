"""Push a REAL SSH attack log (Loghub OpenSSH_2k.log) into Loki, so we score real-world attacks.

    .\\.venv\\Scripts\\python.exe scripts\\replay_loghub.py               # 4 hours of log in ~4 minutes
    .\\.venv\\Scripts\\python.exe scripts\\replay_loghub.py --speed 240   # faster (~1 minute)
    .\\.venv\\Scripts\\python.exe scripts\\replay_loghub.py --dry-run     # just show what would be sent

The file comes from https://github.com/logpai/loghub (OpenSSH, 2,000 lines from a lab server,
Dec 10, 06:55-11:04). It is read from data/OpenSSH_2k.log, downloaded first if missing.
Attacker IPs are kept exactly as in the original. Timestamps are moved to "now" and the
gaps between lines are divided by --speed: the order and the bursts stay the same, just faster.
(Our Loki poller only reads NEW lines, so the lines must be stamped with current times.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://raw.githubusercontent.com/logpai/loghub/master/OpenSSH/OpenSSH_2k.log"
LOCAL = Path(__file__).resolve().parent.parent / "data" / "OpenSSH_2k.log"
LINE_RE = re.compile(r"^(\w{3}\s+\d+ \d\d:\d\d:\d\d) (\S+) sshd\[\d+\]: (.*)$")
FAILURE_RE = re.compile(r"fail|invalid|break-in|error|refused|denied", re.I)


def load_lines(path: Path) -> list[str]:
    if not path.exists():
        print(f"{path.name} not found locally, downloading from Loghub...")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(URL, path)
        except (urllib.error.URLError, OSError) as e:
            sys.exit(f"Could not download {URL} ({e}). Put a copy at {path} and try again.")
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse(lines: list[str]) -> list[tuple[float, str, str, str]]:
    """-> [(seconds since first line, host, LEVEL, message)]"""
    out, first = [], None
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        t = datetime.strptime(f"2000 {m.group(1)}", "%Y %b %d %H:%M:%S")   # the file has no year
        first = first or t
        level = "WARN" if FAILURE_RE.search(m.group(3)) else "INFO"
        out.append(((t - first).total_seconds(), m.group(2), level, m.group(3)))
    return out


def push(loki: str, host: str, values: list[list[str]]) -> None:
    body = json.dumps({"streams": [{"stream": {"job": "sshd", "host": host, "source": "loghub"},
                                    "values": values}]}).encode()
    req = urllib.request.Request(f"{loki}/loki/api/v1/push", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        if r.status != 204:
            raise RuntimeError(f"Loki answered {r.status}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loki", default="http://localhost:3100")
    ap.add_argument("--speed", type=float, default=60, help="time compression (60 = 1 hour of log per minute)")
    ap.add_argument("--file", type=Path, default=LOCAL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    entries = parse(load_lines(args.file))
    span = entries[-1][0]
    print(f"{len(entries)} lines covering {span / 3600:.1f} h, sending in ~{span / args.speed:.0f} s (speed x{args.speed:g})")
    if args.dry_run:
        for off, host, level, msg in entries[:5]:
            print(f"  +{off:6.0f}s  {host}  {level}  {msg}")
        return

    start = time.time()
    sent = 0
    while sent < len(entries):
        now = time.time()
        due = [e for e in entries[sent:] if start + e[0] / args.speed <= now]
        if due:
            values = []
            for i, (off, _host, level, msg) in enumerate(due):
                ts = start + off / args.speed
                ns = int(ts * 1e9) + i * 1000          # +1 µs each: lines from the same second stay distinct
                iso = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                values.append([str(ns), f"{iso} {level} {msg}"])
            try:
                push(args.loki, due[0][1], values)
            except (urllib.error.URLError, OSError, RuntimeError) as e:
                sys.exit(f"Could not push to Loki at {args.loki}: {e}. Is the Docker stack running?")
            sent += len(due)
            print(f"\r  sent {sent}/{len(entries)} lines", end="", flush=True)
        time.sleep(1)
    print("\ndone. The backend's Loki poller picks the failures up within ~10 s.")


if __name__ == "__main__":
    main()
