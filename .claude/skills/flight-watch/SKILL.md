---
name: flight-watch
description: Tracks round-trip flight prices from San Francisco (SFO/OAK/SJC) to New York, Chicago, Durham NC, and Houston through the end of 2026, restricted to trip windows that minimize PTO (Mon/Fri remote work days). Use when the user asks to check flight prices, run the flight tracker, or review fare trends for these routes.
---

# flight-watch

Tracks fares for a fixed set of SFO -> {New York, Chicago, Durham, Houston}
round trips, restricted to windows chosen so most trips cost zero PTO days.

## Why these windows and not "flexible dates"

The user works remote on Mondays and Fridays and in-office Tue/Wed/Thu. A
Thursday-evening departure and Monday-night return therefore costs 0 PTO
days every single week: the departure day is a full SF workday before an
evening flight, Friday and Monday are worked remotely from the
destination, and Saturday/Sunday are free. `windows.py` generates this
full candidate set from `config.json`'s work schedule and holiday list --
see that file for the exact rule set and `test_windows.py` for the
worked examples (Thanksgiving and Christmas both absorb an office day for
free; the Veterans Day and Christmas bridges both buy 11 nights for 2 PTO
days).

Because a free window exists every week, PTO is not the scarce resource
here -- price is. The report ranks by price and by $/night and $/PTO-day,
never by PTO cost alone, since a "free" Thanksgiving window can cost more
than a plain week two weeks earlier.

## Running it

```
python3 track.py            # one tracking pass: search + append to data/history.jsonl
python3 report.py           # full ranked table from history so far
python3 report.py --alerts  # only rows at a new all-time low or past the drop threshold
python3 windows.py          # print the current candidate window set (no network)
python3 -m unittest test_windows -v   # verify the calendar engine
```

**A twice-weekly Routine is set up** (Tue/Sat 8am Pacific, trigger
`trig_01XnCeZYSUsqtTGUwQN9NwqZ`) using `create_new_session_on_fire`, so
each check runs in a fresh container with a push notification on
completion. Because that container is thrown away after the run, its
prompt does three things beyond just running the scripts:

1. Checks out `claude/flight-price-tracking-skill-im1t3y` explicitly --
   the skill isn't on `main`, so a default checkout wouldn't have it.
2. After `track.py` appends new rows, **commits and pushes
   `data/history.jsonl` back to the branch.** This is not optional --
   without it, every firing starts from an empty history file (fresh
   container, nothing survives that isn't in git) and the 30-day-median
   and trend logic in `report.py` would silently reset to nothing every
   single run instead of accumulating.
3. Skips `track.py` entirely (rather than logging a wall of null prices)
   if `AMADEUS_CLIENT_ID`/`AMADEUS_CLIENT_SECRET` aren't set, and says so
   in its reply instead.

If the branch above ever gets merged or renamed, update the trigger's
prompt (`update_trigger`) to match -- it hardcodes that branch name since
Routine prompts can't reference "whatever this session was on."

## Price source: Amadeus production tier, not test, not scraping

`providers/amadeus.py` calls Amadeus's live **production** Flight Offers
Search API (`api.amadeus.com`), not the test host -- the test environment
serves a cached, unrepresentative fare subset. Production is still free
under the self-service monthly quota; it requires a card on file. Get
credentials at https://developers.amadeus.com and export:

```
export AMADEUS_CLIENT_ID=...
export AMADEUS_CLIENT_SECRET=...
```

Without these set, `track.py` still runs and records every window (so the
history file's shape stays consistent), just with `price_usd: null` and a
warning on stderr.

**Google Flights scraping was considered and rejected** for the recurring,
unattended part of this skill: it violates Google's Terms of Service for
automated querying, and headless-browser access from a shared cloud IP is
exactly the profile their bot defenses (CAPTCHA, rate limiting) are built
to block -- it would produce silent gaps or garbage data feeding the trend
history, not a reliability tradeoff worth taking for a skill meant to run
unattended for months. If a live, human-supervised spot-check against
Google Flights is ever wanted, that's a one-off ask-Claude-to-look
interaction in a session, not something this skill automates.

**Southwest is unreachable through Amadeus, or any GDS, at any tier** --
Southwest doesn't distribute fares through GDS channels at all, so this
is not a provider-tier problem. Chicago Midway (MDW) and Houston Hobby
(HOU) are marked `southwest_only_airports` in `config.json`; for those,
`track.py` records a Southwest.com deep link per window instead of a
price, and `report.py` surfaces them as a "NO FARE" row with the link
rather than silently dropping them.

## Files

- `config.json` -- airports, holidays, work schedule, PTO-buying rules,
  alert thresholds. Edit this, not the code, to change destinations or
  the holiday calendar.
- `windows.py` -- pure calendar engine (PTO cost model, candidate window
  generation). No network calls; safe to unit test.
- `test_windows.py` -- stdlib `unittest` coverage of the PTO cost rules
  and window generation invariants.
- `providers/amadeus.py` -- OAuth2 + Flight Offers Search client.
- `track.py` -- orchestrates windows x destinations x origins -> Amadeus
  (or Southwest deep link) -> appends to `data/history.jsonl`.
- `report.py` -- reads history, computes each window's price vs. its own
  30-day median and vs. the destination's overall median, flags new
  all-time lows and drops past `config.json`'s `alerts.drop_pct_threshold`.
- `data/history.jsonl` -- append-only observation log, one JSON object per
  line: `{checked_at, destination, depart, return, nights, pto_days,
  origin_airport, dest_airport, price_usd, carrier, southwest_links}`.

## Changing the destination set or holidays

Edit `config.json`'s `destinations` or `holidays` arrays and re-run
`python3 windows.py` to see the new candidate set before tracking against
it -- no code changes needed for either.
