import unittest
from datetime import date

from windows import Window, generate_windows, load_config, pto_cost


class PtoCostTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_thursday_to_monday_is_free(self):
        # Thu Sep 10 eve -> Mon Sep 14 eve: dep day free, Fri remote,
        # Sat/Sun weekend, Mon remote.
        self.assertEqual(
            pto_cost(date(2026, 9, 10), date(2026, 9, 14), self.config), 0
        )

    def test_wednesday_departure_costs_nothing_for_departure_day_itself(self):
        # The departure day is always free regardless of weekday.
        cost = pto_cost(date(2026, 12, 23), date(2026, 12, 23), self.config)
        self.assertEqual(cost, 0)

    def test_tuesday_return_costs_one_pto_day(self):
        # Thu Sep 10 -> Tue Sep 15: adds one office Tuesday over the
        # Thu-Mon baseline.
        self.assertEqual(
            pto_cost(date(2026, 9, 10), date(2026, 9, 15), self.config), 1
        )

    def test_holiday_absorbs_an_office_day(self):
        # Wed Nov 25 -> Mon Nov 30: Thu 26 (Thanksgiving) and Fri 27 (day
        # after) are both holidays, so this is free despite spanning two
        # weekday-eligible office days.
        self.assertEqual(
            pto_cost(date(2026, 11, 25), date(2026, 11, 30), self.config), 0
        )

    def test_veterans_day_bridge_costs_two(self):
        # Thu Nov 5 -> Mon Nov 16: office days Tue 10, Thu 12, Fri 13 in
        # office set? Fri is remote. Office weekdays hit: Tue 10, Wed 11
        # (Veterans Day, free), Thu 12 -> so cost should be 2 (Tue 10 +
        # Thu 12), matching the documented 2-PTO/11-night window.
        self.assertEqual(
            pto_cost(date(2026, 11, 5), date(2026, 11, 16), self.config), 2
        )

    def test_christmas_stretch_costs_two(self):
        self.assertEqual(
            pto_cost(date(2026, 12, 17), date(2026, 12, 28), self.config), 2
        )


class GenerateWindowsTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.windows = generate_windows(self.config)

    def test_every_window_within_horizon(self):
        start = date.fromisoformat(self.config["horizon"]["start"])
        end = date.fromisoformat(self.config["horizon"]["end"])
        for w in self.windows:
            self.assertGreaterEqual(w.depart, start)
            self.assertLessEqual(w.ret, end)

    def test_every_window_respects_departure_and_return_weekdays(self):
        dep_ok = set(self.config["trip_shape"]["departure_weekdays"])
        ret_ok = set(self.config["trip_shape"]["return_weekdays"])
        for w in self.windows:
            self.assertIn(w.depart.weekday(), dep_ok)
            self.assertIn(w.ret.weekday(), ret_ok)

    def test_no_window_exceeds_max_pto(self):
        max_pto = self.config["pto_buying"]["max_pto_days"]
        for w in self.windows:
            self.assertLessEqual(w.pto_days, max_pto)

    def test_paid_windows_clear_nights_per_pto_bar(self):
        min_ratio = self.config["pto_buying"]["min_nights_per_pto_day"]
        for w in self.windows:
            if w.pto_days > 0:
                self.assertGreaterEqual(w.nights, w.pto_days * min_ratio)

    def test_at_least_one_zero_pto_window_per_week_in_horizon(self):
        # Sanity check on the headline finding: PTO is not the scarce
        # resource here, price is. Every ISO week from "today" (windows.py
        # clamps its effective start to today so this doesn't need manual
        # upkeep) through the configured end should offer a free window.
        free_weeks = {
            w.depart.isocalendar()[:2] for w in self.windows if w.pto_days == 0
        }
        start = max(date.fromisoformat(self.config["horizon"]["start"]), date.today())
        end = date.fromisoformat(self.config["horizon"]["end"])
        d = start
        all_weeks = set()
        while d <= end:
            all_weeks.add(d.isocalendar()[:2])
            d += __import__("datetime").timedelta(days=1)
        missing = all_weeks - free_weeks
        # Allow the partial first/last calendar week (a Tue "today" won't
        # yet contain a Thu-eve departure) to lack a full window.
        self.assertLessEqual(len(missing), 2, f"weeks with no free window: {missing}")

    def test_thanksgiving_window_present(self):
        expected = Window(date(2026, 11, 25), date(2026, 11, 30), 0)
        self.assertIn(expected, self.windows)

    def test_christmas_window_present(self):
        expected = Window(date(2026, 12, 23), date(2026, 12, 28), 0)
        self.assertIn(expected, self.windows)


if __name__ == "__main__":
    unittest.main()
