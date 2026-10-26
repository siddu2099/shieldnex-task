# Requirements and Classification Specification
**Project:** ShieldNex Aerospace Email Checker  
**Target Program:** ShieldNex Aerospace Software Development Internship Selection Task  
**Document Phase:** Phase 0 — Baseline Requirements & Technical Specification  
**Status:** Frozen / Approved for Implementation  

---

## 1. Project Objective and Scope

### 1.1 Objective
The **ShieldNex Aerospace Email Checker** is a lightweight, high-reliability web application designed to validate and triage batches of email addresses into three distinct operational states:
1. `Likely Delivered`
2. `Likely to Bounce`
3. `Unknown`

Each submitted email must be evaluated individually and returned with its assigned classification alongside a precise, human-readable technical rationale detailing the evidence (or lack thereof) supporting the evaluation.

### 1.2 Scope
- **Batch Processing:** Support batch inputs of up to 50 email addresses per single HTTP request.
- **Verification Depth:** Verification is strictly non-intrusive and limited to:
  - RFC-compliant syntax validation via `email-validator`.
  - DNS mail-routing resolution via `dnspython` (MX records, Null MX per RFC 7505, and RFC 5321 §5.1 implicit address fallback).
- **Safe Execution:** The application performs **no actual email transmission** and **no direct SMTP mailbox probing**.
- **User Interface:** A single-page, server-rendered interface with vanilla JavaScript client logic delivering asynchronous batch submissions, live client validation, and clear tabular reporting.
- **Target Audience:** Internal operators at ShieldNex Aerospace requiring deterministic, fast triage of communication contact lists without external third-party data leakage.

---

## 2. Fixed Technology Stack

The technology stack is strictly constrained to standard, well-maintained, open-source Python and web technologies. No additional frameworks, external databases, or third-party validation APIs may be introduced.

| Layer | Technology | Version / Specification | Rationale / Constraints |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | FastAPI | `^0.110.0` | Asynchronous, lightweight ASGI framework with native Pydantic schema validation. |
| **ASGI Server** | Uvicorn | `^0.28.0` | Production ASGI web server runner compatible with containerized and cloud platforms. |
| **Email Syntax** | `email-validator` | `^2.1.0` | Authoritative RFC 5322 & RFC 5890 syntax and domain label parsing. |
| **DNS Resolution** | `dnspython` | `^2.6.0` | Granular DNS inspection (MX, A, AAAA), custom timeouts, and explicit exception handling. |
| **Template Engine** | Jinja2 | `^3.1.3` | Native HTML template rendering with automatic context escaping enabled. |
| **Frontend UI** | HTML5, CSS3, Vanilla JS | ECMAScript 2020+ | Single-page UI, zero front-end build step, zero heavy frameworks (No React/Vue). |
| **Testing** | `pytest`, `pytest-asyncio`, `httpx` | Latest stable | Deterministic testing suite with 100% mocked DNS responses and API route coverage. |
| **Version Control** | Git & GitHub | Git 2.x+ | Structured commit history and clear repository organization. |
| **Hosting Platform** | Render | Native Web Service | Deployable via standard `requirements.txt` and Uvicorn process binding to `$PORT`. |

### Architectural Prohibitions
- **No Database:** No SQLite, PostgreSQL, MongoDB, or ORM layers. All operations are in-memory and stateless.
- **No Heavy Client Frameworks:** No React, Angular, Vue, or build tooling (Vite, Webpack).
- **No External Paid APIs:** No ZeroBounce, Hunter.io, NeverBounce, or Abstract API integrations.
- **No Authentication:** No user accounts, sessions, JWTs, or role-based access control.

---

## 3. Functional and Non-Functional Requirements

### 3.1 Functional Requirements

1. **Multiline Input Ingestion:**
   - The user can paste batches of email addresses into a multiline `<textarea>`.
   - The system must accept entries separated by newlines (`\n`), carriage returns (`\r\n`), and/or commas (`,`).
2. **Whitespace and Empty Entry Truncation:**
   - Leading and trailing whitespace surrounding individual addresses must be stripped.
   - Blank or whitespace-only lines/segments must be silently ignored and excluded from batch counting.
   - Zero non-empty email entries (e.g. empty submission or whitespace-only strings) must produce HTTP 400 Bad Request.
