"""Offline tests for the FRED catalog, transforms, state rules and module builders."""
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import fred_catalog as fc
import fred_modules as md
import fred_monitor as mon
import health

NOW = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)


def daily(values, end="2026-10-19"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


class CatalogTests(unittest.TestCase):
    def test_ids_unique_and_fields_valid(self):
        ids = [s.id for s in fc.CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        for s in fc.CATALOG:
            self.assertIn(s.section, fc.SECTIONS)
            self.assertIn(s.role, ("state", "context"))
            self.assertGreater(s.scale, 0)
            self.assertGreater(s.max_age_days, 0)
            self.assertTrue(s.url.endswith(s.id))
            self.assertTrue(s.label_en and s.label_zh and s.cadence)

    def test_units_documented_in_catalog(self):
        self.assertEqual(fc.BY_ID["WSHOBL"].unit_raw, "millions")
        self.assertEqual(fc.BY_ID["SOFRVOL"].unit_raw, "billions")
        self.assertAlmostEqual(fc.BY_ID["WSHOBL"].scale, 0.001)
        self.assertEqual(fc.BY_ID["BAMLH0A3HYC"].scale, 100.0)


class TransformTests(unittest.TestCase):
    def test_spread_aligns_dates(self):
        a = pd.Series([4.0, 5.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        b = pd.Series([3.5, 3.0], index=pd.to_datetime(["2026-01-02", "2026-01-03"]))
        out = mon.spread(a, b, 100.0)
        self.assertEqual(list(out.values), [150.0])

    def test_change_n_and_short_series(self):
        s = daily([1, 2, 3, 4, 5, 6])
        self.assertEqual(mon.change_n(s, 2, 100.0), 200.0)
        self.assertTrue(np.isnan(mon.change_n(s, 6)))

    def test_change_z_flags_jump_and_needs_history(self):
        rng = np.random.default_rng(0)
        base = np.cumsum(rng.normal(0, 0.01, 400)) + 5
        s = daily(list(base))
        self.assertLess(abs(mon.change_z(s, 20, 3)), 4)
        jump = s.copy()
        jump.iloc[-1] += 1.0
        self.assertGreater(mon.change_z(jump, 20, 3), 3)
        self.assertTrue(np.isnan(mon.change_z(daily([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), 5, 3)))

    def test_level_pctile_reports_actual_window(self):
        s = daily(list(range(1, 501)))
        pct, yrs = mon.level_pctile(s, 3)
        self.assertEqual(pct, 100.0)
        self.assertLessEqual(yrs, 3.01)
        pct2, yrs2 = mon.level_pctile(daily([5, 4, 3, 2, 1]), None)
        self.assertEqual(pct2, 20.0)

    def test_weekly_delta(self):
        s = pd.Series([10.0, 12.0, 11.0], index=pd.to_datetime(["2026-10-07", "2026-10-14", "2026-10-21"]))
        self.assertEqual(list(mon.weekly_delta(s).values), [2.0, -1.0])


class StateRuleTests(unittest.TestCase):
    def test_pct_state_branches(self):
        self.assertEqual(mon.pct_state(96, 2.5, 3.0), "stress")
        self.assertEqual(mon.pct_state(92, 1.2, 3.0), "elevated")
        self.assertEqual(mon.pct_state(85, 0.2, 3.0), "watch")
        self.assertEqual(mon.pct_state(40, 2.1, 3.0), "watch")
        self.assertEqual(mon.pct_state(40, 0.2, 3.0), "normal")
        self.assertEqual(mon.pct_state(99, 3.0, 0.5), "na")
        self.assertEqual(mon.pct_state(float("nan"), 1.0, 3.0), "na")

    def test_rates_state(self):
        self.assertEqual(mon.rates_state(90, 1.5, 10), ("elevated", "high and rising"))
        self.assertEqual(mon.rates_state(90, 0.2, 10), ("watch", "high"))
        self.assertEqual(mon.rates_state(50, -1.4, 10), ("normal", "falling"))
        self.assertEqual(mon.rates_state(50, 0.0, 10), ("normal", "normal"))
        self.assertEqual(mon.rates_state(50, 0.0, 0.2)[0], "na")

    def test_conditions_state(self):
        self.assertEqual(mon.conditions_state(-0.5), "normal")
        self.assertEqual(mon.conditions_state(0.3), "watch")
        self.assertEqual(mon.conditions_state(1.4), "elevated")
        self.assertEqual(mon.conditions_state(float("nan")), "na")

    def test_worst(self):
        self.assertEqual(mon.worst(["normal", "watch", "context", "na"]), "watch")
        self.assertEqual(mon.worst(["na", "context"]), "na")

    def test_backstop_branches(self):
        spec = fc.BY_ID["SWPT"]
        hist = [0.0] * 200
        quiet = mon.backstop_state(daily(hist + [0.2]), 5.0, spec, NOW)
        self.assertEqual(quiet["state"], "quiet")
        use = mon.backstop_state(daily([8.0] * 100 + [6.0] * 100 + [0.0] * 100 + [6.0]), 5.0, spec, NOW)
        self.assertEqual(use["state"], "in_use")
        elev = mon.backstop_state(daily(hist + [50.0]), 5.0, spec, NOW)
        self.assertEqual(elev["state"], "elevated")
        stale = mon.backstop_state(daily(hist + [50.0], end="2026-08-01"), 5.0, spec, NOW)
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(mon.backstop_state(None, 5.0, spec, NOW)["state"], "unavailable")

    def test_discount_window_needs_p95_and_positive_change(self):
        spec = fc.BY_ID["WLCFLPCL"]
        rising = daily(list(np.linspace(3, 11, 200)))
        self.assertEqual(mon.backstop_state(rising, None, spec, NOW)["state"], "elevated")
        falling = daily(list(np.linspace(11, 3, 200)))
        self.assertEqual(mon.backstop_state(falling, None, spec, NOW)["state"], "quiet")

    def test_srf_seven_day_sum(self):
        spec = fc.BY_ID["RPONTSYD"]
        s = daily([0.0] * 100 + [0.6, 0.6])
        r = mon.backstop_state(s, 1.0, spec, NOW, seven_day_sum=True)
        self.assertAlmostEqual(r["value"], 1.2)
        self.assertIn(r["state"], ("in_use", "elevated"))

    def test_backstops_in_use_count(self):
        self.assertEqual(mon.backstops_in_use(["quiet", "in_use", "elevated", "stale"]), 2)


class ModuleBuilderTests(unittest.TestCase):
    def _series(self):
        S = {}
        rng = np.random.default_rng(1)
        for spec in fc.CATALOG:
            n = 900
            base = 3.0 + np.cumsum(rng.normal(0, 0.02, n))
            if spec.unit_raw == "millions":
                base = np.abs(base) * 1e5
            idx = pd.bdate_range(end="2026-10-19" if spec.cadence.startswith("daily") else "2026-10-14", periods=n,
                                 freq="B" if spec.cadence.startswith("daily") else "W-WED")
            S[spec.id] = pd.Series(base[:len(idx)], index=idx[:len(base)])
        return S

    def test_all_modules_build_and_cards_have_required_fields(self):
        M = md.build_all(self._series(), NOW)
        for sec in ("funding", "fedbs", "credit", "rates"):
            self.assertIn(sec, M)
        cards = (M["funding"]["cards"] + M["funding"]["backstops"] + M["fedbs"]["cards"]
                 + M["credit"]["ladder"] + M["credit"]["cards"] + M["rates"]["cards"])
        for c in cards:
            for k in ("id", "title", "value", "state", "state_label", "sub", "what", "asof", "links"):
                self.assertIn(k, c)
            self.assertIn(c["state"], mon.STATES)
        self.assertEqual(len({c["id"] for c in cards}), len(cards))

    def test_missing_series_becomes_grey_card_not_exception(self):
        M = md.build_all({}, NOW)
        for c in M["credit"]["ladder"] + M["funding"]["backstops"] + M["rates"]["cards"]:
            self.assertEqual(c["state"], "na")
        self.assertEqual(M["credit"]["state"], "na")

    def test_stale_series_is_grey_and_keeps_value(self):
        S = self._series()
        S["BAMLH0A3HYC"] = S["BAMLH0A3HYC"].copy()
        S["BAMLH0A3HYC"].index = S["BAMLH0A3HYC"].index - pd.Timedelta(days=60)
        M = md.build_credit(S, NOW)
        ccc = next(c for c in M["ladder"] if c["id"] == "oas-ccc")
        self.assertEqual(ccc["state"], "na")
        self.assertTrue(ccc["stale"])
        self.assertNotEqual(ccc["value"], "n/a")

    def test_oas_displayed_in_bp_and_quality_in_pp(self):
        idx = pd.bdate_range(end="2026-10-19", periods=800)
        S = {"BAMLH0A3HYC": pd.Series(13.10, index=idx), "BAMLH0A1HYBB": pd.Series(2.00, index=idx)}
        M = md.build_credit(S, NOW)
        ccc = next(c for c in M["ladder"] if c["id"] == "oas-ccc")
        self.assertEqual(ccc["value"], "1,310 bp")
        self.assertEqual(M["cards"][0]["value"], "11.10 pp")

    def test_fima_and_foreign_pool_are_separate_lines(self):
        S = {"H41RESPPALGTRFNWW": pd.Series([0.0] * 20, index=pd.date_range(end="2026-10-14", periods=20, freq="W-WED")),
             "WLRRAFOIAL": pd.Series([326598.0] * 20, index=pd.date_range(end="2026-10-14", periods=20, freq="W-WED"))}
        M = md.build_funding(S, NOW)
        fima = next(c for c in M["backstops"] if c["id"] == "fima")
        pool = next(c for c in M["backstops"] if c["id"] == "frrp")
        self.assertEqual(fima["value"], "$0.0B")
        self.assertEqual(fima["backstop"], "quiet")
        self.assertEqual(pool["value"], "$327B")
        self.assertEqual(pool["state"], "context")


class HealthTests(unittest.TestCase):
    def test_registry_and_summary(self):
        health.reset()
        health.register("a", "x", "2026-10-19", "daily", "current")
        health.register("b", "x", "2026-08-19", "daily", "stale")
        health.register("c", "x", None, "daily", "failed")
        s = health.summary()
        self.assertEqual((s["total"], s["current"], s["stale"], s["failed"]), (3, 1, 1, 1))
        self.assertFalse(s["all_current"])
        self.assertIn("1/3 current", s["chip"])
        health.reset()

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            health.register("a", "x", None, "daily", "bogus")


if __name__ == "__main__":
    unittest.main()
