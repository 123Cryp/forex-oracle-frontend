"""
Unit tests for ForexCrossRateOracle's pure, deterministic parsing and
extraction helpers: domain/path extraction, rate parsing, ISO-8601
timestamp parsing, and fixed-vocabulary word matching. None of these
touch gl.nondet or gl.message, so they run as plain Python.
"""
import unittest

from _bootstrap import make_contract


class DomainExtractionTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_plain_domain(self):
        self.assertEqual(self.c._extract_domain("https://xe.com/page"), "xe.com")

    def test_www_prefix_collapses_to_registrable_domain(self):
        self.assertEqual(self.c._extract_domain("https://www.xe.com/page"), "xe.com")

    def test_http_scheme_accepted(self):
        self.assertEqual(self.c._extract_domain("http://oanda.com/x"), "oanda.com")

    def test_missing_scheme_rejected(self):
        self.assertEqual(self.c._extract_domain("xe.com/page"), "")

    def test_multi_part_suffix_domain(self):
        self.assertEqual(
            self.c._extract_domain("https://www.bankofengland.co.uk/rates"),
            "bankofengland.co.uk",
        )

    def test_org_uk_suffix_domain(self):
        self.assertEqual(
            self.c._extract_domain("https://exchangerates.org.uk/x"),
            "exchangerates.org.uk",
        )

    def test_overlong_url_rejected(self):
        long_url = "https://xe.com/" + ("a" * 3000)
        self.assertEqual(self.c._extract_domain(long_url), "")

    def test_port_and_query_stripped(self):
        self.assertEqual(
            self.c._extract_domain("https://xe.com:8443/page?x=1#frag"), "xe.com"
        )


class PathExtractionTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_root_path_is_empty(self):
        self.assertEqual(self.c._extract_path("https://xe.com/"), "")
        self.assertEqual(self.c._extract_path("https://xe.com"), "")

    def test_path_with_trailing_slash_normalized(self):
        self.assertEqual(
            self.c._extract_path("https://xe.com/currency/eur-usd/"),
            "/currency/eur-usd",
        )

    def test_query_and_fragment_stripped_from_path(self):
        self.assertEqual(
            self.c._extract_path("https://xe.com/currency/eur-usd?x=1#y"),
            "/currency/eur-usd",
        )


class EndpointRequirementParsingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_bare_domain(self):
        self.assertEqual(self.c._parse_endpoint_requirement("xe.com"), ("xe.com", ""))

    def test_domain_with_path_no_scheme(self):
        self.assertEqual(
            self.c._parse_endpoint_requirement("xe.com/currency/eur-usd"),
            ("xe.com", "/currency/eur-usd"),
        )

    def test_full_url(self):
        self.assertEqual(
            self.c._parse_endpoint_requirement("https://xe.com/currency/eur-usd"),
            ("xe.com", "/currency/eur-usd"),
        )

    def test_blank_entry(self):
        self.assertEqual(self.c._parse_endpoint_requirement("   "), ("", ""))


class RateParsingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_plain_decimal(self):
        self.assertEqual(self.c._parse_rate("1.0850"), 1.085)

    def test_leading_dollar_symbol(self):
        self.assertEqual(self.c._parse_rate("$1.0850"), 1.085)

    def test_thousands_separator(self):
        self.assertEqual(self.c._parse_rate("1,234.5"), 1234.5)

    def test_trailing_unit_text_ignored(self):
        self.assertEqual(self.c._parse_rate("149.87 JPY"), 149.87)

    def test_negative_rejected(self):
        self.assertIsNone(self.c._parse_rate("-1.0850"))

    def test_zero_rejected(self):
        self.assertIsNone(self.c._parse_rate("0"))

    def test_non_numeric_rejected(self):
        self.assertIsNone(self.c._parse_rate("banana"))

    def test_literal_unclear_rejected(self):
        self.assertIsNone(self.c._parse_rate("Unclear"))

    def test_ambiguous_second_number_rejected(self):
        self.assertIsNone(self.c._parse_rate("1.0850 or 1.0900"))

    def test_number_not_at_start_rejected(self):
        self.assertIsNone(self.c._parse_rate("USD 1.0850"))

    def test_empty_string_rejected(self):
        self.assertIsNone(self.c._parse_rate(""))

    def test_none_rejected(self):
        self.assertIsNone(self.c._parse_rate(None))


class IsoTimestampParsingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_z_suffix_parsed_as_utc(self):
        dt = self.c._parse_iso8601_utc("2026-09-15T12:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 12)
        self.assertEqual(str(dt.tzinfo), "UTC")

    def test_explicit_offset_converted_to_utc(self):
        dt = self.c._parse_iso8601_utc("2026-09-15T14:30:00+02:30")
        self.assertEqual((dt.hour, dt.minute), (12, 0))

    def test_naive_string_assumed_utc(self):
        dt = self.c._parse_iso8601_utc("2026-09-15T12:00:00")
        self.assertEqual(dt.hour, 12)

    def test_garbage_returns_none(self):
        self.assertIsNone(self.c._parse_iso8601_utc("not-a-date"))

    def test_empty_returns_none(self):
        self.assertIsNone(self.c._parse_iso8601_utc(""))
        self.assertIsNone(self.c._parse_iso8601_utc(None))


class FixedWordParsingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_labeled_line_matched(self):
        raw = "PAIR: Match\nFRESHNESS: Current\nRATE: 1.09\nCOMPARISON: Above"
        self.assertEqual(
            self.c._parse_fixed_word(raw, self.c.PAIR_WORDS, "Unclear", label="PAIR"),
            "Match",
        )
        self.assertEqual(
            self.c._parse_fixed_word(
                raw, self.c.FRESHNESS_WORDS, "Unknown", label="FRESHNESS"
            ),
            "Current",
        )
        self.assertEqual(
            self.c._parse_fixed_word(
                raw, self.c.COMPARISON_WORDS, "Unclear", label="COMPARISON"
            ),
            "Above",
        )

    def test_unmatched_falls_back_to_default(self):
        raw = "PAIR: something weird\n"
        self.assertEqual(
            self.c._parse_fixed_word(raw, self.c.PAIR_WORDS, "Unclear", label="PAIR"),
            "Unclear",
        )

    def test_extract_labeled_value_pulls_rate(self):
        raw = "PAIR: Match\nFRESHNESS: Current\nRATE: 1.0912\nCOMPARISON: Above"
        self.assertEqual(self.c._extract_labeled_value(raw, "RATE"), "1.0912")

    def test_extract_labeled_value_missing_label(self):
        raw = "PAIR: Match\n"
        self.assertEqual(self.c._extract_labeled_value(raw, "RATE"), "")


class ContentClassificationTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_empty_content(self):
        status, usable = self.c._classify_content("")
        self.assertEqual((status, usable), ("empty", False))

    def test_too_short_content_is_malformed(self):
        status, usable = self.c._classify_content("EUR USD 1.09")
        self.assertEqual((status, usable), ("malformed", False))

    def test_reasonable_content_is_ok(self):
        content = (
            "EUR/USD live exchange rate today is 1.0900 according to the "
            "current market session data feed updated moments ago."
        )
        status, usable = self.c._classify_content(content)
        self.assertEqual((status, usable), ("ok", True))


if __name__ == "__main__":
    unittest.main()
