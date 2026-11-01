"""Unit tests for the fragility chain, the Funding Stress Index and the coupon supply factor."""
import unittest
from datetime import date

import numpy as np
import pandas as pd

import fast_metrics as fm
import fragility_chain as fc


def ind(on):
    return fc.indicator("x", "v", on)


class StageStatus(unittest.TestCase):
    def test_counts_only_available(self):
        st = fc.stage_status([ind(True), ind(None), ind(False)])
        self.assertEqual((st["status"], st["n_on"], st["n_avail"]), ("partial", 1, 2))

    def test_two_on_confirms(self):
        self.assertEqual(fc.stage_status([ind(True), ind(True), ind(False)])["status"], "confirmed")

    def test_hard_trigger_confirms_with_one(self):
        st = fc.stage_status([ind(True), ind(False)], hard=True)
        self.assertEqual(st["status"], "confirmed")
        self.assertTrue(st["hard"])

    def test_all_missing_is_na(self):
        self.assertEqual(fc.stage_status([ind(None), ind(None)])["status"], "na")

    def test_quiet(self):
        self.assertEqual(fc.stage_status([ind(False), ind(False)])["status"], "quiet")


class Breadth(unittest.TestCase):
    def test_single_stress_capped_at_watch(self):
        self.assertEqual(fc.breadth_state(["stress", "normal", "normal"]), "watch")

    def test_two_capped_at_elevated(self):
        self.assertEqual(fc.breadth_state(["stress", "stress", "normal"]), "elevated")

    def test_three_allow_worst(self):
        self.assertEqual(fc.breadth_state(["stress", "watch", "watch"]), "stress")

    def test_na_and_context_ignored(self):
        self.assertEqual(fc.breadth_state(["na", "context", "normal"]), "normal")
        self.assertEqual(fc.breadth_state(["na"]), "na")


def base_x(**kw):
    x = {"lpi": 50.0, "lpi_stale": False, "basis": 50.0, "reserves_state": "normal", "resgdp_state": "normal",
         "sofr_med_bp": 0.0, "tgcr_bp": 0.0, "bgcr_bp": 0.0, "tail_state": "normal", "tbill_pct": 50.0,
         "effr_bp": -7.0, "effr_chg20": 0.0, "srf_b": 0.0, "srf_state": "quiet", "dw_b": 1.0, "dw_state": "quiet",
         "hy_bp": 300.0, "hy_z": 0.0, "hyig_bp": 200.0, "hyig_z": 0.0, "cccbb_pp": 6.0, "cccbb_z": 0.0,
         "rvol_bp": 80.0, "rvol_pct": 40.0, "usd_z": 0.0, "cp_bp": 10.0, "cp_pct": 50.0,
         "gamma": "positive", "vix_state": "contango", "corr2w": 0.3, "corr1m": 0.35, "spy_vol_ratio": 1.0, "spy_ret1": 0.5}
    x.update(kw)
    return x


