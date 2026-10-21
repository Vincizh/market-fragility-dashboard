import unittest

import index_gex as ig


def chain(spot, n_exp=4, per_exp=60, call_oi=1000.0, put_oi=1000.0, iv=0.2, T=0.05):
    rows = []
    for e in range(n_exp):
        for i in range(per_exp):
            k = spot * (0.8 + 0.4 * i / per_exp)
            rows.append((T + 0.02 * e, True, k, call_oi, iv))
            rows.append((T + 0.02 * e, False, k, put_oi, iv))
    return rows


class IndexGexTests(unittest.TestCase):
    def test_gamma_positive_and_peaks_at_the_money(self):
        atm = ig.bs_gamma(100, 100, 0.1, 0.2, 0.04)
        far = ig.bs_gamma(100, 150, 0.1, 0.2, 0.04)
        self.assertGreater(atm, 0)
        self.assertGreater(atm, far)
        self.assertEqual(ig.bs_gamma(100, 100, 0.0, 0.2, 0.04), 0.0)
        self.assertEqual(ig.bs_gamma(100, 100, 0.1, 0.0, 0.04), 0.0)

    def test_empty_chain_returns_none(self):
        self.assertIsNone(ig.build_reading("SPY", 500.0, [], 0, 0.04))

    def test_thin_chain_returns_none(self):
        self.assertIsNone(ig.build_reading("SPY", 500.0, chain(500.0, n_exp=1, per_exp=10), 1, 0.04))
        self.assertIsNone(ig.build_reading("SPY", 500.0, chain(500.0, n_exp=2, per_exp=100), 2, 0.04))

    def test_sign_follows_call_put_open_interest(self):
        pos = ig.build_reading("SPY", 500.0, chain(500.0, call_oi=3000, put_oi=1000), 4, 0.04)
        neg = ig.build_reading("SPY", 500.0, chain(500.0, call_oi=1000, put_oi=3000), 4, 0.04)
        self.assertGreater(pos["net_gex"], 0)
        self.assertLess(neg["net_gex"], 0)
        self.assertEqual(pos["symbol"], "SPY")
        self.assertGreaterEqual(pos["n_contracts"], ig.MIN_CONTRACTS)

    def test_contract_cleaning(self):
        nan = float("nan")
        self.assertIsNone(ig.clean_contract(500, 0, 0.2))
        self.assertIsNone(ig.clean_contract(500, 10, nan))
        self.assertIsNone(ig.clean_contract(nan, 10, 0.2))
        self.assertIsNone(ig.clean_contract(500, 10, 9.0))
        self.assertIsNone(ig.clean_contract("x", 10, 0.2))
        self.assertEqual(ig.clean_contract("500", "10", "0.2"), (500.0, 10.0, 0.2))

    def test_snapshot_roundtrip_drops_thin_days_and_caps(self):
        snaps = {}
        reading = ig.build_reading("SPY", 500.0, chain(500.0), 4, 0.04)
        for i in range(ig.SNAP_MAX + 5):
            ig.add_snapshot(snaps, "d%04d" % i, reading)
        self.assertEqual(len(snaps), ig.SNAP_MAX)
        snaps["thin"] = {"net_gex": 1.0, "n_contracts": 3}
        html = "<body>" + ig.state_block({"SPY": snaps}) + "</body>"
        loaded = ig.load_state(html)
        self.assertNotIn("thin", loaded["SPY"])
        self.assertEqual(len(loaded["SPY"]), ig.SNAP_MAX)

    def test_cached_reading_uses_last_snapshot_and_flags_date(self):
        reading = ig.build_reading("QQQ", 400.0, chain(400.0), 4, 0.04)
        snaps = ig.add_snapshot({}, "2026-10-01", reading)
        ig.add_snapshot(snaps, "2026-10-02", reading)
        c = ig.cached_reading("QQQ", snaps)
        self.assertEqual(c["cached_date"], "2026-10-02")
        self.assertIsNone(ig.cached_reading("QQQ", {}))

    def test_load_state_bad_input(self):
        self.assertEqual(ig.load_state(""), {})
        self.assertEqual(ig.load_state('<script id="hgex-state" type="application/json">{bad</script>'), {})


if __name__ == "__main__":
    unittest.main()
