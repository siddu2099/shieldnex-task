"""ShieldNex Aerospace Email Checker - Classification Domain Module.

This module encapsulates:
1. RFC-compliant email syntax validation via email-validator.
2. DNS mail-routing inspection via dnspython (MX records, RFC 7505 Null MX detection,
   and RFC 5321 §5.1 implicit A/AAAA address fallback).
3. Deterministic classification of email addresses into one of three operational states:
   - 'Likely Delivered' (retained in schema, not produced in MVP due to zero-send policy)
   - 'Likely to Bounce' (definitive syntax or mail-routing failure)
   - 'Unknown' (usable routing but unverified mailbox, or inconclusive/transient DNS failure)
4. Batch-scoped in-memory domain routing caching to optimize batch checks.
"""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Dict, List, Optional, Tuple

import dns.exception
import dns.name
import dns.resolver
from email_validator import EmailNotValidError, validate_email

# -----------------------------------------------------------------------------
# Configuration Constants
# -----------------------------------------------------------------------------

# Category result constants
STATUS_LIKELY_DELIVERED: str = "Likely Delivered"
STATUS_LIKELY_TO_BOUNCE: str = "Likely to Bounce"
STATUS_UNKNOWN: str = "Unknown"

# Bounded DNS resolution timeouts
QUERY_TIMEOUT: float = 2.0     # Maximum seconds per individual DNS query
TOTAL_LIFETIME: float = 3.0    # Maximum seconds for entire domain check across all queries


# -----------------------------------------------------------------------------
# Internal Data Representations
# -----------------------------------------------------------------------------

class QueryOutcome(str, Enum):
    """Enumeration of possible discrete outcomes for a single DNS query."""
    SUCCESS = "SUCCESS"
    NO_ANSWER = "NO_ANSWER"
    NXDOMAIN = "NXDOMAIN"
    TIMEOUT = "TIMEOUT"
    NO_NAMESERVERS = "NO_NAMESERVERS"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class DomainRoutingResult:
    """Internal representation of a domain's mail-routing evaluation.

    Used for batch-scoped caching across multiple addresses sharing the same
    domain.
    """
    status: str
    reason: str


# -----------------------------------------------------------------------------
# Helper Functions: DNS Resolution & Fallback Logic
# -----------------------------------------------------------------------------

