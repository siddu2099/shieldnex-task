"""ShieldNex Aerospace Email Checker - API Integration Automated Tests.

Validates:
1. Endpoints and static asset delivery (GET /, GET /docs, /static).
2. Request validation and error codes (400, 413, 422).
3. Response schema compliance, ordering, duplicate handling, and whitespace trimming.
4. Internal server error handling (500) and data privacy (PII logging hygiene).
5. Request-scoped domain routing cache behavior through the HTTP boundary.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from checker import (
    STATUS_LIKELY_DELIVERED,
    STATUS_LIKELY_TO_BOUNCE,
    STATUS_UNKNOWN,
    DomainRoutingResult,
)

ALLOWED_STATUSES = {
    STATUS_LIKELY_DELIVERED,
    STATUS_LIKELY_TO_BOUNCE,
    STATUS_UNKNOWN,
}


@pytest.fixture
def client() -> TestClient:
    """Provide a standard FastAPI TestClient for route inspection."""
    return TestClient(app)


@pytest.fixture
def client_no_raise() -> TestClient:
    """Provide a TestClient that allows inspecting HTTP 500 error responses."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def mock_dns_routing():
    """Ensure no API test emits live DNS queries by default.

    Individual tests may override with a specific mock routing implementation.
    """
    with patch(
        "app.classify_email",
        side_effect=lambda email, routing_cache=None: {
            "email": email.strip(),
            "status": (
                STATUS_LIKELY_TO_BOUNCE
                if ("@" not in email or email.startswith("@") or email.endswith("@"))
                else STATUS_UNKNOWN
            ),
            "reason": (
                "Invalid email address syntax: Missing required delimiter."
                if ("@" not in email or email.startswith("@") or email.endswith("@"))
                else "Domain accepts mail via MX; mailbox unverified."
            ),
        },
    ) as default_mock:
        yield default_mock


# =============================================================================
# 1. Routes and Static Assets Tests
# =============================================================================

