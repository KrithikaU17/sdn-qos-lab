#!/usr/bin/env python3
"""Parse qos_udp server log intervals into CSV for report graphs."""

import argparse
import csv
import re
import sys

ROW = re.compile(
    r"^\s*(\d+)s\s+(voice|video|bulk)\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s*$"
)
FAIR = re.compile(r"Jain fairness index:\s*([\d.]+)")


def parse(path):
    rows = []
    fairness_by_second = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        match = ROW.match(line)
        if match:
            elapsed, clazz, tput, latency, loss, processed, queued = match.groups()
            rows.append(
                {
                    "elapsed_s": int(elapsed),
                    "class": clazz,
                    "throughput_kbps": float(tput),
                    "latency_ms": float(latency),
                    "loss_pct": float(loss),
                    "processed": int(processed),
                    "queued": int(queued),
                }
            )
            continue
        fair = FAIR.search(line)
        if fair:
            fairness_by_second[rows[-1]["elapsed_s"] if rows else 0] = float(
                fair.group(1)
            )
    for row in rows:
        row["jain_fairness"] = fairness_by_second.get(row["elapsed_s"], "")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logfile")
    parser.add_argument("-o", "--output", help="CSV path (default stdout)")
    args = parser.parse_args()
    rows = parse(args.logfile)
    if not rows:
        print("no data rows found", file=sys.stderr)
        sys.exit(1)
    fields = list(rows[0].keys())
    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.output:
            out.close()
            print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