3. **Batch Ceiling Enforcement:**
   - The application processes a maximum of **50 non-empty email addresses** per request.
   - If a batch contains more than 50 non-empty addresses, the API must reject the request with HTTP 413 Payload Too Large and an explicit error message.
   - The frontend must also provide client-side pre-validation and live entry counting to alert the user before submission.
4. **1-to-1 Processing and Preservation:**
   - Every submitted non-empty address produces exactly one output result entry.
   - The original input order of addresses must be preserved in the response.
   - Duplicate email addresses within the batch are **not deduplicated**; each instance must be evaluated and represented in the output in its respective position.
   - Syntactic validity is evaluated per-address: a non-empty but syntactically invalid email must receive an individual `Likely to Bounce` classification; it must not cause the entire batch request to be rejected.
5. **Complete Result Tuple:**
   - Every result item must contain exactly:
     - `email`: The sanitized raw email address string submitted.
     - `status`: One of `Likely Delivered`, `Likely to Bounce`, or `Unknown`.
     - `reason`: A definitive, plain-English technical explanation detailing the exact evidence supporting the assigned status.
6. **Accessible Tabular Output:**
   - The frontend must display results in a structured `<table>` with distinct columns: Email Address, Classification Badge, and Explanatory Reason.
   - Clear visual distinctions (e.g., color-coded pill badges) must be applied to each status.
7. **Graceful Error Handling:**
   - All network interruptions, server-side exceptions, and validation failures must surface clear, non-cryptic error banners in the UI.
8. **Strict Zero-Send Policy:**
   - The application must never initiate an SMTP handshake (HELO/EHLO/MAIL FROM/RCPT TO) or dispatch actual email messages over the network.

### 3.2 Non-Functional Requirements

1. **Simplicity and Maintainability:**
   - Minimal codebase adhering to clean code principles and explicit separation of concerns.
   - Domain logic (email syntax parsing and DNS lookup) must remain decoupled from HTTP request parsing and FastAPI route controllers.
2. **Deterministic, Bounded DNS Lookups & Scoped Caching:**
   - The application uses the configured system DNS resolver by default. Do not add automatic fallback to public DNS resolvers.
   - DNS queries executed via `dnspython` must configure strict, bounded timeouts:
     - Per-query timeout: `2.0 seconds`
     - Total query lifetime: `3.0 seconds`
   - Prevents unresponsive nameservers from hanging worker threads or starving ASGI worker connections.
   - DNS-routing cache entries, when implemented in a later phase, must be scoped strictly to the current batch request only and discarded immediately upon request completion.
   - Expected DNS infrastructure failures (such as timeouts, SERVFAIL, or NoNameservers) must be distinguished from unexpected programming errors; infrastructure events yield classification evidence, while unexpected programming bugs return HTTP 500.
3. **Data Privacy and Logging Hygiene:**
   - In accordance with PII protection and GDPR/data privacy standards, user-submitted email addresses **must never be written to application log files**.
   - Server logs must record only aggregate batch metrics (e.g., `Batch received: 14 items`, `Batch completed in 210ms: 0 Delivered, 4 Bounce, 10 Unknown`).
4. **Defensive UI and HTML Injection Prevention:**
   - All user-supplied email strings and server-generated error messages must be sanitized before rendering.
   - Jinja2 auto-escaping must be active for server-rendered contexts.
   - Client-side DOM updates must use safe DOM properties (`textContent` / `element.innerText`) rather than raw `innerHTML` string interpolation.
5. **Deterministic Testability:**
   - 100% of the core classification pipeline and API endpoints must be testable offline without live internet access.
   - All DNS resolution branches (`NXDOMAIN`, `NoAnswer`, timeouts, Null MX, fallback resolution) must be validated using mocked `dnspython` resolver fixtures.
6. **Cloud Portability and Deployment Readiness:**
   - The application must run without modification in standard Python 3.11+ environments.
   - Must be fully deployable as a Render Web Service listening on host `0.0.0.0` and port `$PORT`.

---

## 4. Classification Decision Logic

### 4.1 Categorization Principles

The application implements a strict three-state categorization model:

