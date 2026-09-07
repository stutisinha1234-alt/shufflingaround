"""Reads data/history.jsonl and produces the ranked report: current price
per window, how it compares to that window's own 30-day median (is this a
good time to book *this* trip) and to the destination's overall median
(is this window cheap *relative to other weeks*), plus $/night and
$/PTO-day so a free window and a PTO-buying window can be compared on the
same axis.

python3 report.py            -> full ranked table
python3 report.py --alerts   -> only rows that cross an alert threshold
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from windows import load_config

HISTORY_PATH = Path(__file__).parent / "data" / "history.jsonl"


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    rows = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _window_key(row: dict) -> tuple:
    return (row["destination"], row["depart"], row["return"])


def build_report(rows: list[dict], config: dict | None = None) -> list[dict]:
    config = config or load_config()
    threshold = config["alerts"]["drop_pct_threshold"]

    by_window = defaultdict(list)
    for r in rows:
        by_window[_window_key(r)].append(r)

    by_dest_prices = defaultdict(list)
    for r in rows:
        if r["price_usd"] is not None:
            by_dest_prices[r["destination"]].append(r["price_usd"])

    report = []
    for key, observations in by_window.items():
        dest, depart, ret = key
        observations.sort(key=lambda r: r["checked_at"])
        priced = [o for o in observations if o["price_usd"] is not None]
        if not priced:
            latest = observations[-1]
            report.append(
                {
                    "destination": dest,
                    "depart": depart,
                    "return": ret,
                    "nights": latest["nights"],
                    "pto_days": latest["pto_days"],
                    "current_price": None,
                    "note": "no GDS fare (Southwest-only route or no offers found)",
                    "southwest_links": latest.get("southwest_links", []),
                }
            )
            continue

        latest = priced[-1]
        window_prices = [o["price_usd"] for o in priced]
        window_median = statistics.median(window_prices)

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent = [
            o["price_usd"] for o in priced
            if datetime.fromisoformat(o["checked_at"]) >= cutoff
        ]
        recent_median = statistics.median(recent) if recent else window_median

        dest_median = statistics.median(by_dest_prices[dest]) if by_dest_prices[dest] else None
        all_time_low = min(window_prices)

        pct_vs_recent = (
            (latest["price_usd"] - recent_median) / recent_median
            if recent_median else 0.0
        )
        is_new_low = latest["price_usd"] <= all_time_low
        is_alert_drop = pct_vs_recent <= -threshold

        report.append(
            {
                "destination": dest,
                "depart": depart,
                "return": ret,
                "nights": latest["nights"],
                "pto_days": latest["pto_days"],
                "current_price": latest["price_usd"],
                "carrier": latest["carrier"],
                "dollars_per_night": round(latest["price_usd"] / max(latest["nights"], 1), 2),
                "dollars_per_pto_day": (
                    round(latest["price_usd"] / latest["pto_days"], 2)
                    if latest["pto_days"] else None
                ),
                "window_30d_median": round(recent_median, 2),
                "dest_overall_median": round(dest_median, 2) if dest_median else None,
                "all_time_low": round(all_time_low, 2),
                "pct_vs_30d_median": round(pct_vs_recent * 100, 1),
                "is_new_all_time_low": is_new_low,
                "is_alert_drop": is_alert_drop,
                "southwest_links": latest.get("southwest_links", []),
            }
        )

    report.sort(key=lambda r: (r["current_price"] is None, r["current_price"] or 0))
    return report


def print_table(report: list[dict], alerts_only: bool = False) -> None:
    rows = [r for r in report if (r.get("is_new_all_time_low") or r.get("is_alert_drop"))] if alerts_only else report
    if not rows:
        print("No alerts." if alerts_only else "No history yet -- run track.py first.")
        return
    for r in rows:
        if r["current_price"] is None:
            print(f"{r['destination']:10s} {r['depart']}->{r['return']}  NO FARE  {r['note']}")
            continue
        flag = " *** NEW LOW ***" if r["is_new_all_time_low"] else (" ! drop" if r["is_alert_drop"] else "")
        print(
            f"{r['destination']:10s} {r['depart']}->{r['return']}  "
            f"${r['current_price']:>7.2f}  {r['pto_days']}PTO  "
            f"${r['dollars_per_night']:>6.2f}/night  "
            f"vs30d {r['pct_vs_30d_median']:+.1f}%{flag}"
        )


if __name__ == "__main__":
    history = load_history()
    rep = build_report(history)
    print_table(rep, alerts_only="--alerts" in sys.argv)
