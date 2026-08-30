"""
Unit tests for quorum rules and dissenting source handling in _aggregate.
These tests verify Steward feedback: explicit quorum enforcement when sources
disagree, and proper flagging of dissenting (minority) sources.
"""
import unittest

from _bootstrap import make_contract


def record(
    comparison="Above",
    fetch_status="ok",
    is_duplicate_domain=False,
    is_reputable=True,
    quality_flag="ok",
    domain="xe.com",
):
    return {
        "comparison": comparison,
        "fetch_status": fetch_status,
        "is_duplicate_domain": is_duplicate_domain,
        "is_reputable": is_reputable,
        "quality_flag": quality_flag,
        "domain": domain,
        "is_dissenting": False,  # Will be set by _aggregate
    }


class QuorumRulesTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_two_sources_both_above_agreement(self):
        """Two sources, both Above threshold — should resolve Above."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Above")
        # Neither should be marked dissenting
        for r in records:
            self.assertFalse(r["is_dissenting"])

    def test_two_sources_both_below_agreement(self):
        """Two sources, both Below threshold — should resolve Below."""
        records = [
            record(comparison="Below", domain="xe.com"),
            record(comparison="Below", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Below")
        for r in records:
            self.assertFalse(r["is_dissenting"])

    def test_two_sources_both_equal_agreement(self):
        """Two sources, both Equal — should resolve Equal."""
        records = [
            record(comparison="Equal", domain="xe.com"),
            record(comparison="Equal", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Equal")
        for r in records:
            self.assertFalse(r["is_dissenting"])

    def test_two_sources_disagree_above_vs_below(self):
        """Two sources disagree: one Above, one Below — Indeterminate."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Below", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Indeterminate")

    def test_two_sources_disagree_above_vs_equal(self):
        """Two sources disagree: one Above, one Equal — Indeterminate."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Equal", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Indeterminate")

    def test_two_sources_disagree_below_vs_equal(self):
        """Two sources disagree: one Below, one Equal — Indeterminate."""
        records = [
            record(comparison="Below", domain="xe.com"),
            record(comparison="Equal", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Indeterminate")

    def test_three_sources_two_above_one_below(self):
        """Three sources: 2 Above, 1 Below — majority Above wins, 1 dissenting."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
            record(comparison="Below", domain="bloomberg.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Above")
        
        # Check dissenting flags
        above_records = [r for r in records if r["comparison"] == "Above"]
        below_records = [r for r in records if r["comparison"] == "Below"]
        
        for r in above_records:
            self.assertFalse(r["is_dissenting"])
        for r in below_records:
            self.assertTrue(r["is_dissenting"])

    def test_three_sources_two_below_one_above(self):
        """Three sources: 2 Below, 1 Above — majority Below wins, 1 dissenting."""
        records = [
            record(comparison="Below", domain="xe.com"),
            record(comparison="Below", domain="oanda.com"),
            record(comparison="Above", domain="bloomberg.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Below")
        
        below_records = [r for r in records if r["comparison"] == "Below"]
        above_records = [r for r in records if r["comparison"] == "Above"]
        
        for r in below_records:
            self.assertFalse(r["is_dissenting"])
        for r in above_records:
            self.assertTrue(r["is_dissenting"])

    def test_four_sources_three_above_one_below(self):
        """Four sources: 3 Above, 1 Below — majority Above, 1 dissenting."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
            record(comparison="Above", domain="bloomberg.com"),
            record(comparison="Below", domain="reuters.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Above")
        
        above_records = [r for r in records if r["comparison"] == "Above"]
        below_records = [r for r in records if r["comparison"] == "Below"]
        
        for r in above_records:
            self.assertFalse(r["is_dissenting"])
        for r in below_records:
            self.assertTrue(r["is_dissenting"])

    def test_four_sources_two_above_two_below_deadlock(self):
        """Four sources: 2 Above, 2 Below — deadlock, Indeterminate."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
            record(comparison="Below", domain="bloomberg.com"),
            record(comparison="Below", domain="reuters.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Indeterminate")

    def test_five_sources_three_equal_two_above(self):
        """Five sources: 3 Equal, 2 Above — majority Equal, 2 dissenting."""
        records = [
            record(comparison="Equal", domain="xe.com"),
            record(comparison="Equal", domain="oanda.com"),
            record(comparison="Equal", domain="bloomberg.com"),
            record(comparison="Above", domain="reuters.com"),
            record(comparison="Above", domain="wsj.com"),
        ]
        result = self.c._aggregate(records)
        self.assertEqual(result, "Equal")
        
        equal_records = [r for r in records if r["comparison"] == "Equal"]
        above_records = [r for r in records if r["comparison"] == "Above"]
        
        for r in equal_records:
            self.assertFalse(r["is_dissenting"])
        for r in above_records:
            self.assertTrue(r["is_dissenting"])


class DissentingSourceAuditTests(unittest.TestCase):
    """Verify that dissenting sources are properly recorded for audit trail."""

    def setUp(self):
        self.c = make_contract()

    def test_dissenting_sources_in_evidence_trail(self):
        """Dissenting sources should be in evidence trail with is_dissenting=true."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
            record(comparison="Below", domain="bloomberg.com"),
        ]
        self.c._aggregate(records)
        
        # Verify is_dissenting flag is set on all records
        self.assertTrue(
            any(r["is_dissenting"] for r in records),
            "At least one record should be marked dissenting"
        )
        
        # Verify the Below record is marked dissenting (in minority)
        below_record = [r for r in records if r["comparison"] == "Below"][0]
        self.assertTrue(below_record["is_dissenting"])

    def test_all_agreeing_sources_not_dissenting(self):
        """When all sources agree, none should be marked dissenting."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
            record(comparison="Above", domain="bloomberg.com"),
        ]
        self.c._aggregate(records)
        
        for r in records:
            self.assertFalse(r["is_dissenting"])


class QualityFlagsPreservedTests(unittest.TestCase):
    """Verify that quality flags still work correctly with quorum logic."""

    def setUp(self):
        self.c = make_contract()

    def test_bad_quality_flags_excluded_from_quorum(self):
        """Sources with bad quality_flag should not count toward quorum."""
        records = [
            record(comparison="Above", quality_flag="ok", domain="xe.com"),
            record(comparison="Below", quality_flag="pair_mismatch", domain="oanda.com"),
            record(comparison="Above", quality_flag="ok", domain="bloomberg.com"),
        ]
        result = self.c._aggregate(records)
        
        # Only 2 eligible sources (the two "ok" quality), both Above → Above
        self.assertEqual(result, "Above")

    def test_duplicate_domain_excluded_from_quorum(self):
        """Duplicate domains should not count toward quorum."""
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="xe.com", is_duplicate_domain=True),
            record(comparison="Below", domain="oanda.com"),
        ]
        result = self.c._aggregate(records)
        
        # Only 2 eligible sources (one xe.com, one oanda.com)
        # They disagree → Indeterminate
        self.assertEqual(result, "Indeterminate")


if __name__ == "__main__":
    unittest.main()
