import unittest

import dash_state as ds


class DashStateTests(unittest.TestCase):
    def test_roundtrip_and_prune(self):
        days = {}
        for i in range(60):
            days = ds.update(days, "2026-01-%02d" % (i % 28 + 1) if i < 28 else "2026-02-%02d" % (i - 27), {"a": {"s": "normal", "t": "1"}})
        self.assertLessEqual(len(days), ds.KEEP_DAYS)
        html = "<html>" + ds.block(days) + "</html>"
        self.assertEqual(ds.load(html), days)

    def test_load_bad_input(self):
        self.assertEqual(ds.load(""), {})
        self.assertEqual(ds.load('<script id="dash-state" type="application/json">{oops</script>'), {})

    def test_pick_base_window(self):
        days = {"2026-10-01": {}, "2026-10-12": {}, "2026-10-14": {}, "2026-10-20": {}}
        self.assertEqual(ds.pick_base(days, "2026-10-21"), "2026-10-14")
        self.assertIsNone(ds.pick_base({"2026-10-20": {}}, "2026-10-21"))

    def test_compare_reports_state_change_only(self):
        days = {"2026-10-14": {"credit": {"s": "watch", "t": "300 bp", "label": "Credit"},
                               "rates": {"s": "normal", "t": "5%", "label": "Rates"}}}
        snap = {"credit": {"s": "stress", "t": "330 bp", "label": "Credit"}, "rates": {"s": "normal", "t": "5.1%", "label": "Rates"}}
        base, ch = ds.compare(days, "2026-10-21", snap)
        self.assertEqual(base, "2026-10-14")
        self.assertEqual([c["key"] for c in ch], ["credit"])


if __name__ == "__main__":
    unittest.main()