```
                                  [ Input Email ]
                                         │
                             [ 1. Syntax Validation ]
                                         │
                     ┌───────────────────┴───────────────────┐
                  (Invalid)                               (Valid)
                     │                                       │
            [ Likely to Bounce ]                   [ 2. DNS MX Query ]
                                                             │
                                     ┌───────────────────────┼───────────────────────┐
                                 (NXDOMAIN)              (Null MX)              (MX Present)
                                     │                       │                       │
                            [ Likely to Bounce ]    [ Likely to Bounce ]             │
                                                                                     │
                                   ┌─────────────────────────────────────────────────┤
                               (NoAnswer)                                        (Records)
                                   │                                                 │
                        [ 3. A/AAAA Fallback ]                                       │
                                   │                                                 │
                      ┌────────────┴────────────┐                                    │
                  (No Records)             (Records)                                 │
                      │                         │                                    │
             [ Likely to Bounce ]               └──────────────────┬─────────────────┘
                                                                   │
                                                      ┌────────────┴────────────┐
                                                  (Inconclusive /             (Reliable Mailbox
                                                   Unverified Box)             Proof Exists)
                                                          │                         │
                                                     [ Unknown ]          [ Likely Delivered ]*
                                                                          *(Not produced in MVP)
```

### 4.2 State Definitions

#### A. Likely to Bounce
Assigned **only** when there is definitive, conclusive technical evidence that mail delivery to this address will fail permanently.
- **Triggers:**
  1. **Syntax Failure:** Address violates RFC 5322 or contains illegal characters, invalid octets, unclosed brackets, missing local-part, or invalid domain formatting.
  2. **Non-Existent Domain (NXDOMAIN):** The DNS resolver conclusively confirms the domain name does not exist in the root DNS hierarchy.
  3. **Explicit Null MX (RFC 7505):** The domain explicitly publishes an MX record consisting of a single record with preference `0` and exchange `.` (dot), officially declaring to all MTAs that the domain does not accept email under any circumstances.
  4. **No Mail Routing Destination (RFC 5321 §5.1 Exhaustion):** The domain exists but has no MX records (`NoAnswer`), AND subsequent queries for implicit fallback address records (A and AAAA) also return no usable destination (`NoAnswer` or empty records).

#### B. Unknown
Assigned when the available technical evidence is **inconclusive**, or when the infrastructure is verified but delivery to the specific mailbox cannot be guaranteed.
- **Triggers:**
  1. **Valid Mail Routing Configuration (Unverified Mailbox):** The domain has valid MX records or a valid A/AAAA fallback, but the individual mailbox cannot be checked without sending an email or performing active SMTP probes.
  2. **DNS Query Timeout:** A DNS lookup exceeds the timeout threshold (`dns.exception.Timeout`). A timeout indicates network/nameserver latency or packet drop—**it is not proof that a domain does not exist**.
  3. **Temporary Resolver / Nameserver Failures:** The lookup encounters transient server failures (`SERVFAIL`, `NoNameservers`, refused queries).
  4. **Indeterminate DNS Responses:** CNAME loops, partial network splits, or unhandled non-fatal DNS exceptions.

#### C. Likely Delivered
Retained in the application schema to complete the required 3-category model.
- **MVP Operational Policy:**
  - A valid syntax check, a registered domain name, and active MX records **do not prove** that an individual user's mailbox exists or will accept delivery.
  - Determining deliverability with high confidence requires either:
    - Dispatching a real message and verifying non-bounce (explicitly prohibited).
    - Opening an interactive SMTP connection and executing `RCPT TO` verification (explicitly excluded due to greylisting, anti-spam blacklisting, and unreliability).
  - **Therefore, the hosted MVP will not assign `Likely Delivered` to any address.**
  - Any address with valid syntax and functioning mail routing will be classified as `Unknown` with an honest technical rationale: the domain routes mail, but individual mailbox deliverability cannot be verified without active transmission.

### 4.3 Classification Decision Table

