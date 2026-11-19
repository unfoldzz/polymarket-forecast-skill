from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import market_digest as m


class DigestTests(unittest.TestCase):
    def samples(self, name, budget=10):
        started, fetch = m.fixture_source(HERE / "fixtures" / (name + ".json"))
        return m.collect(fetch, budget, started)

    def test_terminal_dedupe_and_scope(self):
        cur = self.samples("current")
        self.assertTrue(cur["terminal_cursor_reached"])
        self.assertEqual(cur["stop"], "cursor_exhausted")
        self.assertEqual(cur["pages"], 2)
        self.assertEqual(cur["duplicate_eligible_observations"], 1)
        self.assertEqual(cur["excluded_rows"], 1)
        self.assertEqual([r["market_id"] for r in cur["markets"]], ["101","102","103","104","106"])
        self.assertEqual(cur["markets"][1]["observed_at"], "2030-05-01T11:00:03Z")

    def test_direction_identity_intervals_and_missing(self):
        ranks = m.rank(self.samples("current"), self.samples("prior"))
        a, b, changed, multi, missing = ranks["rows"]
        self.assertEqual(a["yes_token"], "11")
        self.assertEqual(Decimal(a["change_pp"]), 5)
        self.assertEqual(Decimal(b["change_pp"]), -15)
        self.assertEqual(a["comparison_interval_seconds"], 39600)
        self.assertEqual(b["comparison_interval_seconds"], 39602)
        self.assertIsNone(changed["change_pp"])
        self.assertIsNone(multi["yes"])
        self.assertIsNone(missing["yes"])
        self.assertTrue(multi["first_seen_in_sample"])
        self.assertFalse(changed["first_seen_in_sample"])
        self.assertEqual(ranks["absolute_change_ids"], ["102","101"])
        self.assertEqual(ranks["volume_24h_ids"], ["101","102"])
        self.assertEqual(ranks["liquidity_ids"], ["102","101"])

    def test_budget_and_cursor_loop_are_partial(self):
        cur = self.samples("current", budget=1)
        self.assertEqual((cur["stop"], cur["terminal_cursor_reached"]), ("page_budget", False))
        seen = []
        def fetch(cursor):
            seen.append(cursor)
            return "2030-05-01T11:00:01Z", {"markets": [{"id":"101"}], "next_cursor":"again"}
        out = m.collect(fetch, 5, "2030-05-01T11:00:00Z")
        self.assertEqual(seen, [None, "again"])
        self.assertEqual((out["stop"], out["terminal_cursor_reached"]), ("cursor_loop", False))

    def test_mid_scan_schema_failure_preserves_partial(self):
        started, good = m.fixture_source(HERE / "fixtures" / "current.json")
        def fetch(cursor):
            return good(cursor) if cursor is None else ("2030-05-01T11:00:02Z", {"rows":[]})
        out = m.collect(fetch, 10, started)
        self.assertEqual(out["stop"], "invalid_page")
        self.assertFalse(out["terminal_cursor_reached"])
        self.assertEqual([r["market_id"] for r in out["markets"]], ["101","102"])

    def test_no_lookahead_and_fixed_scope(self):
        cur, prior = self.samples("current"), self.samples("prior")
        prior["markets"][0]["observed_at"] = "2030-05-02T00:00:00Z"
        self.assertIsNone(m.rank(cur, prior)["rows"][0]["change_pp"])
        prior["scope"] = "not comparable"
        with self.assertRaises(ValueError):
            m.rank(cur, prior)

    def test_partition_requires_same_settlement_and_no_overlap(self):
        q = {"bucket A":".40", "bucket B":".30", "no event":".30"}
        out = m.event_split(q, "no event", disjoint_exhaustive=True, same_settlement=True)
        self.assertEqual(out["event_unconditional"], Decimal(".70"))
        self.assertEqual(out["largest_bucket_unconditional"], Decimal(".40"))
        self.assertEqual(out["largest_bucket_conditional_on_event"].quantize(Decimal(".0001")), Decimal(".5714"))
        for overrides in [{"disjoint_exhaustive":False}, {"same_settlement":False}]:
            args = {"disjoint_exhaustive":True,"same_settlement":True} | overrides
            with self.assertRaises(ValueError):
                m.event_split(q, "no event", **args)
        q["no event"] = ".80"
        bad = m.event_split(q, "no event", disjoint_exhaustive=True, same_settlement=True)
        self.assertFalse(bad["usable_as_distribution"])
        self.assertIsNone(bad["event_unconditional"])

    def test_cli_retains_partial_and_refuses_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = [sys.executable, str(HERE.parent / "scripts" / "market_digest.py"),
                    "--fixture", str(HERE / "fixtures" / "current.json"),
                    "--max-pages", "1", "--out", directory]
            first = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(first.returncode, 2)
            output = Path(directory) / "snapshot.json"
            original = output.read_text()
            self.assertIn('"terminal_cursor_reached": false', original)
            second = subprocess.run(argv, capture_output=True, text=True)
            self.assertIn("output exists", second.stderr)
            self.assertEqual(output.read_text(), original)
