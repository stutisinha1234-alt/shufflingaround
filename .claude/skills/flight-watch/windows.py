"""Calendar engine for flight-watch: turns config.json's work schedule and
holiday list into a ranked set of candidate SFO <-> destination trip windows.

Pure and network-free by design so it can be unit tested without touching
any flight-price provider. track.py imports generate_windows() and pairs
the result with destinations to build the search list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


@dataclass(frozen=True)
class Window:
    depart: date
    ret: date
    pto_days: int

    @property
    def nights(self) -> int:
        return (self.ret - self.depart).days

    def holidays_covered(self, holidays: dict[date, str]) -> list[str]:
        return [name for d, name in holidays.items() if self.depart <= d <= self.ret]


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def _parse_holidays(config: dict) -> dict[date, str]:
    return {date.fromisoformat(h["date"]): h["name"] for h in config["holidays"]}


def pto_cost(depart: date, ret: date, config: dict) -> int:
    """PTO days burned by a trip that departs SFO on `depart` evening and
    returns on `ret` evening. The departure day itself is always free: the
    traveler works a full day in SF before an evening flight out."""
    holidays = _parse_holidays(config)
    remote = set(config["work_schedule"]["remote_weekdays"])
    weekend = {5, 6}

    cost = 0
    d = depart
    while d <= ret:
        is_free = (
            d == depart
            or d in holidays
            or d.weekday() in remote
            or d.weekday() in weekend
        )
        if not is_free:
            cost += 1
        d += timedelta(days=1)
    return cost


def generate_windows(config: dict | None = None) -> list[Window]:
    """All candidate windows in the horizon whose departure/return weekdays
    match trip_shape and whose PTO cost is within pto_buying.max_pto_days.
    Includes zero-PTO windows (the default set) and higher-PTO windows
    (surfaced only when they clear min_nights_per_pto_day)."""
    config = config or load_config()
    shape = config["trip_shape"]
    configured_start = date.fromisoformat(config["horizon"]["start"])
    horizon_start = max(configured_start, date.today())
    horizon_end = date.fromisoformat(config["horizon"]["end"])
    dep_weekdays = set(shape["departure_weekdays"])
    ret_weekdays = set(shape["return_weekdays"])
    max_pto = config["pto_buying"]["max_pto_days"]
    min_nights_per_pto = config["pto_buying"]["min_nights_per_pto_day"]

    windows: list[Window] = []
    d = horizon_start
    while d <= horizon_end:
        if d.weekday() in dep_weekdays:
            for n in range(shape["min_nights"], shape["max_nights"] + 1):
                r = d + timedelta(days=n)
                if r > horizon_end:
                    break
                if r.weekday() not in ret_weekdays:
                    continue
                cost = pto_cost(d, r, config)
                if cost > max_pto:
                    continue
                if cost > 0 and n < cost * min_nights_per_pto:
                    continue
                windows.append(Window(depart=d, ret=r, pto_days=cost))
        d += timedelta(days=1)
    return windows


def best_per_week(windows: list[Window]) -> list[Window]:
    """Collapse same-week candidates to the longest zero-PTO window per week
    plus the standout PTO-buying windows, matching the shape of the report
    shown to the user: one baseline trip per week, PTO spends called out
    separately."""
    free = [w for w in windows if w.pto_days == 0]
    by_week: dict[tuple[int, int], Window] = {}
    for w in free:
        key = w.depart.isocalendar()[:2]
        if key not in by_week or w.nights > by_week[key].nights:
            by_week[key] = w
    baseline = sorted(by_week.values(), key=lambda w: w.depart)

    paid = [w for w in windows if w.pto_days > 0]
    best_paid: dict[int, Window] = {}
    for w in paid:
        if w.pto_days not in best_paid or w.nights > best_paid[w.pto_days].nights:
            best_paid[w.pto_days] = w
    standouts = sorted(best_paid.values(), key=lambda w: w.pto_days)

    return baseline + standouts


if __name__ == "__main__":
    cfg = load_config()
    holidays = _parse_holidays(cfg)
    all_windows = generate_windows(cfg)
    print(f"{len(all_windows)} total candidate windows generated.\n")
    for w in best_per_week(all_windows):
        tag = ", ".join(w.holidays_covered(holidays)) or "-"
        label = "FREE" if w.pto_days == 0 else f"{w.pto_days} PTO"
        print(
            f"{label:>6}  {w.depart} {w.depart.strftime('%a')} eve -> "
            f"{w.ret} {w.ret.strftime('%a')} eve   {w.nights:>2} nights   {tag}"
        )