class TestRoutesAndStaticAssets:
    """Verifies all public routes and asset delivery endpoints."""

    def test_get_root_returns_200_and_html(self, client: TestClient):
        """GET / must render the primary single-page HTML interface."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "EmailCheck" in response.text
        assert 'id="emails"' in response.text
        assert 'id="check-btn"' in response.text

    def test_get_docs_returns_200(self, client: TestClient):
        """GET /docs must serve interactive OpenAPI Swagger UI."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_get_static_css_returns_200(self, client: TestClient):
        """GET /static/style.css must return the active stylesheet."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("content-type", "")
        assert "badge-delivered" in response.text
        assert "badge-bounce" in response.text
        assert "badge-unknown" in response.text

    def test_get_static_js_returns_200(self, client: TestClient):
        """GET /static/app.js must return the client interaction script."""
        response = client.get("/static/app.js")
        assert response.status_code == 200
        assert (
            "application/javascript" in response.headers.get("content-type", "")
            or "text/javascript" in response.headers.get("content-type", "")
        )
        assert "parseAddresses" in response.text


# =============================================================================
# 2. Request Validation Tests
# =============================================================================

class TestRequestValidation:
    """Validates batch input boundaries, schema validation, and error codes."""

    def test_valid_json_request_succeeds(self, client: TestClient):
        """A valid payload with an array of email strings returns HTTP 200."""
        payload = {"emails": ["ops@shieldnex.com", "pilot@shieldnex.com"]}
        response = client.post("/api/check", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["results"]) == 2

    def test_missing_emails_field_returns_422(self, client: TestClient):
        """Missing 'emails' field must return HTTP 422 Unprocessable Entity."""
        response = client.post("/api/check", json={})
        assert response.status_code == 422

    @pytest.mark.parametrize("non_array", ["user@shieldnex.com", 12345, True, {"email": "test"}])
    def test_non_array_emails_field_returns_422(self, client: TestClient, non_array: Any):
        """Non-array 'emails' field must return HTTP 422."""
        response = client.post("/api/check", json={"emails": non_array})
        assert response.status_code == 422

    def test_non_string_array_element_returns_422(self, client: TestClient):
        """Array containing non-string items must return HTTP 422."""
        response = client.post("/api/check", json={"emails": ["valid@shieldnex.com", 12345]})
        assert response.status_code == 422

    def test_empty_list_returns_400(self, client: TestClient):
        """Empty list submissions must return HTTP 400 Bad Request."""
        response = client.post("/api/check", json={"emails": []})
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "BAD_REQUEST"
        assert data["detail"] == "No non-empty email addresses were provided."

    def test_whitespace_only_list_returns_400(self, client: TestClient):
        """List containing only blank or whitespace entries must return HTTP 400."""
        response = client.post("/api/check", json={"emails": ["   ", "\t", "\n", "  "]})
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "BAD_REQUEST"
        assert data["detail"] == "No non-empty email addresses were provided."

    def test_exactly_50_non_empty_addresses_accepted(self, client: TestClient):
        """Batches containing exactly 50 non-empty addresses must succeed (HTTP 200)."""
        emails = [f"user{i}@shieldnex.com" for i in range(50)]
        response = client.post("/api/check", json={"emails": emails})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 50
        assert len(data["results"]) == 50

    def test_51_non_empty_addresses_returns_413(self, client: TestClient):
        """Batches exceeding 50 non-empty addresses must return HTTP 413 Payload Too Large."""
        emails = [f"user{i}@shieldnex.com" for i in range(51)]
        response = client.post("/api/check", json={"emails": emails})
        assert response.status_code == 413
        data = response.json()
        assert data["error"] == "BATCH_LIMIT_EXCEEDED"
        assert "Batch limit exceeded: Received 51 addresses" in data["detail"]

    def test_blank_entries_excluded_before_50_limit(self, client: TestClient):
        """Blank entries must not count toward the 50-address ceiling."""
        # 50 non-empty entries + 10 whitespace entries = 60 items, but only 50 valid
        emails = [f"user{i}@shieldnex.com" for i in range(50)] + ["   ", ""] * 5
        response = client.post("/api/check", json={"emails": emails})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 50

    def test_syntactically_invalid_address_does_not_reject_batch(self, client: TestClient):
        """A syntactically invalid address must receive an individual bounce result."""
        payload = {"emails": ["invalid-syntax-address", "valid@shieldnex.com"]}
        response = client.post("/api/check", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["results"][0]["email"] == "invalid-syntax-address"
        assert data["results"][0]["status"] == STATUS_LIKELY_TO_BOUNCE
        assert data["results"][1]["email"] == "valid@shieldnex.com"
        assert data["results"][1]["status"] == STATUS_UNKNOWN


# =============================================================================
# 3. Response Contract Tests
# =============================================================================

class TestResponseContract:
    """Validates response shape, preservation of input order, duplicates, and statuses."""

    def test_response_contract_fields_and_types(self, client: TestClient):
        """Successful response must contain integer 'total' and list 'results'."""
        payload = {"emails": ["ops@shieldnex.com"]}
        response = client.post("/api/check", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "total" in data
        assert isinstance(data["total"], int)
        assert "results" in data
        assert isinstance(data["results"], list)

        item = data["results"][0]
        assert "email" in item
        assert "status" in item
        assert "reason" in item
        assert isinstance(item["email"], str)
        assert isinstance(item["status"], str)
        assert isinstance(item["reason"], str)

    def test_total_equals_len_results(self, client: TestClient):
        """The 'total' field must equal the length of 'results'."""
        payload = {"emails": ["a@example.com", "b@example.com", "c@example.com"]}
        response = client.post("/api/check", json=payload)
        data = response.json()
        assert data["total"] == len(data["results"]) == 3

    def test_results_preserve_input_order(self, client: TestClient):
        """Returned results must preserve the exact sequence of submitted addresses."""
        ordered_emails = ["third@example.com", "first@example.com", "second@example.com"]
        response = client.post("/api/check", json={"emails": ordered_emails})
        data = response.json()
        returned_emails = [r["email"] for r in data["results"]]
        assert returned_emails == ordered_emails

    def test_duplicate_addresses_preserved(self, client: TestClient):
        """Duplicate email entries must not be deduplicated."""
        duplicates = ["dup@example.com", "other@example.com", "dup@example.com"]
        response = client.post("/api/check", json={"emails": duplicates})
        data = response.json()
        returned_emails = [r["email"] for r in data["results"]]
        assert returned_emails == duplicates
        assert data["total"] == 3

    def test_whitespace_entries_ignored_in_results(self, client: TestClient):
        """Whitespace entries must be omitted from results entirely."""
        batch = ["  valid@example.com  ", "   ", "another@example.com", ""]
        response = client.post("/api/check", json={"emails": batch})
        data = response.json()
        assert data["total"] == 2
        assert [r["email"] for r in data["results"]] == ["valid@example.com", "another@example.com"]

    def test_reasons_present_and_non_empty(self, client: TestClient):
        """Every result must include an explanatory reason string."""
        response = client.post("/api/check", json={"emails": ["valid@example.com", "invalid-user"]})
        data = response.json()
        for r in data["results"]:
            assert r["reason"] is not None
            assert len(r["reason"].strip()) > 0

    def test_returned_email_is_trimmed(self, client: TestClient):
        """Leading and trailing whitespace must be removed from returned email fields."""
        response = client.post("/api/check", json={"emails": ["   padded@example.com   "]})
        data = response.json()
        assert data["results"][0]["email"] == "padded@example.com"

    def test_status_values_strictly_allowed(self, client: TestClient):
        """Status strings must conform strictly to the 3-state specification."""
        response = client.post("/api/check", json={"emails": ["user@example.com", "bad-email"]})
        data = response.json()
        for r in data["results"]:
            assert r["status"] in ALLOWED_STATUSES


# =============================================================================
# 4. Error Handling and Data Privacy Tests
# =============================================================================

class TestErrorHandlingAndDataPrivacy:
    """Verifies internal server error safety and PII logging hygiene."""

    def test_unexpected_exception_returns_500_with_generic_error(
        self, client_no_raise: TestClient
    ):
        """Unexpected errors must return HTTP 500 with a generic machine-readable code."""
        with patch("app.classify_email", side_effect=ZeroDivisionError("Simulated bug")):
            response = client_no_raise.post("/api/check", json={"emails": ["user@example.com"]})
            assert response.status_code == 500
            data = response.json()
            assert data["error"] == "INTERNAL_SERVER_ERROR"
            assert data["detail"] == "An unexpected server error occurred while processing the verification batch."

    def test_500_does_not_expose_traceback_or_paths_or_details(
        self, client_no_raise: TestClient
    ):
        """HTTP 500 response body must not leak stack traces, internal paths, or user PII."""
        secret_email = "confidential-user@aerospace-secret.com"
        with patch("app.classify_email", side_effect=ValueError("Sensitive database schema error")):
            response = client_no_raise.post("/api/check", json={"emails": [secret_email]})
            assert response.status_code == 500
            response_text = response.text
            assert "Traceback" not in response_text
            assert "app.py" not in response_text
            assert "Sensitive database schema error" not in response_text
            assert secret_email not in response_text

    def test_logging_does_not_contain_plaintext_emails_or_batches(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ):
        """Application logs must record batch counts without user-supplied email strings."""
        caplog.set_level(logging.INFO)
        secret_email_1 = "classified-pilot@shieldnex.com"
        secret_email_2 = "orbital-ops@shieldnex.com"

        response = client.post("/api/check", json={"emails": [secret_email_1, secret_email_2]})
        assert response.status_code == 200

        logged_text = caplog.text
        assert "Processing email check batch with 2 addresses" in logged_text
        assert "Completed email check batch: 2 results produced" in logged_text
        assert secret_email_1 not in logged_text
        assert secret_email_2 not in logged_text


# =============================================================================
# 5. Request-Scoped Cache Integration Tests
# =============================================================================

class TestRequestScopedCacheIntegration:
    """Verifies that the request-scoped domain routing cache functions over HTTP."""

    def test_api_batch_shares_routing_cache_for_same_domain(self, client: TestClient):
        """Addresses sharing a domain in one request must trigger only one domain lookup."""
        lookup_counter = 0

        def counting_classify(email: str, routing_cache=None):
            nonlocal lookup_counter
            domain = email.split("@")[1].strip().lower()
            if routing_cache is not None and domain in routing_cache:
                cached = routing_cache[domain]
                return {"email": email.strip(), "status": cached.status, "reason": cached.reason}

            lookup_counter += 1
            res = DomainRoutingResult(
                status=STATUS_UNKNOWN,
                reason="Domain accepts mail via MX; mailbox unverified.",
            )
            if routing_cache is not None:
                routing_cache[domain] = res
            return {"email": email.strip(), "status": res.status, "reason": res.reason}

        with patch("app.classify_email", side_effect=counting_classify):
            batch = ["a@shieldnex.com", "b@shieldnex.com", "c@shieldnex.com"]
            response = client.post("/api/check", json={"emails": batch})
            assert response.status_code == 200
            assert lookup_counter == 1

    def test_api_subsequent_request_creates_fresh_cache(self, client: TestClient):
        """Subsequent independent API requests must not reuse cache from previous requests."""
        lookup_counter = 0

        def counting_classify(email: str, routing_cache=None):
            nonlocal lookup_counter
            domain = email.split("@")[1].strip().lower()
            if routing_cache is not None and domain in routing_cache:
                cached = routing_cache[domain]
                return {"email": email.strip(), "status": cached.status, "reason": cached.reason}

            lookup_counter += 1
            res = DomainRoutingResult(
                status=STATUS_UNKNOWN,
                reason="Domain accepts mail via MX; mailbox unverified.",
            )
            if routing_cache is not None:
                routing_cache[domain] = res
            return {"email": email.strip(), "status": res.status, "reason": res.reason}

        with patch("app.classify_email", side_effect=counting_classify):
            # Request 1
            r1 = client.post("/api/check", json={"emails": ["user1@shieldnex.com"]})
            assert r1.status_code == 200
            assert lookup_counter == 1

            # Request 2 (identical domain, but fresh request)
            r2 = client.post("/api/check", json={"emails": ["user2@shieldnex.com"]})
            assert r2.status_code == 200
            assert lookup_counter == 2
