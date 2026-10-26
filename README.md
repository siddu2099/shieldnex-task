# EmailCheck — ShieldNex Aerospace Email Checker

**EmailCheck** is a lightweight, reliable batch email validation and diagnostic web application developed for the **ShieldNex Aerospace Software Development Internship** selection task.

The application triages batches of email addresses into three operational deliverability categories:
1. `Likely Delivered`
2. `Likely to Bounce`
3. `Unknown`

Verification is strictly non-intrusive: it validates syntax compliance according to RFC specifications and performs DNS mail-routing inspection without dispatching actual emails or executing invasive SMTP mailbox probing.

Repository URL: [https://github.com/siddu2099/shieldnex-task.git](https://github.com/siddu2099/shieldnex-task.git)

---

## Features

- **Batch Ingestion:** Validate batches of up to 50 non-empty email addresses in a single request.
- **Flexible Delimiters:** Supports input separated by newlines (`\n`, `\r\n`) and commas (`,`).
- **RFC Syntax Validation:** Strict parsing of local-part and domain labels via `email-validator` (RFC 5322 & RFC 5890).
- **DNS Mail-Routing Discovery:** Granular DNS inspection via `dnspython` covering:
  - Primary mail exchangers (MX records).
  - RFC 7505 explicit Null MX detection (`0 .`).
  - RFC 5321 §5.1 implicit address fallback (A and AAAA records) when MX records are absent.
- **Informative Technical Rationales:** Every evaluated address returns a plain-English explanation detailing the technical evidence supporting its classification.
- **Request-Scoped DNS Cache:** In-memory caching scoped strictly to the lifecycle of an individual batch request to optimize lookups for shared domains without global state or cross-request persistence.
- **Input Boundary Enforcement:** Strict enforcement of batch limits (1 to 50 non-empty addresses) with HTTP 400 for empty submissions and HTTP 413 for batches exceeding 50 items.
- **Order and Duplicate Preservation:** Exact input order and duplicates are preserved in the response.
- **Per-Address Fault Tolerance:** Syntactically invalid addresses are classified individually as `Likely to Bounce` without rejecting the batch.
- **Responsive, Accessible Interface:** Clean single-page UI built with semantic HTML5, accessible contrast (WCAG AA/AAA), keyboard focus states, color-coded badges, live loading indicator, and summary statistics.
- **Zero-Send Security & Privacy:** No emails are transmitted, no SMTP connections are initiated, and user email addresses are never written to server log files.

---

## Technology Stack

Python package dependencies are currently unpinned and declared in `requirements.txt`.

| Layer | Technology | Version Policy | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | FastAPI | Unpinned (`requirements.txt`) | Asynchronous ASGI framework with native Pydantic schema validation. |
| **ASGI Server** | Uvicorn | Unpinned (`requirements.txt`) | Production ASGI web server runner. |
| **Syntax Validation** | `email-validator` | Unpinned (`requirements.txt`) | Authoritative RFC 5322 & RFC 5890 syntax and domain label parsing. |
| **DNS Resolution** | `dnspython` | Unpinned (`requirements.txt`) | DNS inspection (MX, A, AAAA) with bounded per-query and total timeouts. |
| **Template Engine** | Jinja2 | Unpinned (`requirements.txt`) | Server-rendered HTML templating with auto-escaping. |
| **Frontend UI** | HTML5, CSS3, Vanilla JS | Native / Vanilla | Single-page UI, zero front-end build step, zero third-party frameworks. |
| **Testing** | `pytest`, `httpx` | Unpinned (`requirements.txt`) | Deterministic testing suite with 100% mocked DNS responses. |

*Architectural Constraints: No external databases, no third-party paid validation APIs, no heavy frontend frameworks (React/Vue), and no persistent cross-request caches.*

---

## Classification Rules

The application assigns each address to one of three operational states based on concrete technical evidence:

| Status | Operational Definition | Technical Triggers & Evidence |
| :--- | :--- | :--- |
| **`Likely to Bounce`** | Conclusive evidence that delivery will permanently fail. | • **Syntax Failure:** Violates RFC 5322 (missing `@`, invalid characters, unclosed quotes).<br>• **NXDOMAIN:** DNS resolver confirms domain does not exist in root hierarchy.<br>• **RFC 7505 Null MX:** Domain explicitly publishes `MX 0 .` to declare email refusal.<br>• **Routing Exhaustion:** Domain publishes no MX records (`NoAnswer`), and fallback queries for both A and AAAA records return no usable addresses (`NoAnswer` or `NXDOMAIN`). |
| **`Unknown`** | Inconclusive evidence, transient network failure, or unverified recipient mailbox. | • **Functional Mail Routing:** Domain has active MX records or valid A/AAAA fallback, but individual recipient mailbox existence cannot be confirmed without active sending.<br>• **DNS Timeout:** Query exceeds timeout limits (`dns.exception.Timeout`). Latency is not proof of nonexistence.<br>• **Nameserver Glitch:** Authoritative nameservers return `SERVFAIL` or `NoNameservers`.<br>• **Malformed MX:** Ambiguous record configurations (e.g., mixing Null MX with standard MX). |
| **`Likely Delivered`** | Reserved in application schema. *(Not produced in current MVP)* | High-confidence deliverability proof requires either dispatching a live email or executing interactive SMTP `RCPT TO` commands. Because SMTP probing triggers greylisting and anti-spam blacklisting, active transmission is strictly prohibited. Valid syntax and working mail routing do not prove an individual mailbox exists. Consequently, the MVP assigns `Unknown` with an honest technical explanation rather than claiming unverified deliverability. |

### DNS Resolution Limits & Edge Cases

- **Bounded Timeouts:** Configured via `dnspython`:
  - Per-query timeout: `2.0 seconds`
  - Total routing deadline per domain: `3.0 seconds`
- **RFC 5321 §5.1 Implicit Fallback:** If an MX query returns `NoAnswer`, the resolver queries A and AAAA address records. If either exists, mail can be routed to the implicit MX host.
- **Transient Failures vs Nonexistence:** `NXDOMAIN` confirms nonexistence (`Likely to Bounce`). `NoNameservers`, `SERVFAIL`, or timeouts represent external network events and yield `Unknown`.
- **Unexpected Programming Errors:** Programming bugs propagate to controller exception handlers and return `HTTP 500` rather than falsely classifying addresses as `Unknown`.

---

## Architecture

The codebase enforces strict separation of concerns across domain logic, HTTP routing, and client presentation:

```
ShieldNex Aerospace — Email Checker/
├── app.py                  # FastAPI application entrypoint, routes, schemas, and error handlers
├── checker.py              # Decoupled classification engine (RFC syntax, DNS lookups, caching)
├── requirements.txt        # Unpinned Python package dependencies
├── REQUIREMENTS.md         # Authoritative technical specification
├── README.md               # Project documentation
├── static/
│   ├── style.css           # Self-contained, accessible CSS stylesheet (WCAG AA/AAA)
│   └── app.js              # Vanilla JavaScript for input parsing, fetch requests, and safe DOM rendering
├── templates/
│   └── index.html          # Semantic HTML5 single-page interface (EmailCheck)
└── tests/
    ├── test_checker.py     # Unit test suite for checker.py (syntax, DNS, timeouts, cache)
    └── test_api.py         # Integration test suite for app.py (endpoints, limits, privacy, 500 safety)
```

- **`checker.py`**: Pure domain module. Exposes `classify_email(email, routing_cache=None, resolver=None)`. Contains no web framework code or HTTP dependencies.
- **`app.py`**: Manages the HTTP interface, mounts static assets, validates incoming payloads via Pydantic (`CheckRequest`), instantiates the per-request `routing_cache`, and returns standardized JSON responses (`CheckResponse`, `ErrorResponse`).
- **`templates/index.html` & `static/`**: Client interface providing accessible form controls, real-time validation, responsive tables, and injection-safe rendering.
- **`tests/`**: Comprehensive automated test suite ensuring regression safety and protocol compliance.

---

## Prerequisites and Local Setup

### Prerequisites
- Python 3.11 or higher
- Git 2.x

### 1. Clone the Repository
```bash
git clone https://github.com/siddu2099/shieldnex-task.git
cd shieldnex-task
```

### 2. Create and Activate a Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
Launch the local Uvicorn development server:
```bash
uvicorn app:app --reload
```

Open your browser and navigate to:
- **Application Interface:** `http://127.0.0.1:8000/`
- **Interactive Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc API Documentation:** `http://127.0.0.1:8000/redoc`

---

## Automated Testing

Run the full automated test suite using `pytest`:

```bash
pytest -q
```

### Test Isolation and Offline Execution
- **100% Mocked DNS:** All DNS lookups in the test suite are mocked using genuine `dnspython` data structures parsed via `dns.message.from_text`.
- **Zero External Dependencies:** Tests do not connect to public DNS resolvers, guaranteeing deterministic, fast execution (70 tests complete in ~1.0 second).
- **Controllable Monotonic Clock:** Timeout and deadline tests utilize patched monotonic clock ticks rather than real sleeps.

---

## API Usage

### 1. Web Interface
- **Route:** `GET /`
- **Response:** `text/html` (Single-page application)

### 2. Batch Email Check
- **Route:** `POST /api/check`
- **Headers:** `Content-Type: application/json`, `Accept: application/json`

#### Request Payload
```json
{
  "emails": [
    "pilot@shieldnex.com",
    "invalid-syntax-user@",
    "contact@nonexistent-domain-12345.org"
  ]
}
```

#### Success Response (`200 OK`)
```json
{
  "total": 3,
  "results": [
    {
      "email": "pilot@shieldnex.com",
      "status": "Unknown",
      "reason": "Domain accepts mail via active MX records (mail.shieldnex.com), but recipient mailbox existence cannot be confirmed without active sending."
    },
    {
      "email": "invalid-syntax-user@",
      "status": "Likely to Bounce",
      "reason": "Invalid email address syntax: There must be something after the @-sign."
    },
    {
      "email": "contact@nonexistent-domain-12345.org",
      "status": "Likely to Bounce",
      "reason": "Domain does not exist according to DNS (NXDOMAIN)."
    }
  ]
}
```

#### Client Error Responses
- **`400 Bad Request`** (Zero non-empty addresses submitted):
  ```json
  {
    "error": "BAD_REQUEST",
    "detail": "No non-empty email addresses were provided."
  }
  ```
- **`413 Content Too Large`** (Exceeds 50 non-empty addresses):
  ```json
  {
    "error": "BATCH_LIMIT_EXCEEDED",
    "detail": "Batch limit exceeded: Received 52 addresses. A maximum of 50 non-empty email addresses is permitted per request."
  }
  ```
- **`422 Unprocessable Entity`** (Schema mismatch, missing `emails` field, or non-string elements):
  ```json
  {
    "detail": [
      {
        "loc": ["body", "emails"],
        "msg": "Field required",
        "type": "missing"
      }
    ]
  }
  ```

#### Server Error Response
- **`500 Internal Server Error`** (Unexpected runtime errors):
  ```json
  {
    "error": "INTERNAL_SERVER_ERROR",
    "detail": "An unexpected server error occurred while processing the verification batch."
  }
  ```
  *The response contains no stack traces, file paths, or user email strings.*

---

## Limitations

1. **No Individual Mailbox Verification:** Domain-level DNS inspection confirms whether a domain accepts email and where to route it; it does **not** prove that an individual recipient mailbox exists.
2. **Zero-Send Policy:** To uphold ethical email hygiene and avoid spam filtering/blacklisting, the application performs no SMTP handshakes (`RCPT TO`) and sends no probe messages.
3. **System Resolver Dependency:** The application relies on the host environment's system DNS resolver by default.
4. **Batch Limit:** Batches are strictly limited to 50 non-empty email addresses per request to ensure predictable CPU and network utilization.

---

## Deployment

Public cloud deployment is scheduled as a subsequent phase. The application is container-ready and prepared for deployment to hosting platforms such as Render as a native Web Service binding to `0.0.0.0` and `$PORT`.

---

## License

This project was developed for the ShieldNex Aerospace Software Development Internship evaluation task.
