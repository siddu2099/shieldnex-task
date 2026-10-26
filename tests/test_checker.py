"""ShieldNex Aerospace Email Checker - Classification Engine Automated Tests.

Validates:
1. Input and RFC syntax validation.
2. Deterministic DNS mail-routing classifications with mocked DNS fixtures.
3. Bounded per-query timeout (2.0s) and total deadline (3.0s) behavior.
4. Batch-scoped domain routing cache behavior and isolation.
5. Deliverability policy compliance (zero-send, no unverified Likely Delivered).
"""

import sys
from pathlib import Path
from typing import Dict, List
from unittest.mock import Mock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

import dns.exception
import dns.message
import dns.name
import dns.rdataclass
import dns.rdatatype
import dns.resolver

from checker import (
    QUERY_TIMEOUT,
    STATUS_LIKELY_DELIVERED,
    STATUS_LIKELY_TO_BOUNCE,
    STATUS_UNKNOWN,
    TOTAL_LIFETIME,
    DomainRoutingResult,
    classify_email,
)

ALLOWED_STATUSES = {
    STATUS_LIKELY_DELIVERED,
    STATUS_LIKELY_TO_BOUNCE,
    STATUS_UNKNOWN,
}


# =============================================================================
# Helper: Construct Real dnspython Answer Objects
# =============================================================================

def make_mock_answer(qname: str, rdtype: str, records: List[str]) -> dns.resolver.Answer:
    """Create a genuine dnspython Answer object from RFC DNS message text.

    Avoids internal mocking of response structures by constructing real
    dnspython Answer instances parsed via dns.message.from_text.
    """
    clean_qname = qname.rstrip(".") + "."
    text_records = "\n".join(f"{clean_qname} 300 IN {rdtype} {rec}" for rec in records)
    raw_zone = f"""id 1234
opcode QUERY
rcode NOERROR
flags QR AA RD
;QUESTION
{clean_qname} IN {rdtype}
;ANSWER
{text_records}
"""
    msg = dns.message.from_text(raw_zone)
    return dns.resolver.Answer(
        dns.name.from_text(clean_qname),
        dns.rdatatype.from_text(rdtype),
        dns.rdataclass.IN,
        msg,
    )


# =============================================================================
# 1. Input and Syntax Validation Tests
# =============================================================================

class TestInputAndSyntaxValidation:
    """Validates boundary checking, whitespace trimming, and RFC syntax validation."""

    def test_empty_email_raises_value_error(self):
        """Empty string input must immediately raise ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            classify_email("")

    def test_whitespace_only_email_raises_value_error(self):
        """Whitespace-only input must raise ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            classify_email("   \t  \n  ")

    @pytest.mark.parametrize("invalid_type", [None, 123, ["email@example.com"], {"email": "test"}])
    def test_non_string_email_raises_value_error(self, invalid_type):
        """Non-string inputs must raise ValueError."""
        with pytest.raises(ValueError, match="non-empty string"):
            classify_email(invalid_type)

    @pytest.mark.parametrize(
        "malformed_address",
        [
            "invalid-no-at-sign",
            "@missing-local-part.com",
            "missing-domain-part@",
            "user@exa mple.com",
            "user@-invalid-domain.com",
            "user@domain..com",
        ],
    )
    def test_obviously_malformed_email_returns_likely_to_bounce(self, malformed_address):
        """Addresses violating RFC syntax must evaluate to 'Likely to Bounce'."""
        result = classify_email(malformed_address)
        assert result["status"] == STATUS_LIKELY_TO_BOUNCE
        assert result["email"] == malformed_address
        assert "Invalid email address syntax:" in result["reason"]

    def test_malformed_syntax_explanation_is_informative(self):
        """Malformed syntax must return a specific and human-readable explanation."""
        result = classify_email("missing-at-sign.com")
        assert result["status"] == STATUS_LIKELY_TO_BOUNCE
        assert "An email address must have an @-sign" in result["reason"]

    def test_malformed_address_triggers_no_dns_queries(self):
        """Syntax errors must terminate evaluation early without executing DNS queries."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        result = classify_email("invalid-email-syntax", resolver=mock_resolver)
        assert result["status"] == STATUS_LIKELY_TO_BOUNCE
        assert mock_resolver.resolve.call_count == 0

    def test_leading_and_trailing_whitespace_trimmed_in_returned_email(self):
        """Returned result must preserve the trimmed user input."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "shieldnex.com", "MX", ["10 mail.shieldnex.com."]
        )
        raw_input = "   pilot@shieldnex.com   \t"
        result = classify_email(raw_input, resolver=mock_resolver)
        assert result["email"] == "pilot@shieldnex.com"
        assert result["status"] == STATUS_UNKNOWN

    def test_classification_uses_only_allowed_status_strings(self):
        """Results must only utilize the approved three operational status strings."""
        res_invalid = classify_email("invalid")
        assert res_invalid["status"] in ALLOWED_STATUSES

        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "shieldnex.com", "MX", ["10 mail.shieldnex.com."]
        )
        res_valid = classify_email("valid@shieldnex.com", resolver=mock_resolver)
        assert res_valid["status"] in ALLOWED_STATUSES


