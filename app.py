"""ShieldNex Aerospace Email Checker - Web Application Entrypoint.

FastAPI application providing:
1. GET /: Renders the single-page HTML interface (templates/index.html).
2. POST /api/check: Validates and classifies batches of up to 50 email addresses.
3. /static: Static file mount for CSS and JS assets.
"""

import logging
from pathlib import Path
from typing import Dict, List, Literal

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from checker import (
    STATUS_LIKELY_DELIVERED,
    STATUS_LIKELY_TO_BOUNCE,
    STATUS_UNKNOWN,
    DomainRoutingResult,
    classify_email,
)

# -----------------------------------------------------------------------------
# Application Setup & Static Paths
# -----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="ShieldNex Aerospace Email Checker",
    version="0.1.0",
    description="Batch email validation and classification service for ShieldNex Aerospace.",
)

# Mount static directory for CSS/JS assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Initialize Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------

class CheckRequest(BaseModel):
    """Request payload containing an array of email address strings."""
    emails: List[str] = Field(
        ...,
        description="List of email addresses to validate and classify.",
        examples=[["ops@shieldnex.com", "contact@example.org"]],
    )


class EmailResult(BaseModel):
    """Individual email address classification result."""
    email: str = Field(..., description="The trimmed email address evaluated.")
    status: Literal[
        STATUS_LIKELY_DELIVERED,
        STATUS_LIKELY_TO_BOUNCE,
        STATUS_UNKNOWN,
    ] = Field(
        ...,
        description="Operational deliverability status assigned to the address.",
    )
    reason: str = Field(
        ...,
        description="Technical explanation detailing the evidence for the status.",
    )


class CheckResponse(BaseModel):
    """Response payload containing evaluation totals and ordered results."""
    total: int = Field(..., description="Total number of evaluated addresses.")
    results: List[EmailResult] = Field(
        ...,
        description="Classification results preserving input sequence and duplicates.",
    )


class ErrorResponse(BaseModel):
    """Structured error response schema."""
    error: str = Field(..., description="Machine-readable error code.")
    detail: str = Field(..., description="Human-readable explanation of the error.")


# -----------------------------------------------------------------------------
# Global Exception Handler
# -----------------------------------------------------------------------------

@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled server exceptions, log diagnostic without PII, and return HTTP 500."""
    logger.exception("Unhandled server error processing request to %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "detail": "An unexpected server error occurred while processing the verification batch.",
        },
    )


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    """Render the primary single-page application interface."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.post(
    "/api/check",
    response_model=CheckResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Empty batch or zero non-empty addresses."},
        413: {"model": ErrorResponse, "description": "Batch limit exceeded (maximum 50 addresses)."},
        422: {"description": "Malformed request body or schema validation error."},
        500: {"model": ErrorResponse, "description": "Internal server error."},
    },
)
def check_emails(payload: CheckRequest):
    """Validate and classify a batch of up to 50 email addresses.

    Processing workflow:
    1. Strip leading and trailing whitespace from each address.
    2. Filter out empty or whitespace-only entries.
    3. Validate batch boundaries (1 to 50 non-empty entries).
    4. Execute sequential classification using a request-scoped domain routing cache.
    5. Return one structured result per address in exact input sequence.
    """
    # 1. Trim whitespace and filter out blank/whitespace-only entries
    non_empty_emails: List[str] = [
        email.strip() for email in payload.emails if isinstance(email, str) and email.strip()
    ]

    # 2. Reject empty batches (zero non-empty entries)
    if not non_empty_emails:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "BAD_REQUEST",
                "detail": "No non-empty email addresses were provided.",
            },
        )

    # 3. Reject batches exceeding the 50-address ceiling
    if len(non_empty_emails) > 50:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "error": "BATCH_LIMIT_EXCEEDED",
                "detail": f"Batch limit exceeded: Received {len(non_empty_emails)} addresses. A maximum of 50 non-empty email addresses is permitted per request.",
            },
        )

    # 4. Instantiate request-scoped DNS routing cache (isolated per request)
    routing_cache: Dict[str, DomainRoutingResult] = {}

    logger.info("Processing email check batch with %d addresses", len(non_empty_emails))

    # 5. Classify every non-empty address sequentially in original sequence
    results: List[Dict[str, str]] = []
    try:
        for email_address in non_empty_emails:
            result = classify_email(email_address, routing_cache=routing_cache)
            results.append(result)
    except Exception:
        logger.exception("Unexpected error during batch email classification")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "detail": "An unexpected server error occurred while processing the verification batch.",
            },
        )

    logger.info("Completed email check batch: %d results produced", len(results))

    return CheckResponse(
        total=len(results),
        results=[
            EmailResult(
                email=r["email"],
                status=r["status"],
                reason=r["reason"],
            )
            for r in results
        ],
    )