def _query_single_record(
    resolver: dns.resolver.Resolver,
    qname: str,
    rdtype: str,
    deadline: float,
) -> Tuple[QueryOutcome, Optional[dns.resolver.Answer]]:
    """Execute a single DNS query under bounded per-query and total remaining deadlines.

    Args:
        resolver: The DNS resolver to use.
        qname: The domain name to query.
        rdtype: Record type string (e.g., 'MX', 'A', 'AAAA').
        deadline: Monotonic time limit after which the overall check must abort.

    Returns:
        A tuple of (QueryOutcome, optional Answer).
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return QueryOutcome.TIMEOUT, None

    timeout = min(QUERY_TIMEOUT, remaining)
    if hasattr(resolver, "timeout"):
        resolver.timeout = timeout

    try:
        answer = resolver.resolve(qname, rdtype, lifetime=remaining)
        return QueryOutcome.SUCCESS, answer
    except dns.resolver.NXDOMAIN:
        return QueryOutcome.NXDOMAIN, None
    except dns.resolver.NoAnswer:
        return QueryOutcome.NO_ANSWER, None
    except dns.resolver.NoNameservers:
        return QueryOutcome.NO_NAMESERVERS, None
    except dns.exception.Timeout:
        return QueryOutcome.TIMEOUT, None
    except dns.exception.DNSException:
        # Handles any other dnspython protocol/socket error without concealing programming bugs
        return QueryOutcome.INCONCLUSIVE, None


def _is_null_mx(rdata: object) -> bool:
    """Check if an MX record matches the RFC 7505 Null MX specification.

    RFC 7505 specifies a single MX record with preference 0 and exchange '.'
    (root/empty).
    """
    preference = getattr(rdata, "preference", None)
    exchange = getattr(rdata, "exchange", None)
    if preference == 0 and exchange is not None:
        target = exchange.to_text().strip(".")
        return target == ""
    return False


def _check_implicit_fallback(
    domain: str,
    resolver: dns.resolver.Resolver,
    deadline: float,
) -> DomainRoutingResult:
    """Perform RFC 5321 §5.1 implicit mail-routing fallback to address records (A and AAAA).

    RFC 5321 specifies that if an MX query returns NoAnswer, mail routing falls
    back
    to the domain's own address records. A usable route is present if either an A
    or AAAA
    record exists. If both A and AAAA definitively return no records (NoAnswer
    or NXDOMAIN),
    the domain cannot route email and is classified as 'Likely to Bounce'.

    Args:
        domain: The domain to check.
        resolver: The DNS resolver.
        deadline: Monotonic deadline for resolution.

    Returns:
        DomainRoutingResult with status and explanation.
    """
    # 1. Query A records
    outcome_a, answer_a = _query_single_record(resolver, domain, "A", deadline)
    if outcome_a == QueryOutcome.SUCCESS and answer_a is not None and len(answer_a) > 0:
        return DomainRoutingResult(
            status=STATUS_UNKNOWN,
            reason="Domain has no MX records, but accepts implicit-MX fallback routing via address records (RFC 5321); mailbox existence cannot be confirmed without active sending.",
        )

    # 2. Check remaining time before AAAA query
    if deadline - time.monotonic() <= 0:
        return DomainRoutingResult(
            status=STATUS_UNKNOWN,
            reason="DNS query timed out before address fallback checks could complete.",
        )

    # 3. Query AAAA records
    outcome_aaaa, answer_aaaa = _query_single_record(resolver, domain, "AAAA", deadline)
    if outcome_aaaa == QueryOutcome.SUCCESS and answer_aaaa is not None and len(answer_aaaa) > 0:
        return DomainRoutingResult(
            status=STATUS_UNKNOWN,
            reason="Domain has no MX records, but accepts implicit-MX fallback routing via address records (RFC 5321); mailbox existence cannot be confirmed without active sending.",
        )

    # 4. Check if both A and AAAA returned definitive absence of records
    is_a_definitive_empty = outcome_a in (QueryOutcome.NO_ANSWER, QueryOutcome.NXDOMAIN)
    is_aaaa_definitive_empty = outcome_aaaa in (QueryOutcome.NO_ANSWER, QueryOutcome.NXDOMAIN)

    if is_a_definitive_empty and is_aaaa_definitive_empty:
        return DomainRoutingResult(
            status=STATUS_LIKELY_TO_BOUNCE,
            reason="Domain has no MX records and no usable A/AAAA address fallback (RFC 5321).",
        )

    # 5. Otherwise, one or both queries timed out, hit NoNameservers, or were inconclusive
    return DomainRoutingResult(
        status=STATUS_UNKNOWN,
        reason="DNS query timed out or encountered a temporary resolver failure during address fallback checks.",
    )


def _check_domain_routing(
    domain: str,
    resolver: Optional[dns.resolver.Resolver] = None,
) -> DomainRoutingResult:
    """Evaluate the mail-routing capabilities of a domain within bounded timeouts.

    Args:
        domain: Normalized ASCII/Punycode domain name.
        resolver: Optional DNS resolver instance. Defaults to system resolver.

    Returns:
        DomainRoutingResult detailing the status and technical reason.
    """
    if resolver is None:
        resolver = dns.resolver.Resolver(configure=True)

    deadline = time.monotonic() + TOTAL_LIFETIME

    # 1. Resolve MX records
    outcome_mx, answer_mx = _query_single_record(resolver, domain, "MX", deadline)

    if outcome_mx == QueryOutcome.SUCCESS and answer_mx is not None:
        records = list(answer_mx)
        null_mx_records = [r for r in records if _is_null_mx(r)]

        if len(records) == 1 and len(null_mx_records) == 1:
            # Explicit RFC 7505 Null MX record
            return DomainRoutingResult(
                status=STATUS_LIKELY_TO_BOUNCE,
                reason="Domain publishes an explicit Null MX record (RFC 7505) and rejects all incoming email.",
            )
        elif len(null_mx_records) > 0:
            # Malformed mixture of Null MX and standard MX records
            return DomainRoutingResult(
                status=STATUS_UNKNOWN,
                reason="Domain publishes an inconclusive or malformed MX configuration containing both Null MX and standard MX records.",
            )
        elif len(records) > 0:
            # Valid standard MX records present (sorted by preference per RFC 5321 §5.1)
            records.sort(key=lambda r: getattr(r, "preference", 999999))
            primary_mx = records[0].exchange.to_text().rstrip(".")
            return DomainRoutingResult(
                status=STATUS_UNKNOWN,
                reason=f"Domain accepts mail via active MX records ({primary_mx}), but recipient mailbox existence cannot be confirmed without active sending.",
            )
        else:
            # Empty record set on success (unusual, fallback to A/AAAA)
            return _check_implicit_fallback(domain, resolver, deadline)

    elif outcome_mx == QueryOutcome.NXDOMAIN:
        # Domain does not exist in DNS
        return DomainRoutingResult(
            status=STATUS_LIKELY_TO_BOUNCE,
            reason="Domain does not exist according to DNS (NXDOMAIN).",
        )

    elif outcome_mx == QueryOutcome.NO_ANSWER:
        # Domain exists but publishes no MX records: initiate RFC 5321 §5.1 implicit fallback
        return _check_implicit_fallback(domain, resolver, deadline)

    elif outcome_mx == QueryOutcome.TIMEOUT:
        return DomainRoutingResult(
            status=STATUS_UNKNOWN,
            reason="DNS query timed out while resolving mail exchangers.",
        )

    elif outcome_mx == QueryOutcome.NO_NAMESERVERS:
        return DomainRoutingResult(
            status=STATUS_UNKNOWN,
            reason="Temporary DNS nameserver or resolver failure while checking mail routing.",
        )

    else:  # outcome_mx == QueryOutcome.INCONCLUSIVE
        return DomainRoutingResult(
            status=STATUS_UNKNOWN,
            reason="Temporary or inconclusive DNS resolution failure while checking mail routing.",
        )


# -----------------------------------------------------------------------------
# Public Classification API
# -----------------------------------------------------------------------------

def classify_email(
    email: str,
    routing_cache: Optional[Dict[str, DomainRoutingResult]] = None,
    resolver: Optional[dns.resolver.Resolver] = None,
) -> Dict[str, str]:
    """Validate email syntax and inspect DNS mail routing to classify deliverability.

    Evaluates an email address against RFC syntax rules and DNS mail routing.
    Does not initiate SMTP connections or transmit messages.

    Args:
        email: The raw email address string to evaluate. Must not be empty or
          whitespace-only.
        routing_cache: Optional batch-scoped dictionary mapping domain strings
          to DomainRoutingResult instances to prevent redundant lookups within a
          single batch.
        resolver: Optional custom dns.resolver.Resolver instance (useful for
          testing). Defaults to a new system-configured resolver.

    Returns:
        Dict with keys:
            - 'email': The trimmed input address.
            - 'status': One of 'Likely Delivered', 'Likely to Bounce', or
            'Unknown'.
            - 'reason': Clear, human-readable technical rationale for the
            status.

    Raises:
        ValueError: If email is empty, contains only whitespace, or is not a
        string.
    """
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Email address must be a non-empty string.")

    trimmed_email = email.strip()

    # Step 1: RFC Syntax Validation (check_deliverability=False to avoid external DNS here)
    try:
        validated = validate_email(trimmed_email, check_deliverability=False)
    except EmailNotValidError as e:
        return {
            "email": trimmed_email,
            "status": STATUS_LIKELY_TO_BOUNCE,
            "reason": f"Invalid email address syntax: {e}",
        }

    # Step 2: Domain normalization (use ascii_domain for IDN/Punycode compatibility)
    domain = validated.ascii_domain.lower()

    # Step 3: Check batch-scoped cache if provided
    if routing_cache is not None and domain in routing_cache:
        cached_result = routing_cache[domain]
        return {
            "email": trimmed_email,
            "status": cached_result.status,
            "reason": cached_result.reason,
        }

    # Step 4: Perform DNS mail-routing checks
    routing_result = _check_domain_routing(domain, resolver=resolver)

    # Step 5: Populate batch-scoped cache if provided
    if routing_cache is not None:
        routing_cache[domain] = routing_result

    return {
        "email": trimmed_email,
        "status": routing_result.status,
        "reason": routing_result.reason,
    }
