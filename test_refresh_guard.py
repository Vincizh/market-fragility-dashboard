import unittest
from datetime import datetime, timezone

import refresh_guard as rg


def h(gen="2026-11-03 04:00 UTC", **st):
    return {"generated_at": gen, "sources": [{"name": k, "status": v} for k, v in st.items()]}


class Skip(unittest.TestCase):
    now = datetime(2026, 11, 3, 4, 20, tzinfo=timezone.utc)

    def test_recent_schedule_skips(self):
        self.assertTrue(rg.should_skip(h(), "schedule", self.now))

    def test_old_schedule_runs(self):
        self.assertFalse(rg.should_skip(h(gen="2026-11-03 03:30 UTC"), "schedule", self.now))

    def test_dispatch_never_skips(self):
        self.assertFalse(rg.should_skip(h(), "workflow_dispatch", self.now))

    def test_missing_health_runs(self):
        self.assertFalse(rg.should_skip({}, "schedule", self.now))


class Retry(unittest.TestCase):
    def test_new_failure_retries(self):
        t = rg.retry_targets(h(A="current", B="current"), h(A="failed", B="current"), 0, [], "success")
        self.assertEqual(t, ["A"])
        self.assertEqual(rg.next_attempt(0, t), 1)

    def test_long_running_outage_does_not_retry(self):
        t = rg.retry_targets(h(A="failed"), h(A="failed"), 0, [], "success")
        self.assertEqual(t, [])
        self.assertIsNone(rg.next_attempt(0, t))

    def test_cached_counts_as_failure(self):
        self.assertEqual(rg.retry_targets(h(A="current"), h(A="cached"), 0, [], "success"), ["A"])

    def test_stale_source_lag_is_not_retried(self):
        self.assertEqual(rg.retry_targets(h(A="current"), h(A="stale"), 0, [], "success"), [])

    def test_retry_run_follows_its_list(self):
        t = rg.retry_targets(h(A="failed"), h(A="current", B="failed"), 1, ["A", "B"], "success")
        self.assertEqual(t, ["B"])

    def test_job_failure_retries_until_budget(self):
        t = rg.retry_targets({}, {}, 2, ["job"], "failure")
        self.assertEqual(t, ["job"])
        self.assertEqual(rg.next_attempt(2, t), 3)
        self.assertIsNone(rg.next_attempt(rg.MAX_ATTEMPTS, t))

    def test_new_source_counts_as_previously_current(self):
        self.assertEqual(rg.retry_targets(h(), h(N="failed"), 0, [], "success"), ["N"])


if __name__ == "__main__":
    unittest.main()
