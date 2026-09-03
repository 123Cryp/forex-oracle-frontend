"""
End-to-end tests of resolve_agreement. gl.nondet.web.render and
gl.nondet.exec_prompt are mocked per test to simulate specific source
content and LLM responses; every other step (fetching, prompt
construction, deterministic rate comparison, aggregation, party
binding of the winner) runs for real through contract.py.
"""
import datetime
import json
import unittest
from unittest.mock import patch

from _bootstrap import (
    PARTY_A_ADDRESS,
    PARTY_B_ADDRESS,
    gl,
    make_contract,
    set_caller,
)


def iso_in(seconds_from_now: float) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=seconds_from_now
    )
    return dt.isoformat()


def create_and_accept(c, comparison="above", threshold_rate="1.0850",
                       required_source_domains=None):
    required_source_domains = required_source_domains or ["xe.com", "oanda.com"]
    set_caller(PARTY_A_ADDRESS)
    aid = c.create_agreement(
        party_b_address=PARTY_B_ADDRESS,
        currency_pair="EUR/USD",
        threshold_rate=threshold_rate,
        comparison=comparison,
        description="End-to-end test agreement",
        resolution_deadline=iso_in(c.MIN_DEADLINE_LEAD_SECONDS + 5),
        required_source_domains=required_source_domains,
    )
    set_caller(PARTY_B_ADDRESS)
    c.accept_agreement(aid)

    # Fast-forward past the deadline without waiting in real time, by
    # rewriting stored timestamps directly (same technique used in
    # test_party_binding_and_timing.py).
    record = json.loads(c.agreements[aid])
    record["resolution_deadline"] = iso_in(-5)
    record["resolution_window_closes_at"] = iso_in(c.RESOLUTION_WINDOW_SECONDS)
    c.agreements[aid] = json.dumps(record, sort_keys=True)
    return aid


CURRENT_ABOVE_CONTENT = (
    "EUR/USD live exchange rate today is 1.0950, updated moments ago "
    "as of the current trading session for all major currency pairs."
)
CURRENT_BELOW_CONTENT = (
    "EUR/USD live exchange rate today is 1.0700, updated moments ago "
    "as of the current trading session for all major currency pairs."
)


def llm_response_for(content):
    # Timestamp must be within [deadline - 24h, deadline]
    # Since deadline is ~300 seconds in future, use deadline - 1 hour
    # (which is still before deadline, within the 24-hour window)
    valid_timestamp = iso_in(-3600)  # 1 hour before now = well within window
    if "1.0950" in content:
        return f"PAIR: Match\nFRESHNESS: Current\nRATE: 1.0950\nTIMESTAMP: {valid_timestamp}\nCOMPARISON: Above"
    if "1.0700" in content:
        return f"PAIR: Match\nFRESHNESS: Current\nRATE: 1.0700\nTIMESTAMP: {valid_timestamp}\nCOMPARISON: Below"
    return f"PAIR: Unclear\nFRESHNESS: Unknown\nRATE: Unclear\nTIMESTAMP: {valid_timestamp}\nCOMPARISON: Unclear"


class ResolveHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_two_sources_above_threshold_party_a_wins(self):
        aid = create_and_accept(self.c, comparison="above")
        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(
            gl.nondet, "exec_prompt",
            side_effect=lambda prompt, response_format="text": llm_response_for(CURRENT_ABOVE_CONTENT),
        ):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["final_verdict"], "Above")
        self.assertEqual(result["winner"], "party_a")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["independent_source_count"], 2)

    def test_two_sources_below_threshold_party_b_wins_when_agreement_is_above(self):
        aid = create_and_accept(self.c, comparison="above")
        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_BELOW_CONTENT
        ), patch.object(
            gl.nondet, "exec_prompt",
            side_effect=lambda prompt, response_format="text": llm_response_for(CURRENT_BELOW_CONTENT),
        ):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["final_verdict"], "Below")
        self.assertEqual(result["winner"], "party_b")

    def test_comparison_below_agreement_party_a_wins_on_below_verdict(self):
        aid = create_and_accept(self.c, comparison="below")
        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_BELOW_CONTENT
        ), patch.object(
            gl.nondet, "exec_prompt",
            side_effect=lambda prompt, response_format="text": llm_response_for(CURRENT_BELOW_CONTENT),
        ):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["winner"], "party_a")


class ResolveQualityGuardrailTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_pair_mismatch_source_excluded_from_consensus(self):
        aid = create_and_accept(self.c)

        def fake_exec_prompt(prompt, response_format="text"):
            return "PAIR: Mismatch\nFRESHNESS: Current\nRATE: 1.0950\nCOMPARISON: Above"

        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(gl.nondet, "exec_prompt", side_effect=fake_exec_prompt):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["final_verdict"], "Indeterminate")
        self.assertEqual(result["winner"], "unresolved")
        for record in result["records"]:
            self.assertEqual(record["quality_flag"], "pair_mismatch")

    def test_stale_source_excluded_from_consensus(self):
        aid = create_and_accept(self.c)

        def fake_exec_prompt(prompt, response_format="text"):
            return "PAIR: Match\nFRESHNESS: Stale\nRATE: 1.0950\nCOMPARISON: Above"

        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(gl.nondet, "exec_prompt", side_effect=fake_exec_prompt):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["final_verdict"], "Indeterminate")
        for record in result["records"]:
            self.assertEqual(record["quality_flag"], "stale_or_unknown_freshness")

    def test_unparseable_rate_excluded_from_consensus(self):
        aid = create_and_accept(self.c)

        def fake_exec_prompt(prompt, response_format="text"):
            return "PAIR: Match\nFRESHNESS: Current\nRATE: Unclear\nCOMPARISON: Unclear"

        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(gl.nondet, "exec_prompt", side_effect=fake_exec_prompt):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["final_verdict"], "Indeterminate")
        for record in result["records"]:
            self.assertEqual(record["quality_flag"], "rate_unparseable")

    def test_self_reported_comparison_disagreeing_with_deterministic_excluded(self):
        # Source content says the rate is 1.0950 (above the 1.0850
        # threshold), but the model's own COMPARISON claims "Below" -
        # the contract must trust the deterministic Python comparison,
        # not the model's self-report, and flag the mismatch.
        aid = create_and_accept(self.c)

        def fake_exec_prompt(prompt, response_format="text"):
            valid_timestamp = iso_in(-3600)  # Valid within deadline window
            return f"PAIR: Match\nFRESHNESS: Current\nRATE: 1.0950\nTIMESTAMP: {valid_timestamp}\nCOMPARISON: Below"

        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(gl.nondet, "exec_prompt", side_effect=fake_exec_prompt):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        for record in result["records"]:
            self.assertEqual(record["quality_flag"], "comparison_mismatch")
        self.assertEqual(result["final_verdict"], "Indeterminate")

    def test_fetch_timeout_excluded_from_consensus(self):
        aid = create_and_accept(self.c)

        def fake_render(url, mode="text"):
            raise Exception("request timed out")

        with patch.object(gl.nondet.web, "render", side_effect=fake_render):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        for record in result["records"]:
            self.assertEqual(record["fetch_status"], "timeout")
        self.assertEqual(result["final_verdict"], "Indeterminate")

    def test_indeterminate_result_leaves_agreement_open_for_retry(self):
        aid = create_and_accept(self.c)

        def fake_exec_prompt(prompt, response_format="text"):
            return "PAIR: Mismatch\nFRESHNESS: Unknown\nRATE: Unclear\nCOMPARISON: Unclear"

        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(gl.nondet, "exec_prompt", side_effect=fake_exec_prompt):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )
        self.assertEqual(result["status"], "open")
        self.assertEqual(result["winner"], "unresolved")
        self.assertEqual(result["resolution_attempts"], 1)


class ResolveGuardrailAndTimingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_too_few_source_urls_rejected(self):
        aid = create_and_accept(self.c)
        with self.assertRaises(gl.vm.UserError):
            self.c.resolve_agreement(aid, ["https://www.xe.com/x"])

    def test_too_many_source_urls_rejected(self):
        aid = create_and_accept(self.c)
        urls = [f"https://xe.com/{i}" for i in range(7)]
        with self.assertRaises(gl.vm.UserError):
            self.c.resolve_agreement(aid, urls)

    def test_missing_a_required_domain_rejected_before_any_fetch(self):
        aid = create_and_accept(
            self.c, required_source_domains=["xe.com", "oanda.com"]
        )
        with patch.object(gl.nondet.web, "render") as mock_render:
            with self.assertRaises(gl.vm.UserError):
                # Only submits xe.com twice - oanda.com (committed at
                # creation time) is never represented.
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/a", "https://www.xe.com/b"]
                )
            mock_render.assert_not_called()

    def test_resolve_before_open_status_rejected(self):
        set_caller(PARTY_A_ADDRESS)
        aid = self.c.create_agreement(
            party_b_address=PARTY_B_ADDRESS,
            currency_pair="EUR/USD",
            threshold_rate="1.0850",
            comparison="above",
            description="Not yet accepted",
            resolution_deadline=iso_in(3600),
            required_source_domains=["xe.com", "oanda.com"],
        )
        with self.assertRaises(gl.vm.UserError):
            self.c.resolve_agreement(
                aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
            )

    def test_resolve_on_already_resolved_agreement_rejected(self):
        aid = create_and_accept(self.c)
        with patch.object(
            gl.nondet.web, "render", side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT
        ), patch.object(
            gl.nondet, "exec_prompt",
            side_effect=lambda prompt, response_format="text": llm_response_for(CURRENT_ABOVE_CONTENT),
        ):
            self.c.resolve_agreement(
                aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
            )
        with self.assertRaises(gl.vm.UserError):
            self.c.resolve_agreement(
                aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
            )


