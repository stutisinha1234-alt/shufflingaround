"""Runs one tracking pass: windows() x destinations x origin airports ->
Amadeus search (or a Southwest deep link where Amadeus structurally can't
reach the fare) -> append every observation to data/history.jsonl.

Invoke directly (python3 track.py) or via a twice-weekly Routine. Designed
to be safe to run repeatedly: every row is timestamped and appended, never
overwritten, so history.jsonl is the append-only ledger report.py reads.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

from providers.amadeus import AmadeusClient, AmadeusError
from windows import Window, best_per_week, generate_windows, load_config

HISTORY_PATH = Path(__file__).parent / "data" / "history.jsonl"


def southwest_deep_link(origin: str, destination: str, depart: date, ret: date) -> str:
    params = {
        "originationAirportCode": origin,
        "destinationAirportCode": destination,
        "departureDate": depart.isoformat(),
        "returnDate": ret.isoformat(),
        "adultPassengersCount": "1",
        "tripType": "roundtrip",
    }
    return "https://www.southwest.com/air/booking/select.html?" + urllib.parse.urlencode(params)


def append_history(rows: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def run(config: dict | None = None, sleep_between_calls: float = 0.3) -> list[dict]:
    config = config or load_config()
    windows = best_per_week(generate_windows(config))
    origins = config["origin_airports"]
    checked_at = datetime.now(timezone.utc).isoformat()

    rows: list[dict] = []
    client: AmadeusClient | None = None
    try:
        client = AmadeusClient()
    except AmadeusError as e:
        print(f"WARNING: Amadeus unavailable ({e}). All windows will be "
              f"recorded as deep-link-only observations.", file=sys.stderr)

    for dest in config["destinations"]:
        sw_only = set(dest["southwest_only_airports"])
        gds_airports = [a for a in dest["airports"] if a not in sw_only]

        for window in windows:
            best_offer = None
            best_pair = None

            if client and gds_airports:
                for origin in origins:
                    for airport in gds_airports:
                        try:
                            offers = client.search_round_trip(
                                origin, airport, window.depart, window.ret
                            )
                        except AmadeusError as e:
                            print(
                                f"  search failed {origin}->{airport} "
                                f"{window.depart}/{window.ret}: {e}",
                                file=sys.stderr,
                            )
                            offers = []
                        if offers and (best_offer is None or offers[0]["price"] < best_offer["price"]):
                            best_offer = offers[0]
                            best_pair = (origin, airport)
                        time.sleep(sleep_between_calls)

            row = {
                "checked_at": checked_at,
                "destination": dest["name"],
                "depart": window.depart.isoformat(),
                "return": window.ret.isoformat(),
                "nights": window.nights,
                "pto_days": window.pto_days,
                "origin_airport": best_pair[0] if best_pair else None,
                "dest_airport": best_pair[1] if best_pair else None,
                "price_usd": best_offer["price"] if best_offer else None,
                "carrier": best_offer["carrier"] if best_offer else None,
                "southwest_links": [
                    {
                        "origin": o,
                        "dest": a,
                        "url": southwest_deep_link(o, a, window.depart, window.ret),
                    }
                    for o in origins
                    for a in sw_only
                ] if sw_only else [],
            }
            rows.append(row)

    append_history(rows)
    return rows


if __name__ == "__main__":
    results = run()
    priced = [r for r in results if r["price_usd"] is not None]
    print(f"Recorded {len(results)} window observations ({len(priced)} with a live price).")
