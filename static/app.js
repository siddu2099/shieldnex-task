/**
 * EmailCheck — Frontend Application Script
 *
 * Handles:
 * 1. Input parsing (splitting on newlines/commas, trimming, blank removal).
 * 2. Client-side boundary pre-validation (1 to 50 non-empty addresses).
 * 3. Asynchronous batch submission to POST /api/check.
 * 4. Safe DOM rendering using textContent to prevent HTML injection.
 * 5. Robust error state management (network failures, 400, 413, 422, 500).
 */

document.addEventListener("DOMContentLoaded", () => {
    // -------------------------------------------------------------------------
    // DOM Element References
    // -------------------------------------------------------------------------
    const checkForm = document.getElementById("check-form");
    const emailsInput = document.getElementById("emails");
    const checkBtn = document.getElementById("check-btn");
    const loadingIndicator = document.getElementById("loading");
    const errorMessage = document.getElementById("error-message");

    const summaryPanel = document.getElementById("summary");
    const summaryTotal = document.getElementById("summary-total");
    const summaryDelivered = document.getElementById("summary-delivered");
    const summaryBounce = document.getElementById("summary-bounce");
    const summaryUnknown = document.getElementById("summary-unknown");

    const initialState = document.getElementById("initial-state");
    const emptyResultsState = document.getElementById("empty-results-state");
    const resultsContainer = document.getElementById("results-container");
    const resultsBody = document.getElementById("results-body");

    // Guard flag to prevent concurrent or duplicate submissions
    let isSubmitting = false;

    // Strict status-to-CSS-class mapping (prevents arbitrary class injection)
    const STATUS_MAP = Object.freeze({
        "Likely Delivered": "badge-delivered",
        "Likely to Bounce": "badge-bounce",
        "Unknown": "badge-unknown",
    });

    // -------------------------------------------------------------------------
    // Helper Functions
    // -------------------------------------------------------------------------

    /**
     * Parses raw textarea input into an array of non-empty email addresses.
     * Splits on newlines and commas, strips whitespace, and removes empty entries.
     * Preserves exact input ordering and duplicates.
     *
     * @param {string} rawText
     * @returns {string[]}
     */
    function parseAddresses(rawText) {
        if (typeof rawText !== "string") {
            return [];
        }
        return rawText
            .split(/[\r\n,]+/)
            .map((item) => item.trim())
            .filter((item) => item.length > 0);
    }

    /**
     * Clears all dynamic rows from the results table body.
     */
    function clearResultsTable() {
        while (resultsBody.firstChild) {
            resultsBody.removeChild(resultsBody.firstChild);
        }
    }

    /**
     * Resets results table, summary panel, and restores initial state.
     * Ensures previous results are not misleadingly presented on failed requests.
     */
    function hideResults() {
        clearResultsTable();
        resultsContainer.hidden = true;
        summaryPanel.hidden = true;
        emptyResultsState.hidden = true;
        initialState.hidden = false;
    }

    /**
     * Displays a user-facing error message in the designated accessible alert area.
     * Uses textContent to prevent HTML injection.
     * Clears and hides previous results to prevent misleading association with failed requests.
     *
     * @param {string} message
     */
    function showError(message) {
        hideResults();
        errorMessage.textContent = message;
        errorMessage.hidden = false;
    }

    /**
     * Hides the error message alert area.
     */
    function hideError() {
        errorMessage.textContent = "";
        errorMessage.hidden = true;
    }

    /**
     * Sets the UI loading state during asynchronous API requests.
     *
     * @param {boolean} loading
     */
    function setLoading(loading) {
        isSubmitting = loading;
        checkBtn.disabled = loading;
        loadingIndicator.hidden = !loading;
    }

    // -------------------------------------------------------------------------
    // Main Form Submit Handler
    // -------------------------------------------------------------------------

    checkForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        if (isSubmitting) {
            return;
        }

        hideError();

        // Step 1: Parse input addresses
        const rawValue = emailsInput.value;
        const addresses = parseAddresses(rawValue);

        // Client-side batch boundary checks
        if (addresses.length === 0) {
            showError("No non-empty email addresses were provided. Please enter at least one email address.");
            return;
        }

        if (addresses.length > 50) {
            showError(
                `Batch limit exceeded: Received ${addresses.length} addresses. A maximum of 50 non-empty email addresses is permitted per request.`
            );
            return;
        }

        // Step 2 & 3: Submit API request with active loading state
        setLoading(true);

        try {
            const response = await fetch("/api/check", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body: JSON.stringify({ emails: addresses }),
            });

            // Step 4 & 5: Handle responses and errors
            if (!response.ok) {
                let errorDetail = "";
                try {
                    const errPayload = await response.json();
                    if (typeof errPayload.detail === "string") {
                        errorDetail = errPayload.detail;
                    } else if (Array.isArray(errPayload.detail)) {
                        errorDetail = errPayload.detail
                            .map((d) => d.msg || "Invalid parameter")
                            .join("; ");
                    } else if (typeof errPayload.error === "string") {
                        errorDetail = errPayload.error;
                    }
                } catch {
                    // Response body was not JSON
                }

                if (response.status === 400) {
                    showError(errorDetail || "No non-empty email addresses were provided.");
                } else if (response.status === 413) {
                    showError(
                        errorDetail ||
                        "Batch limit exceeded: A maximum of 50 non-empty email addresses is permitted per request."
                    );
                } else if (response.status === 422) {
                    showError(errorDetail ? `Validation error: ${errorDetail}` : "Invalid request payload format.");
                } else if (response.status === 500) {
                    showError(
                        errorDetail ||
                        "An unexpected server error occurred while processing the verification batch."
                    );
                } else {
                    showError(errorDetail || `Request failed with HTTP status ${response.status}.`);
                }
                return;
            }

            // Successful 200 response
            const data = await response.json();
            const results = Array.isArray(data.results) ? data.results : [];

            // Reset previous displays
            clearResultsTable();
            initialState.hidden = true;

            if (results.length === 0) {
                emptyResultsState.hidden = false;
                resultsContainer.hidden = true;
                summaryPanel.hidden = true;
                return;
            }

            emptyResultsState.hidden = true;
            resultsContainer.hidden = false;
            summaryPanel.hidden = false;

            // Summary counters
            let deliveredCount = 0;
            let bounceCount = 0;
            let unknownCount = 0;

            // Render table rows safely using DOM APIs (no innerHTML)
            for (const item of results) {
                const row = document.createElement("tr");

                // 1. Email cell
                const tdEmail = document.createElement("td");
                tdEmail.className = "cell-email";
                tdEmail.textContent = item.email != null ? String(item.email) : "";
                row.appendChild(tdEmail);

                // 2. Status badge cell
                const tdStatus = document.createElement("td");
                const badge = document.createElement("span");
                const statusText = item.status != null ? String(item.status) : "";
                const badgeClass = STATUS_MAP[statusText] || "badge-unknown";
                badge.className = `status-badge ${badgeClass}`;
                badge.textContent = statusText;
                tdStatus.appendChild(badge);
                row.appendChild(tdStatus);

                // 3. Reason cell
                const tdReason = document.createElement("td");
                tdReason.className = "cell-reason";
                tdReason.textContent = item.reason != null ? String(item.reason) : "";
                row.appendChild(tdReason);

                resultsBody.appendChild(row);

                // Increment summary counters
                if (statusText === "Likely Delivered") {
                    deliveredCount += 1;
                } else if (statusText === "Likely to Bounce") {
                    bounceCount += 1;
                } else if (statusText === "Unknown") {
                    unknownCount += 1;
                }
            }

            // Populate summary metrics from response
            const totalCount = typeof data.total === "number" ? data.total : results.length;
            summaryTotal.textContent = String(totalCount);
            summaryDelivered.textContent = String(deliveredCount);
            summaryBounce.textContent = String(bounceCount);
            summaryUnknown.textContent = String(unknownCount);

        } catch (err) {
            // Handle network interruption, aborted connection, or DNS resolution failure
            showError("Network error: Unable to reach the server. Please check your network connection and try again.");
        } finally {
            setLoading(false);
        }
    });
});
