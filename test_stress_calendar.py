import unittest
from datetime import date, timedelta

import pandas as pd

import stress_calendar as sc


class StressCalendarTests(unittest.TestCase):
    def test_fomc_list_covers_window(self):
        # Fails when the hard-coded FOMC list needs extending (update from federalreserve.gov).
        self.assertTrue(sc.fomc_covers(date.today()), "FOMC calendar list ends before the 120-day window; extend FOMC_DECISION_DAYS")

    def test_fomc_dates_are_weekdays_and_sorted(self):
        self.assertEqual(sc.FOMC_DECISION_DAYS, sorted(sc.FOMC_DECISION_DAYS))
        self.assertTrue(all(d.weekday() < 5 for d in sc.FOMC_DECISION_DAYS))

    def test_rolling_window_and_known_events(self):
        today = date(2026, 10, 21)
        ev = sc.build_events(today)
        dates = [e["date"] for e in ev]
        self.assertTrue(all(today - timedelta(days=7) <= d <= today + timedelta(days=120) for d in dates))
        kinds = {(e["kind"], e["date"]) for e in ev}
        self.assertIn(("fomc", date(2026, 10, 28)), kinds)
        self.assertIn(("quarter_end", date(2026, 12, 31)), kinds)
        self.assertIn(("tax", date(2026, 12, 15)), kinds)
        self.assertIn(("refunding_ann", date(2026, 11, 4)), kinds)
        self.assertIn(("refunding_settle", date(2026, 11, 16)), kinds)  # 15th is a Sunday

    def test_status_labels(self):
        ev = sc.build_events(date(2026, 10, 21))
        self.assertTrue(all(e["status"] in ("announced", "scheduled", "estimated") for e in ev))
        self.assertTrue(all(e["status"] == "estimated" for e in ev if e["kind"].startswith("refunding")))

    def test_coupon_settlements_from_upcoming(self):
        up = pd.DataFrame({
            "security_type": ["Note", "Note", "Bill"], "security_term": ["2-Year", "5-Year", "4-Week"],
            "issue_date": pd.to_datetime(["2026-11-02", "2026-11-02", "2026-10-27"]),
            "offering_amt": [69e9, float("nan"), 80e9]})
        ev = sc.build_events(date(2026, 10, 21), up)
        coupon = [e for e in ev if e["kind"] == "coupon"]
        self.assertEqual(len(coupon), 1)
        self.assertEqual(coupon[0]["date"], date(2026, 11, 2))
        self.assertIn("not yet announced", coupon[0]["label"])
        self.assertEqual(coupon[0]["status"], "announced")

    def test_weekly_load_counts_weights(self):
        today = date(2026, 10, 21)
        ev = sc.build_events(today)
        wk = sc.weekly_load(ev, today)
        self.assertEqual(sum(w["load"] for w in wk), sum(e["weight"] for e in ev))
        self.assertEqual(len(sc.chart_payload(wk)), len(wk))


if __name__ == "__main__":
    unittest.main()