class ChainLevel(unittest.TestCase):
    def test_all_quiet_is_normal(self):
        self.assertEqual(fc.build_chain(base_x())["level"], "normal")

    def test_stage1_confirmed_is_watch(self):
        c = fc.build_chain(base_x(sofr_med_bp=4.0, tgcr_bp=3.5))
        self.assertEqual(c["by_key"]["repo"]["status"], "confirmed")
        self.assertEqual(c["level"], "watch")

    def test_effr_at_iorb_hard_trigger(self):
        c = fc.build_chain(base_x(effr_bp=0.0))
        self.assertEqual(c["by_key"]["reserves"]["status"], "confirmed")
        self.assertIn("EFFR", c["by_key"]["reserves"]["hard_reason"])
        self.assertEqual(c["level"], "elevated")

    def test_srf_elevated_hard_trigger(self):
        c = fc.build_chain(base_x(srf_b=12.0, srf_state="elevated"))
        self.assertEqual(c["by_key"]["reserves"]["status"], "confirmed")
        self.assertIn("SRF", c["by_key"]["reserves"]["hard_reason"])

    def test_srf_in_use_alone_is_partial(self):
        c = fc.build_chain(base_x(srf_b=3.0, srf_state="in_use"))
        self.assertEqual(c["by_key"]["reserves"]["status"], "partial")
        self.assertEqual(c["level"], "normal")

    def test_two_late_stages_is_stress(self):
        c = fc.build_chain(base_x(effr_bp=0.5, hy_z=2.0, hyig_z=2.0))
        self.assertEqual(c["level"], "stress")

    def test_backdrop_raises_one_notch_only_below_elevated(self):
        c = fc.build_chain(base_x(lpi=70.0, basis=90.0))
        self.assertEqual(c["by_key"]["backdrop"]["status"], "confirmed")
        self.assertEqual(c["level"], "watch")
        c = fc.build_chain(base_x(lpi=70.0, basis=90.0, gamma="negative", vix_state="backwardation"))
        self.assertEqual(c["level"], "elevated")

    def test_stale_lpi_is_unavailable(self):
        c = fc.build_chain(base_x(lpi=90.0, lpi_stale=True))
        self.assertIsNone(c["by_key"]["backdrop"]["inds"][0]["on"])

    def test_down_day_volume_needs_negative_return(self):
        c = fc.build_chain(base_x(spy_vol_ratio=2.0, spy_ret1=0.4))
        self.assertFalse(c["by_key"]["amplification"]["inds"][3]["on"])

    def test_next_watch_points_at_first_unconfirmed(self):
        c = fc.build_chain(base_x(sofr_med_bp=4.0, tgcr_bp=3.5))
        self.assertIn("stage 2", c["next_watch"])


class FSI(unittest.TestCase):
    def test_causal_pctile_mid_rank_ties(self):
        s = pd.Series([5.0] * 300)
        p = fc.causal_pctile(s, window=1260, burn=250)
        self.assertTrue(np.isnan(p.iloc[0]))
        self.assertAlmostEqual(p.iloc[-1], 50.0)

    def test_causal_pctile_no_lookahead(self):
        s = pd.Series(np.arange(300, dtype=float))
        a = fc.causal_pctile(s, burn=250)
        b = fc.causal_pctile(pd.concat([s, pd.Series([-1.0] * 50)], ignore_index=True), burn=250)
        self.assertTrue(np.allclose(a.iloc[249:300].values, b.iloc[249:300].values))

    def test_anchor_uses_ioer_before_iorb(self):
        ioer = pd.Series([1.0, 1.0], index=pd.to_datetime(["2021-07-27", "2021-07-28"]))
        iorb = pd.Series([2.0, 2.0], index=pd.to_datetime(["2021-07-29", "2021-07-30"]))
        a = fc.anchor_rate(iorb, ioer)
        self.assertEqual(list(a.values), [1.0, 1.0, 2.0, 2.0])

    def test_fsi_bands(self):
        self.assertEqual(fc.fsi_state(59.9), "normal")
        self.assertEqual(fc.fsi_state(60.0), "watch")
        self.assertEqual(fc.fsi_state(80.0), "elevated")
        self.assertEqual(fc.fsi_state(95.0), "stress")
        self.assertEqual(fc.fsi_state(float("nan")), "na")

    def test_fsi_needs_two_components(self):
        idx = pd.bdate_range("2018-04-02", periods=400)
        sofr = pd.Series(2.0, index=idx)
        out = fc.funding_stress_index(sofr, None, None, pd.Series(2.0, index=idx))
        self.assertFalse(out["available"])

    def test_fsi_rises_with_spreads(self):
        idx = pd.bdate_range("2018-04-02", periods=600)
        rng = np.random.default_rng(0)
        anchor = pd.Series(2.0, index=idx)
        sofr = pd.Series(2.0 + rng.normal(0, 0.01, len(idx)), index=idx)
        effr = pd.Series(1.95 + rng.normal(0, 0.01, len(idx)), index=idx)
        sofr.iloc[-10:] += 0.2
        effr.iloc[-10:] += 0.2
        out = fc.funding_stress_index(sofr, effr, sofr + 0.05, anchor)
        self.assertTrue(out["available"])
        self.assertGreater(out["comp_last"]["repo"], 95)
        self.assertGreater(out["comp_last"]["interbank"], 95)
        self.assertGreater(out["value"], 75)       # the flat tail component ranks at its mid-rank, about 50


