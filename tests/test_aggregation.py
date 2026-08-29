"""
Unit tests for ForexCrossRateOracle._aggregate - the deterministic
function that combines per-source records into one final verdict.
Pure function of a list of dicts; no gl.nondet or gl.message needed.
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
    }


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_two_agreeing_sources_above(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
        ]
        self.assertEqual(self.c._aggregate(records), "Above")

    def test_two_agreeing_sources_below(self):
        records = [
            record(comparison="Below", domain="xe.com"),
            record(comparison="Below", domain="oanda.com"),
        ]
        self.assertEqual(self.c._aggregate(records), "Below")

    def test_two_agreeing_sources_equal(self):
        records = [
            record(comparison="Equal", domain="xe.com"),
            record(comparison="Equal", domain="oanda.com"),
        ]
        self.assertEqual(self.c._aggregate(records), "Equal")

    def test_single_eligible_source_is_indeterminate(self):
        # MIN_INDEPENDENT_SOURCES is 2 - one good source alone can't decide.
        records = [record(comparison="Above", domain="xe.com")]
        self.assertEqual(self.c._aggregate(records), "Indeterminate")

    def test_disagreeing_sources_indeterminate(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Below", domain="oanda.com"),
        ]
        self.assertEqual(self.c._aggregate(records), "Indeterminate")

    def test_non_reputable_source_excluded(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="sketchy-fx-blog.com", is_reputable=False),
        ]
        self.assertEqual(self.c._aggregate(records), "Indeterminate")

    def test_duplicate_domain_excluded(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="xe.com", is_duplicate_domain=True),
        ]
        self.assertEqual(self.c._aggregate(records), "Indeterminate")

    def test_failed_fetch_excluded(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Unclear", domain="oanda.com", fetch_status="timeout"),
        ]
        self.assertEqual(self.c._aggregate(records), "Indeterminate")

    def test_bad_quality_flag_excluded(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(
                comparison="Unclear",
                domain="oanda.com",
                quality_flag="pair_mismatch",
            ),
        ]
        self.assertEqual(self.c._aggregate(records), "Indeterminate")

    def test_three_sources_majority_wins(self):
        records = [
            record(comparison="Above", domain="xe.com"),
            record(comparison="Above", domain="oanda.com"),
            record(comparison="Below", domain="investing.com"),
        ]
        self.assertEqual(self.c._aggregate(records), "Above")

    def test_empty_records_list(self):
        self.assertEqual(self.c._aggregate([]), "Indeterminate")


if __name__ == "__main__":
    unittest.main()
