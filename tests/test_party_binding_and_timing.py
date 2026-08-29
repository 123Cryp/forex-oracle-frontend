"""
Unit tests for the three headline security properties: address-based
party binding, resolution deadline / expiry timing, and mandatory
multi-source commitment validation. Also covers the plain create /
accept / cancel / expire state machine and the read-only views.

None of these call resolve_agreement's nondet pipeline, so no web/LLM
mocking is needed here - see test_end_to_end.py for that.
"""
import datetime
import json
import unittest

from _bootstrap import (
    PARTY_A_ADDRESS,
    PARTY_B_ADDRESS,
    STRANGER_ADDRESS,
    gl,
    make_contract,
    set_caller,
)


def iso_in(seconds_from_now: float) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=seconds_from_now
    )
    return dt.isoformat()


def create_default_agreement(c, **overrides):
    set_caller(PARTY_A_ADDRESS)
    kwargs = dict(
        party_b_address=PARTY_B_ADDRESS,
        currency_pair="EUR/USD",
        threshold_rate="1.0850",
        comparison="above",
        description="Test agreement",
        resolution_deadline=iso_in(3600),
        required_source_domains=["xe.com", "oanda.com"],
    )
    kwargs.update(overrides)
    return c.create_agreement(**kwargs)


def force_deadline_passed(c, agreement_id):
    """Rewrite stored resolution_deadline into the past, to test
    behavior after the deadline without actually waiting."""
    record = json.loads(c.agreements[agreement_id])
    record["resolution_deadline"] = iso_in(-5)
    c.agreements[agreement_id] = json.dumps(record, sort_keys=True)


def force_window_closed(c, agreement_id):
    """Rewrite stored resolution_deadline and resolution_window_closes_at
    so both are already in the past."""
    record = json.loads(c.agreements[agreement_id])
    record["resolution_deadline"] = iso_in(-c.RESOLUTION_WINDOW_SECONDS - 3600)
    record["resolution_window_closes_at"] = iso_in(-5)
    c.agreements[agreement_id] = json.dumps(record, sort_keys=True)


class CreateAgreementValidationTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_happy_path_binds_party_a_to_caller(self):
        aid = create_default_agreement(self.c)
        record = json.loads(self.c.agreements[aid])
        self.assertEqual(record["party_a"].lower(), PARTY_A_ADDRESS.lower())
        self.assertEqual(record["party_b"].lower(), PARTY_B_ADDRESS.lower())
        self.assertEqual(record["status"], "pending_acceptance")

    def test_party_b_same_as_caller_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, party_b_address=PARTY_A_ADDRESS)

    def test_invalid_party_b_address_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, party_b_address="not-an-address")

    def test_currency_pair_without_slash_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, currency_pair="EURUSD")

    def test_currency_pair_same_base_and_quote_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, currency_pair="EUR/EUR")

    def test_unsupported_currency_code_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, currency_pair="EUR/XYZ")

    def test_unparseable_threshold_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, threshold_rate="not-a-number")

    def test_invalid_comparison_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, comparison="sideways")

    def test_empty_description_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, description="   ")

    def test_overlong_description_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, description="x" * 500)

    def test_missing_required_domains_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, required_source_domains=[])

    def test_single_required_domain_rejected(self):
        # MIN_INDEPENDENT_SOURCES is 2 - one domain alone is insufficient.
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, required_source_domains=["xe.com"])

    def test_too_many_required_domains_rejected(self):
        domains = [
            "xe.com", "oanda.com", "investing.com", "tradingeconomics.com",
            "x-rates.com", "fxstreet.com", "bloomberg.com",
        ]  # 7 entries, MAX_SOURCES_SUBMITTED is 6
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, required_source_domains=domains)

    def test_non_allowlisted_domain_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(
                self.c, required_source_domains=["xe.com", "some-random-blog.com"]
            )

    def test_duplicate_domain_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(
                self.c, required_source_domains=["xe.com", "xe.com"]
            )

    def test_deadline_too_soon_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, resolution_deadline=iso_in(60))

    def test_deadline_too_far_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(
                self.c, resolution_deadline=iso_in(365 * 24 * 3600 * 2)
            )

    def test_unparseable_deadline_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            create_default_agreement(self.c, resolution_deadline="not-a-date")

    def test_deadline_exactly_at_minimum_lead_is_accepted(self):
        # Should NOT raise - a small cushion above the exact minimum
        # avoids flakiness from the few milliseconds of test execution
        # time between computing iso_in() and the contract's own
        # internal "now" check.
        aid = create_default_agreement(
            self.c, resolution_deadline=iso_in(self.c.MIN_DEADLINE_LEAD_SECONDS + 5)
        )
        self.assertEqual(aid, "0")


class AcceptCancelStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.aid = create_default_agreement(self.c)

    def test_party_a_cannot_accept_own_agreement(self):
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.accept_agreement(self.aid)

    def test_stranger_cannot_accept(self):
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.accept_agreement(self.aid)

    def test_party_b_can_accept(self):
        set_caller(PARTY_B_ADDRESS)
        result = json.loads(self.c.accept_agreement(self.aid))
        self.assertEqual(result["status"], "open")
        self.assertIsNotNone(result["accepted_at"])

    def test_double_accept_rejected(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.accept_agreement(self.aid)
        with self.assertRaises(gl.vm.UserError):
            self.c.accept_agreement(self.aid)

    def test_accept_after_deadline_passed_rejected(self):
        force_deadline_passed(self.c, self.aid)
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.accept_agreement(self.aid)

    def test_party_a_can_cancel_before_acceptance(self):
        set_caller(PARTY_A_ADDRESS)
        result = json.loads(self.c.cancel_agreement(self.aid))
        self.assertEqual(result["status"], "cancelled")

    def test_party_b_cannot_cancel(self):
        set_caller(PARTY_B_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.cancel_agreement(self.aid)

    def test_stranger_cannot_cancel(self):
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.cancel_agreement(self.aid)

    def test_cannot_cancel_after_acceptance(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.accept_agreement(self.aid)
        set_caller(PARTY_A_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.cancel_agreement(self.aid)


class ExpireAgreementTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.aid = create_default_agreement(self.c)

    def test_expire_before_deadline_rejected(self):
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_agreement(self.aid)

    def test_pending_agreement_expires_after_deadline(self):
        force_deadline_passed(self.c, self.aid)
        result = json.loads(self.c.expire_agreement(self.aid))
        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["winner"], "unresolved")

    def test_open_agreement_cannot_expire_before_window_closes(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.accept_agreement(self.aid)
        force_deadline_passed(self.c, self.aid)  # deadline passed, window still open
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_agreement(self.aid)

    def test_open_agreement_expires_after_window_closes(self):
        set_caller(PARTY_B_ADDRESS)
        self.c.accept_agreement(self.aid)
        force_window_closed(self.c, self.aid)
        result = json.loads(self.c.expire_agreement(self.aid))
        self.assertEqual(result["status"], "expired")

    def test_cancelled_agreement_cannot_expire(self):
        set_caller(PARTY_A_ADDRESS)
        self.c.cancel_agreement(self.aid)
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_agreement(self.aid)

    def test_expire_is_permissionless(self):
        force_deadline_passed(self.c, self.aid)
        set_caller(STRANGER_ADDRESS)  # anyone may call expire_agreement
        result = json.loads(self.c.expire_agreement(self.aid))
        self.assertEqual(result["status"], "expired")


class ReadOnlyViewTests(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_total_agreements_increments(self):
        self.assertEqual(self.c.total_agreements(), 0)
        create_default_agreement(self.c)
        self.assertEqual(self.c.total_agreements(), 1)
        create_default_agreement(self.c)
        self.assertEqual(self.c.total_agreements(), 2)

    def test_get_agreement_unknown_id_raises(self):
        with self.assertRaises(gl.vm.UserError):
            self.c.get_agreement("999")

    def test_get_role_reports_each_party_correctly(self):
        aid = create_default_agreement(self.c)
        self.assertEqual(self.c.get_role(aid, PARTY_A_ADDRESS), "party_a")
        self.assertEqual(self.c.get_role(aid, PARTY_B_ADDRESS), "party_b")
        self.assertEqual(self.c.get_role(aid, STRANGER_ADDRESS), "none")


if __name__ == "__main__":
    unittest.main()