class ProductionPromptContractEndToEndTests(unittest.TestCase):
    """
    Regression test for a real bug: the production extraction prompt
    built by _build_extraction_prompt (called from resolve_agreement)
    must actually ask the model for a fifth TIMESTAMP field, in
    addition to PAIR / FRESHNESS / RATE / COMPARISON. If the prompt
    text does not request TIMESTAMP, gl.nondet.exec_prompt will never
    return one, source_timestamp will always be empty, and every
    resolution will silently fail with quality_flag =
    "timestamp_invalid_or_stale" for every source, forever making
    resolve_agreement unusable in production.

    This test does NOT hand-construct a mocked LLM response in
    isolation from the prompt; it inspects the actual prompt text that
    resolve_agreement builds and sends to gl.nondet.exec_prompt, and
    only returns a TIMESTAMP field in the mocked reply BECAUSE the
    prompt is verified to ask for one - proving the whole pipeline
    (prompt -> five-field parse -> timestamp validation -> quorum ->
    winner) is wired together correctly end-to-end with the exact
    five-line output contract PAIR/FRESHNESS/RATE/TIMESTAMP/COMPARISON.
    """

    def setUp(self):
        self.c = make_contract()

    def test_prompt_requires_timestamp_field(self):
        """
        The production prompt text itself must instruct the model to
        report TIMESTAMP - this is what the steward flagged as
        missing. Verified directly against the real prompt-building
        method used by resolve_agreement.
        """
        prompt = self.c._build_prompt(
            currency_pair="EUR/USD",
            threshold_rate="1.0850",
            source_content="dummy content",
        )
        self.assertIn("TIMESTAMP", prompt)
        self.assertIn("ISO-8601", prompt)
        # Must be listed as one of the five required response lines,
        # not just mentioned in passing.
        self.assertIn("TIMESTAMP: <ISO-8601 UTC value, or Unclear>", prompt)

    def test_fresh_multi_source_evidence_reaches_quorum_with_winner(self):
        """
        End-to-end: build the mocked LLM reply using the EXACT five-line
        output contract the production prompt requires (PAIR,
        FRESHNESS, RATE, TIMESTAMP, COMPARISON), with a fresh
        (near-"now") TIMESTAMP for every source. Two independent,
        reputable, agreeing sources must be enough to reach quorum,
        produce final_verdict == "Above", status == "resolved", and a
        concrete winner - proving the timestamp requirement does not
        silently block legitimate resolutions.
        """
        aid = create_and_accept(self.c)

        # Fresh timestamp must be computed relative to the agreement's
        # actual resolution_deadline (which create_and_accept rewrites
        # into the past), not wall-clock "now" - otherwise a timestamp
        # that is "fresh" by wall-clock time could still land AFTER the
        # already-passed deadline and be correctly rejected as invalid.
        deadline_str = json.loads(self.c.agreements[aid])["resolution_deadline"]
        deadline_dt = datetime.datetime.fromisoformat(deadline_str)
        fresh_timestamp = (deadline_dt - datetime.timedelta(seconds=2)).isoformat()

        # Confirm resolve_agreement actually builds a prompt containing
        # TIMESTAMP for each source before we simulate the model's reply.
        captured_prompts = []

        def fake_exec_prompt(prompt, response_format="text"):
            captured_prompts.append(prompt)
            self.assertIn("TIMESTAMP", prompt)
            return (
                "PAIR: Match\n"
                "FRESHNESS: Current\n"
                "RATE: 1.0950\n"
                f"TIMESTAMP: {fresh_timestamp}\n"
                "COMPARISON: Above"
            )

        with patch.object(
            gl.nondet.web, "render",
            side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT,
        ), patch.object(
            gl.nondet, "exec_prompt", side_effect=fake_exec_prompt,
        ):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )

        # Both sources' prompts requested TIMESTAMP.
        self.assertEqual(len(captured_prompts), 2)
        for p in captured_prompts:
            self.assertIn("TIMESTAMP", p)

        # Quorum reached with a concrete, recorded winner.
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["final_verdict"], "Above")
        self.assertEqual(result["winner"], "party_a")
        self.assertEqual(len(result["records"]), 2)
        for record in result["records"]:
            self.assertEqual(record["quality_flag"], "ok")
            self.assertEqual(record["comparison"], "Above")
            self.assertFalse(record["is_dissenting"])

    def test_missing_timestamp_in_reply_flags_source_and_blocks_quorum(self):
        """
        If a source's reply genuinely omits TIMESTAMP (model answers
        "Unclear"), that source must be excluded via quality_flag =
        "timestamp_invalid_or_stale" - the exact flag name the
        contract emits and declares in QUALITY_FLAGS - and, with only
        one remaining eligible source, quorum must fail
        (Indeterminate), never silently resolving on incomplete
        evidence.
        """
        aid = create_and_accept(self.c)
        deadline_str = json.loads(self.c.agreements[aid])["resolution_deadline"]
        deadline_dt = datetime.datetime.fromisoformat(deadline_str)
        fresh_timestamp = (deadline_dt - datetime.timedelta(seconds=2)).isoformat()

        call_count = {"n": 0}

        def fake_exec_prompt(prompt, response_format="text"):
            self.assertIn("TIMESTAMP", prompt)
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (
                    "PAIR: Match\nFRESHNESS: Current\nRATE: 1.0950\n"
                    f"TIMESTAMP: {fresh_timestamp}\nCOMPARISON: Above"
                )
            # Second source: model could not find a timestamp.
            return (
                "PAIR: Match\nFRESHNESS: Current\nRATE: 1.0950\n"
                "TIMESTAMP: Unclear\nCOMPARISON: Above"
            )

        with patch.object(
            gl.nondet.web, "render",
            side_effect=lambda url, mode="text": CURRENT_ABOVE_CONTENT,
        ), patch.object(
            gl.nondet, "exec_prompt", side_effect=fake_exec_prompt,
        ):
            result = json.loads(
                self.c.resolve_agreement(
                    aid, ["https://www.xe.com/x", "https://www.oanda.com/y"]
                )
            )

        flags = {r["domain"]: r["quality_flag"] for r in result["records"]}
        self.assertIn("timestamp_invalid_or_stale", flags.values())
        self.assertIn("timestamp_invalid_or_stale", self.c.QUALITY_FLAGS)
        self.assertEqual(result["final_verdict"], "Indeterminate")
        self.assertEqual(result["winner"], "unresolved")


if __name__ == "__main__":
    unittest.main()