| Rule ID | Syntax Valid? | DNS Query MX Response | DNS Fallback A/AAAA Response | Classification | Explanatory Reason Template |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R-01** | **No** | *Not executed* | *Not executed* | `Likely to Bounce` | `Invalid email address syntax: <syntax error details>` |
| **R-02** | Yes | `NXDOMAIN` | *Not executed* | `Likely to Bounce` | `Domain does not exist in DNS (NXDOMAIN).` |
| **R-03** | Yes | `MX 0 .` (RFC 7505 Null MX) | *Not executed* | `Likely to Bounce` | `Domain publishes an explicit Null MX record (RFC 7505) and rejects all incoming email.` |
| **R-04** | Yes | `NoAnswer` | `NXDOMAIN` or `NoAnswer` (Both A & AAAA) | `Likely to Bounce` | `Domain has no MX records and no usable A/AAAA address fallback (RFC 5321).` |
| **R-05** | Yes | Valid MX Record(s) present | *Not executed* | `Unknown` | `Domain accepts mail via MX (<primary_mx>), but recipient mailbox existence cannot be confirmed without active sending.` |
| **R-06** | Yes | `NoAnswer` | Valid A or AAAA Record(s) present | `Unknown` | `Domain has no MX records, but accepts fallback routing via address records (<ip_address>); mailbox existence cannot be confirmed without active sending.` |
| **R-07** | Yes | `dns.exception.Timeout` | *Not executed* | `Unknown` | `DNS query timed out while resolving mail exchangers. Temporary network or nameserver latency.` |
| **R-08** | Yes | `dns.resolver.NoNameservers` / `ServFail` | *Not executed* | `Unknown` | `Temporary DNS nameserver or resolver failure encountered for domain.` |
| **R-09** | Yes | Any unexpected `DNSException` | *Not executed* | `Unknown` | `Inconclusive DNS query result: <sanitized error message>.` |
| **R-10** | Yes | Verified Mailbox Delivery | N/A | `Likely Delivered` | *Reserved: Unused in MVP. Requires active mailbox probing which is out of scope.* |

---

## 5. DNS Edge Cases and Resolution Specification

DNS resolution must strictly implement RFC 5321 (Simple Mail Transfer Protocol) mail exchange discovery rules. The resolution pipeline must adhere to the following sequence:

```
[ Domain Extracted ]
         │
  [ Query DNS MX ]
         │
         ├──> [ NXDOMAIN ] ───────────────> Bounce (Domain non-existent)
         ├──> [ Timeout / ServFail ] ────> Unknown (Transient failure)
         ├──> [ Null MX: "0 ." ] ────────> Bounce (Explicit email refusal)
         ├──> [ Active MX Records ] ─────> Unknown (Mailbox unverified)
         │
         └──> [ NoAnswer on MX ]
                     │
              [ Query DNS A & AAAA ]
                     │
                     ├──> [ A or AAAA Found ] ──────> Unknown (Usable fallback; mailbox unverified)
                     ├──> [ Timeout / ServFail ] ───> Unknown (Transient failure on fallback)
                     └──> [ NoAnswer / NXDOMAIN ] ──> Bounce (No MX and no usable fallback)
```

### 5.1 Concrete Handling of `dnspython` Exceptions

| dnspython Exception Class | Cause / Network Event | Required Pipeline Action | Assigned Status |
| :--- | :--- | :--- | :--- |
| `dns.resolver.NXDOMAIN` | Non-Existent Domain. | Abort resolution immediately. Confirm domain failure. | `Likely to Bounce` |
| `dns.resolver.NoAnswer` *(on MX query)* | Domain exists, but possesses no `MX` resource records. | Do **not** mark as bounce. Initiate fallback queries for `A` and `AAAA` records (RFC 5321 §5.1). | *Proceed to Fallback* |
| `dns.resolver.NoAnswer` *(on A/AAAA query)* | Domain possesses neither MX nor A/AAAA records. | Both primary and implicit fallback routing have failed. Confirm routing failure. | `Likely to Bounce` |
| `dns.resolver.NoNameservers` | All authoritative nameservers failed to answer or returned `SERVFAIL`. | Treat as transient nameserver failure. Do not claim domain is non-existent. | `Unknown` |
| `dns.exception.Timeout` | Query elapsed total `lifetime` (3.0s) without response. | Treat as network latency or packet loss. Conclude resolution. | `Unknown` |
| `dns.name.EmptyLabel` / `dns.name.LabelTooLong` | Malformed domain label encountered during parsing. | Treat as address syntax/naming invalidity. | `Likely to Bounce` |
| Generic `dns.exception.DNSException` | Network, socket, or inconclusive DNS protocol error. | Safely catch exception, log anonymized diagnostic, return inconclusive result. | `Unknown` |

> [!IMPORTANT]
> **Distinguishing Infrastructure Events from Programming Errors:**
> Expected DNS infrastructure events (such as `NXDOMAIN`, `NoAnswer`, timeouts, `SERVFAIL`, or `NoNameservers`) represent external network observations and are handled deterministically as domain classifications (`Likely to Bounce` or `Unknown`). They must be strictly distinguished from unexpected programming bugs, internal runtime exceptions, or uncaught server errors, which must be caught at the controller boundary and returned as `HTTP 500 Internal Server Error` without crashing the ASGI worker process or leaking internal stack traces.