# =============================================================================
# 2. DNS Mail-Routing Classification Tests (Mocked)
# =============================================================================

class TestDnsClassification:
    """Validates all DNS classification decision branches using offline fixtures."""

    def test_dns_nxdomain_returns_likely_to_bounce(self):
        """NXDOMAIN confirms domain nonexistence and must classify as 'Likely to Bounce'."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.side_effect = dns.resolver.NXDOMAIN(
            qnames=[dns.name.from_text("nonexistent-domain-12345.org.")]
        )
        result = classify_email("contact@nonexistent-domain-12345.org", resolver=mock_resolver)
        assert result["status"] == STATUS_LIKELY_TO_BOUNCE
        assert "NXDOMAIN" in result["reason"]

    def test_dns_valid_ordinary_mx_record_returns_unknown(self):
        """Standard MX record presence classifies as Unknown (unverified mailbox in MVP)."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "example.com", "MX", ["10 mail.example.com.", "20 backup.example.com."]
        )
        result = classify_email("user@example.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "mail.example.com" in result["reason"]
        assert "mailbox existence cannot be confirmed" in result["reason"]

    def test_dns_mx_records_out_of_order_sorted_by_preference(self):
        """RFC 5321 §5.1: MX records must be sorted by numerical preference to find primary exchanger."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        # Records arrive with higher preference numbers first
        mock_resolver.resolve.return_value = make_mock_answer(
            "multi-mx.org", "MX", ["50 backup.multi-mx.org.", "5 primary.multi-mx.org.", "20 relay.multi-mx.org."]
        )
        result = classify_email("contact@multi-mx.org", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "primary.multi-mx.org" in result["reason"]
        assert "backup.multi-mx.org" not in result["reason"]

    def test_dns_explicit_rfc7505_null_mx_returns_likely_to_bounce(self):
        """RFC 7505 Null MX (preference 0, target '.') explicitly rejects mail."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "nomail-domain.org", "MX", ["0 ."]
        )
        result = classify_email("admin@nomail-domain.org", resolver=mock_resolver)
        assert result["status"] == STATUS_LIKELY_TO_BOUNCE
        assert "Null MX" in result["reason"]
        assert "RFC 7505" in result["reason"]

    def test_dns_malformed_mixture_null_mx_returns_unknown(self):
        """Mixture of Null MX and standard MX is ambiguous/malformed and classifies as Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "mixed-mx.org", "MX", ["0 .", "10 mail.mixed-mx.org."]
        )
        result = classify_email("ops@mixed-mx.org", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "inconclusive or malformed MX configuration" in result["reason"]

    def test_dns_mx_timeout_returns_unknown(self):
        """DNS query timeout is a network latency event, not nonexistence."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.side_effect = dns.exception.Timeout()
        result = classify_email("user@laggy-nameserver.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "timed out" in result["reason"].lower()

    def test_dns_nonameservers_returns_unknown(self):
        """NoNameservers / SERVFAIL is transient infrastructure failure, yielding Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.side_effect = dns.resolver.NoNameservers()
        result = classify_email("user@servfail-domain.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "Temporary DNS nameserver or resolver failure" in result["reason"]

    def test_dns_no_answer_mx_with_a_fallback_returns_unknown(self):
        """RFC 5321 implicit fallback: No MX, but valid A record present yields Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        def mock_resolve(qname, rdtype, **kwargs):
            if rdtype == "MX":
                raise dns.resolver.NoAnswer()
            if rdtype == "A":
                return make_mock_answer(str(qname), "A", ["192.0.2.1"])
            raise dns.resolver.NoAnswer()

        mock_resolver.resolve.side_effect = mock_resolve
        result = classify_email("contact@implicit-routing.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "accepts implicit-MX fallback routing via address records" in result["reason"]

    def test_dns_no_answer_mx_no_a_with_aaaa_fallback_returns_unknown(self):
        """RFC 5321 implicit fallback: No MX, No A, but valid AAAA record yields Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        def mock_resolve(qname, rdtype, **kwargs):
            if rdtype == "MX":
                raise dns.resolver.NoAnswer()
            if rdtype == "A":
                raise dns.resolver.NoAnswer()
            if rdtype == "AAAA":
                return make_mock_answer(str(qname), "AAAA", ["2001:db8::1"])
            raise dns.resolver.NoAnswer()

        mock_resolver.resolve.side_effect = mock_resolve
        result = classify_email("ipv6@implicit-routing.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "accepts implicit-MX fallback routing via address records" in result["reason"]

    def test_dns_no_answer_mx_no_a_no_aaaa_returns_likely_to_bounce(self):
        """Exhaustion of MX, A, and AAAA definitively confirms no mail destination."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        def mock_resolve(qname, rdtype, **kwargs):
            raise dns.resolver.NoAnswer()

        mock_resolver.resolve.side_effect = mock_resolve
        result = classify_email("undeliverable@no-mail-destination.org", resolver=mock_resolver)
        assert result["status"] == STATUS_LIKELY_TO_BOUNCE
        assert "Domain has no MX records and no usable A/AAAA address fallback" in result["reason"]

    def test_dns_fallback_a_fails_temporarily_but_aaaa_succeeds(self):
        """If A query times out but AAAA has valid records, usable routing is established."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        def mock_resolve(qname, rdtype, **kwargs):
            if rdtype == "MX":
                raise dns.resolver.NoAnswer()
            if rdtype == "A":
                raise dns.exception.Timeout()
            if rdtype == "AAAA":
                return make_mock_answer(str(qname), "AAAA", ["2001:db8::1"])
            raise dns.resolver.NoAnswer()

        mock_resolver.resolve.side_effect = mock_resolve
        result = classify_email("user@ipv6-rescued.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "accepts implicit-MX fallback routing" in result["reason"]

    def test_dns_fallback_temporary_failure_without_usable_route_returns_unknown(self):
        """If A query times out and AAAA returns NoAnswer, outcome is inconclusive (Unknown)."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        def mock_resolve(qname, rdtype, **kwargs):
            if rdtype == "MX":
                raise dns.resolver.NoAnswer()
            if rdtype == "A":
                raise dns.exception.Timeout()
            if rdtype == "AAAA":
                raise dns.resolver.NoAnswer()
            raise dns.resolver.NoAnswer()

        mock_resolver.resolve.side_effect = mock_resolve
        result = classify_email("user@temporary-failure.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert "temporary resolver failure during address fallback checks" in result["reason"]

    def test_unexpected_programming_exception_propagates(self):
        """Unexpected internal exceptions (non-DNS) must propagate rather than return Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.side_effect = RuntimeError("Fatal disk corruption in resolver")

        with pytest.raises(RuntimeError, match="Fatal disk corruption"):
            classify_email("user@corrupted.com", resolver=mock_resolver)

    def test_nxdomain_distinguished_from_temporary_resolver_failure(self):
        """NXDOMAIN yields Likely to Bounce, whereas SERVFAIL/Timeout yields Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        # 1. NXDOMAIN -> Bounce
        mock_resolver.resolve.side_effect = dns.resolver.NXDOMAIN(
            qnames=[dns.name.from_text("dead-domain.com.")]
        )
        res_nx = classify_email("test@dead-domain.com", resolver=mock_resolver)
        assert res_nx["status"] == STATUS_LIKELY_TO_BOUNCE

        # 2. SERVFAIL / NoNameservers -> Unknown
        mock_resolver.resolve.side_effect = dns.resolver.NoNameservers()
        res_servfail = classify_email("test@temporary-glitch.com", resolver=mock_resolver)
        assert res_servfail["status"] == STATUS_UNKNOWN


# =============================================================================
# 3. Timeout and Monotonic Clock Deadline Tests
# =============================================================================

class TestTimeoutAndDeadlineBehavior:
    """Validates bounded query timeout and total routing deadline enforcement."""

    def test_dns_query_uses_configured_timeouts(self):
        """Resolver queries must enforce per-query and total bounded limits."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.timeout = None
        mock_resolver.resolve.return_value = make_mock_answer("shieldnex.com", "MX", ["10 mail.shieldnex.com."])

        classify_email("pilot@shieldnex.com", resolver=mock_resolver)

        assert mock_resolver.timeout <= QUERY_TIMEOUT
        _, kwargs = mock_resolver.resolve.call_args
        assert kwargs.get("lifetime") <= TOTAL_LIFETIME

    def test_deadline_expiration_before_fallback_returns_unknown(self):
        """If clock exceeds total deadline during resolution, fallback aborts with Unknown."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.side_effect = dns.resolver.NoAnswer()

        clock_ticks = [100.0, 100.0, 104.0, 104.5]
        clock_idx = 0

        def simulated_monotonic():
            nonlocal clock_idx
            val = clock_ticks[min(clock_idx, len(clock_ticks) - 1)]
            clock_idx += 1
            return val

        with patch("checker.time.monotonic", side_effect=simulated_monotonic):
            result = classify_email("user@deadline-expired.org", resolver=mock_resolver)
            assert result["status"] == STATUS_UNKNOWN
            assert "timed out" in result["reason"].lower()

    def test_subsequent_lookups_respect_remaining_deadline(self):
        """A and AAAA queries must use min(QUERY_TIMEOUT, remaining_time)."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        resolved_lifetimes: List[float] = []

        def tracking_resolve(qname, rdtype, lifetime=None, **kwargs):
            resolved_lifetimes.append(lifetime)
            raise dns.resolver.NoAnswer()

        mock_resolver.resolve.side_effect = tracking_resolve

        # Clock sequence:
        # Start: 100.0 (deadline 103.0)
        # MX: 100.0 -> remaining 3.0 -> lifetime=3.0
        # A: 101.8 -> remaining 1.2 -> lifetime=1.2
        # AAAA: 102.6 -> remaining 0.4 -> lifetime=0.4
        clock_ticks = [100.0, 100.0, 101.8, 101.8, 102.6, 102.6, 103.0]
        clock_idx = 0

        def simulated_monotonic():
            nonlocal clock_idx
            val = clock_ticks[min(clock_idx, len(clock_ticks) - 1)]
            clock_idx += 1
            return val

        with patch("checker.time.monotonic", side_effect=simulated_monotonic):
            result = classify_email("user@clock-audit.com", resolver=mock_resolver)
            assert result["status"] == STATUS_LIKELY_TO_BOUNCE
            assert len(resolved_lifetimes) == 3
            assert resolved_lifetimes[0] == pytest.approx(3.0, 0.1)
            assert resolved_lifetimes[1] == pytest.approx(1.2, 0.1)
            assert resolved_lifetimes[2] == pytest.approx(0.4, 0.1)


# =============================================================================
# 4. Request-Scoped Cache Behavior Tests
# =============================================================================

class TestRequestScopedCache:
    """Validates domain-routing cache reuse, isolation, and absence of global state."""

    def test_cache_reused_for_same_domain(self):
        """Addresses with identical domains must reuse cached routing evaluations."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "shieldnex.com", "MX", ["10 mail.shieldnex.com."]
        )

        batch_cache: Dict[str, DomainRoutingResult] = {}
        res1 = classify_email("alpha@shieldnex.com", routing_cache=batch_cache, resolver=mock_resolver)
        res2 = classify_email("bravo@shieldnex.com", routing_cache=batch_cache, resolver=mock_resolver)

        assert res1["status"] == STATUS_UNKNOWN
        assert res2["status"] == STATUS_UNKNOWN
        assert mock_resolver.resolve.call_count == 1
        assert "shieldnex.com" in batch_cache

    def test_different_emails_sharing_domain_receive_separate_result_objects(self):
        """Cached domain results must still populate the respective unique input email."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer("shieldnex.com", "MX", ["10 mail.shieldnex.com."])

        batch_cache: Dict[str, DomainRoutingResult] = {}
        res1 = classify_email("first@shieldnex.com", routing_cache=batch_cache, resolver=mock_resolver)
        res2 = classify_email("second@shieldnex.com", routing_cache=batch_cache, resolver=mock_resolver)

        assert res1["email"] == "first@shieldnex.com"
        assert res2["email"] == "second@shieldnex.com"
        assert res1 is not res2

    def test_different_normalized_domains_do_not_collide(self):
        """Different domains must perform separate DNS lookups and store distinct entries."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)

        def mock_resolve(qname, rdtype, **kwargs):
            target = str(qname).rstrip(".")
            return make_mock_answer(target, "MX", [f"10 mail.{target}."])

        mock_resolver.resolve.side_effect = mock_resolve

        batch_cache: Dict[str, DomainRoutingResult] = {}
        res_a = classify_email("user@domain-a.com", routing_cache=batch_cache, resolver=mock_resolver)
        res_b = classify_email("user@domain-b.com", routing_cache=batch_cache, resolver=mock_resolver)

        assert mock_resolver.resolve.call_count == 2
        assert "domain-a.com" in batch_cache
        assert "domain-b.com" in batch_cache
        assert "domain-a.com" in res_a["reason"]
        assert "domain-b.com" in res_b["reason"]

    def test_no_module_global_cache_leakage(self):
        """Separate caches must not leak across independent requests."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer("shieldnex.com", "MX", ["10 mail.shieldnex.com."])

        cache_request_1: Dict[str, DomainRoutingResult] = {}
        classify_email("req1@shieldnex.com", routing_cache=cache_request_1, resolver=mock_resolver)
        assert mock_resolver.resolve.call_count == 1

        cache_request_2: Dict[str, DomainRoutingResult] = {}
        classify_email("req2@shieldnex.com", routing_cache=cache_request_2, resolver=mock_resolver)
        assert mock_resolver.resolve.call_count == 2

    def test_calls_without_supplied_cache_work_correctly(self):
        """Calls with routing_cache=None must evaluate correctly without error."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer("shieldnex.com", "MX", ["10 mail.shieldnex.com."])

        res = classify_email("nocache@shieldnex.com", routing_cache=None, resolver=mock_resolver)
        assert res["status"] == STATUS_UNKNOWN
        assert res["email"] == "nocache@shieldnex.com"


# =============================================================================
# 5. Deliverability Status Policy Tests
# =============================================================================

class TestDeliverabilityStatusPolicy:
    """Verifies that the hosted MVP never generates Likely Delivered without evidence."""

    def test_valid_syntax_and_routing_never_produces_likely_delivered_in_mvp(self):
        """Valid syntax and valid MX records must return Unknown, not Likely Delivered."""
        mock_resolver = Mock(spec=dns.resolver.Resolver)
        mock_resolver.resolve.return_value = make_mock_answer(
            "corporate-aerospace.com", "MX", ["10 mx1.corporate-aerospace.com."]
        )

        result = classify_email("ceo@corporate-aerospace.com", resolver=mock_resolver)
        assert result["status"] == STATUS_UNKNOWN
        assert result["status"] != STATUS_LIKELY_DELIVERED
        assert "mailbox existence cannot be confirmed" in result["reason"]

    def test_status_constants_match_spec(self):
        """Ensure exported status constants strictly match REQUIREMENTS.md."""
        assert STATUS_LIKELY_DELIVERED == "Likely Delivered"
        assert STATUS_LIKELY_TO_BOUNCE == "Likely to Bounce"
        assert STATUS_UNKNOWN == "Unknown"
