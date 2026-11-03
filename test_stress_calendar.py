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


class UpcomingMerge(unittest.TestCase):
    def test_treasurydirect_fills_and_wins(self):
        import pandas as pd
        import stress_calendar as sc
        fiscal = pd.DataFrame({"cusip": ["A"], "security_type": ["Note"], "security_term": ["2-Year"],
                               "auction_date": ["2026-10-28"], "issue_date": ["2026-11-02"], "offering_amt": ["69000000000"]})
        td = sc.treasurydirect_upcoming_frame([
            {"cusip": "A", "securityType": "Note", "securityTerm": "2-Year", "competitiveAuctionCloseDate": "2026-10-28T00:00:00",
             "issueDate": "2026-11-02T00:00:00", "offeringAmount": "70000000000", "floatingRate": "No", "inflationProtected": "No"},
            {"cusip": "B", "securityType": "Note", "securityTerm": "2-Year", "competitiveAuctionCloseDate": "2026-10-29T00:00:00",
             "issueDate": "2026-10-31T00:00:00", "floatingRate": "Yes", "inflationProtected": "No"},
            {"cusip": "C", "securityType": "Note", "securityTerm": "10-Year", "competitiveAuctionCloseDate": "2026-11-19T00:00:00",
             "issueDate": "2026-11-30T00:00:00", "floatingRate": "No", "inflationProtected": "Yes"}])
        m = sc.merge_upcoming(fiscal, td)
        self.assertEqual(len(m), 3)
        self.assertEqual(float(m.loc[m["cusip"] == "A", "offering_amt"].iloc[0]), 70e9)
        self.assertEqual(m.loc[m["cusip"] == "B", "security_type"].iloc[0], "FRN")
        self.assertEqual(m.loc[m["cusip"] == "C", "security_type"].iloc[0], "TIPS Note")

    def test_both_empty(self):
        import stress_calendar as sc
        self.assertTrue(sc.merge_upcoming(None, None).empty)