### 5.2 Explicit RFC 7505 Null MX Detection
When an MX query succeeds, the application must inspect the returned records for the RFC 7505 Null MX specification:
```python
# RFC 7505 Null MX pattern: preference == 0 and exchange in [".", "@", ""]
is_null_mx = any(
    rdata.preference == 0 and rdata.exchange.to_text().strip(".") == ""
    for rdata in mx_answers
)
```
If `is_null_mx` is `True`, the address must immediately be classified as `Likely to Bounce`.

---

## 6. API Request and Response Contract

### 6.1 Endpoints Overview

| Method | Path | Content-Type | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | `text/html` | Renders the primary single-page application interface. |
| `POST` | `/api/check` | `application/json` | Ingests a batch of email addresses and returns classification results. |
| `GET` | `/healthz` | `application/json` | Operational liveness probe for hosting environments (Render). |

---

### 6.2 `POST /api/check` Specification

#### Request Headers
```http
POST /api/check HTTP/1.1
Host: shieldnex-email-checker.onrender.com
Content-Type: application/json
Accept: application/json
```

#### Request Body Schema
```json
{
  "emails": [
    "string"
  ]
}
```

#### Request Validation Rules
1. `emails` field is mandatory and must be a JSON array of strings.
2. The batch must contain between **1 and 50 non-empty email addresses** after whitespace trimming.
3. Submissions containing zero non-empty email entries (e.g., `emails` is missing, empty `[]`, or contains exclusively empty/whitespace strings `["", "   "]`) must produce `400 Bad Request`.
4. If the count of non-empty email strings exceeds 50, the server must reject the batch with `413 Payload Too Large`.
5. Syntactic validity is strictly evaluated per address: a non-empty but syntactically invalid email must be processed and assigned an individual `Likely to Bounce` classification; it must not cause the entire batch request to be rejected with 400 or 422.

---

### 6.3 Response Schemas

#### Success Response: `200 OK`
Returned when the batch is valid and all addresses have been evaluated.

```json
{
  "total": 3,
  "results": [
    {
      "email": "flight-ops@shieldnex.com",
      "status": "Unknown",
      "reason": "Domain accepts mail via MX (mail.shieldnex.com), but recipient mailbox existence cannot be confirmed without active sending."
    },
    {
      "email": "invalid-syntax-user@",
      "status": "Likely to Bounce",
      "reason": "Invalid email address syntax: An email address must have a domain part."
    },
    {
      "email": "contact@nonexistent-aerospace-corp-12345.org",
      "status": "Likely to Bounce",
      "reason": "Domain does not exist in DNS (NXDOMAIN)."
    }
  ]
}
```

#### Client Error: `400 Bad Request` (Zero Non-Empty Entries)
```json
{
  "error": "BAD_REQUEST",
  "detail": "Batch contains no valid email addresses. Please submit at least one non-empty email address."
}
```

#### Client Error: `413 Payload Too Large` (Batch Limit Exceeded)
```json
{
  "error": "BATCH_LIMIT_EXCEEDED",
  "detail": "Batch limit exceeded: Received 62 addresses. A maximum of 50 non-empty email addresses is permitted per request."
}
```