class History(unittest.TestCase):
    def snap(self, level, repo="quiet", fsi_state="normal", when="2026-11-01T00:00Z"):
        return {"when": when, "level": level, "stages": {"backdrop": "quiet", "repo": repo}, "fsi": 50.0, "fsi_state": fsi_state}

    def test_first_run_no_events(self):
        h, ev = fc.update_history({}, self.snap("normal"))
        self.assertEqual(ev, [])
        self.assertEqual(h["current"]["level"], "normal")

    def test_change_creates_event(self):
        h, _ = fc.update_history({}, self.snap("normal"))
        h, ev = fc.update_history(h, self.snap("watch", repo="confirmed"))
        kinds = sorted(e["kind"] for e in ev)
        self.assertEqual(kinds, ["level", "stage"])
        self.assertTrue(all(e["worse"] for e in ev))
        self.assertEqual(len(h["events"]), 2)

    def test_outage_is_not_relief(self):
        h, _ = fc.update_history({}, self.snap("watch", repo="confirmed"))
        h, ev = fc.update_history(h, self.snap("na", repo="na", fsi_state="na"))
        self.assertEqual(ev, [])
        self.assertEqual(h["current"]["stages"]["repo"], "confirmed")
        h, ev = fc.update_history(h, self.snap("normal", repo="quiet"))
        self.assertEqual(sorted(e["kind"] for e in ev), ["level", "stage"])


class CouponSupply(unittest.TestCase):
    def test_term_years_reopening(self):
        self.assertAlmostEqual(fm.term_years("9-Year 10-Month"), 9 + 10 / 12)
        self.assertEqual(fm.term_years("10-Year"), 10)
        self.assertTrue(np.isnan(fm.term_years("26-Week")))

    def test_frame_keeps_reopenings_drops_frn_and_dedups(self):
        fiscal = [
            {"cusip": "A", "auction_date": "2026-10-07", "security_term": "9-Year 10-Month", "security_type": "Note", "floating_rate": "No", "offering_amt": "39000000000"},
            {"cusip": "F", "auction_date": "2026-10-22", "security_term": "2-Year", "security_type": "Note", "floating_rate": "Yes", "offering_amt": "28000000000"},
            {"cusip": "B", "auction_date": "2026-10-08", "security_term": "29-Year 11-Month", "security_type": "Bond", "floating_rate": "No", "offering_amt": "22000000000"},
            {"cusip": "C", "auction_date": "2026-10-09", "security_term": "1-Year", "security_type": "Note", "floating_rate": "No", "offering_amt": "1000000000"},
        ]
        td = [
            {"cusip": "A", "competitiveAuctionCloseDate": "2026-10-07T00:00:00", "securityTerm": "9-Year 10-Month", "securityType": "Note", "floatingRate": "No", "offeringAmount": "40000000000"},
            {"cusip": "D", "competitiveAuctionCloseDate": "2026-10-28T00:00:00", "securityTerm": "7-Year", "securityType": "Note", "floatingRate": "No", "offeringAmount": "44000000000"},
        ]
        f = fm.coupon_supply_frame(fiscal, td)
        self.assertEqual(sorted(f["cusip"]), ["A", "B", "D"])
        self.assertEqual(f.loc[f["cusip"] == "A", "source"].iloc[0], "FiscalData")
        self.assertEqual(float(f.loc[f["cusip"] == "A", "amount"].iloc[0]), 39e9)

    def test_weekly_stops_at_known_through(self):
        f = fm.coupon_supply_frame([
            {"cusip": "A", "auction_date": "2026-09-02", "security_term": "10-Year", "security_type": "Note", "floating_rate": "No", "offering_amt": "40000000000"},
            {"cusip": "B", "auction_date": "2026-10-28", "security_term": "7-Year", "security_type": "Note", "floating_rate": "No", "offering_amt": "44000000000"},
        ])
        w = fm.coupon_supply_weekly(f, date(2026, 10, 1))
        self.assertLessEqual(w.index.max(), pd.Timestamp("2026-10-07"))
        self.assertAlmostEqual(w.sum(), 40.0)
        self.assertTrue((w.iloc[1:] == 0).all())


if __name__ == "__main__":
    unittest.main()