#### Client Error: `422 Unprocessable Entity` (Malformed JSON / Schema Mismatch)
```json
{
  "detail": [
    {
      "loc": ["body", "emails"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

#### Server Error: `500 Internal Server Error`
```json
{
  "error": "INTERNAL_SERVER_ERROR",
  "detail": "An unexpected server error occurred while processing the verification batch."
}
```

---

## 7. Explicit Exclusions and Deployment Limitations

### 7.1 Explicit Exclusions
To maintain strict compliance with project constraints, anti-spam hygiene, and ethical engineering standards, the following mechanisms are **expressly prohibited**:

1. **No SMTP Mailbox Probing:** The application will not connect to port 25 of remote mail exchangers or issue `HELO`/`MAIL FROM`/`RCPT TO` commands. Most modern enterprise mail systems (including aerospace corporate domains) interpret unauthenticated SMTP probes as dictionary attacks, leading to IP blacklisting, greylisting delays, and false positives.
2. **No Actual Email Transmission:** No test messages, verification tokens, or bounce probes will ever be sent.
3. **No Paid or Third-Party Verification APIs:** All validations must run locally using open-source packages and standard DNS resolution.
4. **No Disposable / Temporary Email Blacklists:** No external blacklists (e.g., BurnerMail, GuerrillaMail domains) will be bundled, as they add maintenance overhead and fall outside pure mail-routing verification.
5. **No Persistent Data Storage or Global Caching:** No database or persistent disk caching. Submitted emails are processed entirely in volatile memory and discarded once the HTTP response is completed. Any DNS-routing cache entries implemented in subsequent phases must be scoped strictly to the lifecycle of the single batch request.
6. **No Authentication or User Accounts:** The interface is an open, unauthenticated utility for internship evaluation.

### 7.2 Deployment Limitations
- **Render Free-Tier Cold Starts:** On Render's free tier, the web service will spin down after inactivity. Initial requests may experience a 30–50 second cold-start latency.
- **System DNS Resolver Dependency:** The application relies on the hosting environment's configured system DNS resolver by default. Automatic fallback to external public DNS resolvers is intentionally omitted.
- **Rate Limiting:** While this phase does not require an API gateway rate limiter, the 50-item batch ceiling guarantees bounded CPU and network utilization per connection.

---

## 8. Testable Acceptance Criteria

The following acceptance criteria define the definition of done for subsequent implementation phases:

### Category 1: Email Syntax Validation
- **AC-1.1:** Given a valid email address (e.g. `test@example.com`), syntax validation passes and advances to DNS checks.
- **AC-1.2:** Given an address missing the `@` symbol (e.g. `testexample.com`), the application assigns `Likely to Bounce` and cites syntax failure without performing DNS queries.
- **AC-1.3:** Given an address with invalid domain characters (e.g. `user@exa mple.com`), the application assigns `Likely to Bounce`.
- **AC-1.4:** Given an address with an empty local-part (e.g. `@example.com`), the application assigns `Likely to Bounce`.

### Category 2: DNS Mail-Routing & Edge Cases
- **AC-2.1 (NXDOMAIN):** Given a domain that does not exist in DNS, the application assigns `Likely to Bounce` with reason citing `NXDOMAIN`.
- **AC-2.2 (Null MX):** Given a domain publishing `MX 0 .`, the application assigns `Likely to Bounce` citing RFC 7505 Null MX.
- **AC-2.3 (Valid MX):** Given a domain publishing valid MX records, the application assigns `Unknown` citing that the domain receives mail but mailbox deliverability cannot be verified.
- **AC-2.4 (No MX with A/AAAA Fallback):** Given a domain with no MX records (`NoAnswer`) but valid A/AAAA records, the application assigns `Unknown` citing RFC 5321 address fallback.
- **AC-2.5 (No MX and No A/AAAA Fallback):** Given a domain with no MX records and no A/AAAA records, the application assigns `Likely to Bounce` citing lack of usable mail routing.
- **AC-2.6 (DNS Timeout):** Given a simulated DNS query timeout, the application assigns `Unknown` citing network/DNS timeout rather than claiming domain failure.
- **AC-2.7 (Nameserver Failure):** Given a simulated `SERVFAIL` or `NoNameservers`, the application assigns `Unknown` citing transient DNS failure.

### Category 3: Batch Ingestion & Ordering
- **AC-3.1:** Given a batch of comma-separated and newline-separated emails, all non-empty items are correctly parsed and returned in original sequence.
- **AC-3.2:** Given duplicate emails in a batch, each instance is evaluated and returned in the results list at its exact original position.
- **AC-3.3:** Given an empty submission or whitespace-only input, the API returns HTTP 400 with a descriptive error message.
- **AC-3.4:** Given a batch containing 51 non-empty addresses, the API returns HTTP 413 Payload Too Large indicating that the 50-address ceiling has been exceeded.
- **AC-3.5:** Given a batch containing 50 non-empty addresses, the API successfully processes all 50 items and returns HTTP 200.

### Category 4: Security, Privacy, and UI
- **AC-4.1:** Given email addresses containing HTML tags (e.g. `<script>alert('xss')</script>@test.com`), the frontend renders the text safely without script execution.
- **AC-4.2:** Given any request to `/api/check`, application logs contain no plaintext email addresses.
- **AC-4.3:** The frontend interface provides a clean, responsive layout with an intuitive text area, live address counter, submit button with loading spinner, and structured result table with distinct color badges.
