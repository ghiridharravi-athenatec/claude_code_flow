# SPEC.md — Medical Record Validator (Clinical Documentation Integrity Scorer)
This is a binding implementation contract. Every decision below is final for v1 unless SCOPE.md is revisited. Where SCOPE.md left a default, this document inherits it without re-litigating it.

---

## 1. Extraction Pipeline

### 1.1 File type detection
- Detected by **file extension + MIME sniffing** (not extension alone) using `python-magic`. If the sniffed MIME type doesn't match one of the three allowed types, reject before any parsing is attempted.
- Allowed: `application/pdf` (.pdf), `text/plain` (.txt), `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (.docx).
- Max file size: **10 MB**. Reject larger files with a 413 before reading the full file into memory (check `Content-Length` header first, then re-validate actual size after read).

### 1.2 Per-type extraction
| Type | Library | Method |
|---|---|---|
| PDF | `pypdf` (`PdfReader`) | Concatenate `page.extract_text()` for every page, joined with `\n\n`. |
| DOCX | `python-docx` | Concatenate `paragraph.text` for every paragraph in `document.paragraphs`, plus cell text from every table in `document.tables` (row-major, tab-joined per row), joined with `\n`. |
| TXT | built-in | Read as UTF-8. If decoding fails, retry with `latin-1`. If that also fails, treat as extraction failure. |

- **Decision:** No OCR fallback. If PDF text extraction yields fewer than **20 non-whitespace characters** total, the record is treated as **extraction failure** (see 1.4), on the assumption it's a scanned/image-only PDF.
- **Decision:** No layout/structure preservation beyond paragraph and table boundaries. Headers, footers, and page numbers are extracted as plain text along with body content — no attempt to strip them.

### 1.3 PHI identification and handling
- **Library:** Microsoft Presidio (`presidio-analyzer` + `presidio-anonymizer`), with spaCy's `en_core_web_lg` as the NLP engine — consistent with existing Presidio usage.
- **Entities detected:** Presidio's default set (`PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `DATE_TIME`, `LOCATION`, `MEDICAL_LICENSE`, `US_SSN`) plus two custom recognizers: `AADHAAR` and `PAN` (regex-based, matching the pattern used in the RAG chatbot's `hybrid_pii_detector.py`), since records are expected to originate in an Indian context.
- **Decision — where PHI handling applies:**
  - The **full extracted text is used, unredacted, for rubric matching** (validation needs actual content — dates, provider names, etc. may themselves be required rubric fields). PHI redaction is NOT applied before matching.
  - **Updated:** "rubric matching" as of Section 2.2/Section 6 means a Claude API call — the full unredacted extracted text is transmitted to Anthropic's API as part of that call. This is the same "no redaction before matching" decision as above, now extended to an external API rather than only in-process code; see SCOPE.md's PHI Handling section for the explicit, accepted-tradeoff framing of this.
  - PHI redaction (via Presidio Anonymizer, `replace` operator — e.g. `<PERSON>`, `<PHONE_NUMBER>`) is applied to:
    - Any text written to application logs (info/warning/error level).
    - Any text included in exception tracebacks that get logged.
    - Any text returned in an error response body to the client (e.g., a snippet showing what caused a parse failure).
  - The raw extracted text and the original uploaded file exist only in memory for the duration of the request and are **never written to disk** or any persistent store (consistent with SCOPE.md's no-database, no-persistence decision).
- **Decision:** No PHI redaction in the validation result JSON returned to the browser, because the user is the uploader and is treated as authorized to see their own submitted content (per SCOPE.md ambiguity #6). Rubric "matched text" snippets in the response (see Section 3) are shown unredacted.

### 1.4 Extraction failure handling
- Extraction failure is a terminal state for the request — no partial validation is attempted.
- Failure conditions: unreadable/corrupted file, password-protected PDF/DOCX, zero or near-zero extracted text (< 20 non-whitespace chars), decode failure on TXT.
- On failure, return **HTTP 422** with a structured error body (see Section 4.5). The specific failure reason is included, but any text excerpt in the error (if any) is PHI-redacted first.

---

## 2. Rubric Matching Logic

### 2.1 Rubric file structure
`med_record_rubrics.json` — a single JSON object describing **one** weighted, narrative-scored rubric (not a dict keyed by rubric ID, and not keyword/regex criteria):

```json
{
  "title": "Medical Record Narrative - Clinical Documentation Integrity Evaluation Rubric",
  "version": "1.0",
  "framework": "AHIMA/ACDIS high-quality documentation criteria, PDQI-9 note-quality domains, CMS 42 CFR 482.24, ICD-10-CM Official Guidelines",
  "scale": {
    "min": 1,
    "max": 5,
    "meaning": "5 = documentation integrity fully met / lowest compliance and denial risk, 1 = fails the standard / highest risk. Use N/E when the record provides no evidence either way; N/E scores 0 points."
  },
  "rubrics": [
    {
      "id": "R1",
      "name": "Authentication and Legal Integrity",
      "weight": 8,
      "question": "Is this a legally valid, attributable record?",
      "reference": "42 CFR 482.24(c)(1); Joint Commission RC.01.01.01",
      "levels": {
        "5": "Every entry authenticated with author name, credentials, date and time. Verbal and telephone orders co-signed within policy. Amendments, corrections and late entries explicitly labelled, with the original content preserved and a reason stated. No unattributed sections.",
        "4": "Fully authenticated with one minor lapse - a verbal order co-signed outside the policy window, or a late entry labelled but without a stated reason.",
        "3": "Authentication present but inconsistent - one or more entries missing time, credentials or co-signature; or an amendment made without the original preserved.",
        "2": "Material authentication gaps - a substantive clinical entry unsigned, or an addendum that changes clinical meaning without label, date or attribution.",
        "1": "The record, or the section carrying the principal diagnosis or a procedure, is unauthenticated or unattributable; or content was altered with no audit trail."
      },
      "hard_rule": "A score of 1 on Authentication triggers DEFICIENT regardless of the weighted total."
    }
  ],
  "scoring_method": {
    "formula": "points = (score / 5) * weight",
    "total": "Sum of all ten rubrics. Maximum 100.",
    "worked_example": "Diagnostic Specificity scored 4 of 5, weight 14 -> (4/5) * 14 = 11.2 points."
  },
  "decision_bands": [
    { "min": 88, "max": 100, "decision": "DOCUMENTATION ACCEPTED", "note": "Meets documentation integrity standards. Release for coding and billing." },
    { "min": 74, "max": 87, "decision": "ACCEPTED WITH QUERY", "note": "Codable, but one or more elements require a compliant provider query before final code assignment." },
    { "min": 58, "max": 73, "decision": "RETURN FOR CLARIFICATION", "note": "Material gaps. Return to the author for amendment; do not finalise coding." },
    { "min": 0, "max": 57, "decision": "DEFICIENT", "note": "Does not meet minimum documentation standards. Escalate to CDI leadership and compliance." }
  ],
  "severity_order": ["DOCUMENTATION ACCEPTED", "ACCEPTED WITH QUERY", "RETURN FOR CLARIFICATION", "DEFICIENT"],
  "hard_rules": [
    {
      "id": "HR-1",
      "rubric_id": "R1",
      "trigger": "R1 (Authentication and Legal Integrity) score equals 1",
      "action": "DEFICIENT",
      "reason": "The record is unauthenticated. An entry that cannot be attributed to an author is not a legal record and cannot support a claim, however strong the clinical content is."
    },
    {
      "id": "HR-2",
      "rubric_id": "R5",
      "trigger": "R5 (Diagnostic Specificity and Coding Support) score equals 1",
      "action": "RETURN FOR CLARIFICATION",
      "reason": "No principal diagnosis can be assigned from the narrative as written. Specificity elsewhere in the record does not substitute for a codable principal diagnosis."
    }
  ]
}
```

Field reference:
- `rubrics[]` — ten fixed dimensions (`R1`–`R10`), each with `id`, `name`, `weight` (integer points this dimension contributes out of a 100-point total), `question` (framing prompt), `reference` (citation), and `levels` — an object keyed `"1"`–`"5"` (string keys), each value a paragraph describing what that score level looks like in the narrative. There is **no** `patterns`, `match_type`, or `case_sensitive` field anywhere in the file — a rubric dimension is not resolved by substring/regex matching, it is scored on a 1–5 narrative-judgment scale. A `hard_rule` (string, optional, informational) may accompany a rubric; the authoritative, machine-actionable version of any such override lives in the top-level `hard_rules[]` array, not in this field. One dimension (`R5`, Diagnostic Specificity and Coding Support) also carries an optional `primary_metric` field (string, informational) describing the specific measure that dimension's levels track; it is not present on the other nine dimensions and is not used by the LLM judge or the scorer — display-only, same treatment as `hard_rule`.
- `scale` — the 1–5 scoring range shared by every rubric, plus an `"N/E"` ("no evidence") value usable in place of a numeric score wherever a score is recorded; `N/E` contributes 0 points.
- `scoring_method` — `points = (score / 5) * weight` per rubric dimension; the total is the sum across all ten dimensions, maximum 100.
- `decision_bands[]` — ordered `min`/`max` integer ranges over the 0–100 total score, each mapped to a `decision` string and an explanatory `note`.
- `severity_order[]` — the four `decision` values ordered best-to-worst outcome.
- `hard_rules[]` — overrides keyed by `rubric_id` (`trigger`, `action`, `reason`) that force a specific `decision` outright when a named rubric dimension scores a specific value, independent of the weighted total.
- **Note (resolved):** the per-rubric `rubric_id` selection model this note used to flag as inconsistent has been removed — see Sections 4.1 and 4.2 below, which now reflect the single-active-rubric model directly.

### 2.2 Matching algorithm

**Re-resolved — LLM-judged scoring.** This section previously described a deterministic keyword/regex-indicator matcher (`dimension_indicators.py` + `matcher.py`), itself a supersession of an even earlier flat-criteria `pass`/`fail` algorithm. Per the updated SCOPE.md Validation Engine section (Ambiguous Areas item 10), dimension scoring now uses the Claude API to perform genuine narrative judgment instead of a keyword/regex proxy for it. The following supersedes the keyword/regex description entirely; `dimension_indicators.py` is retired and is no longer part of the architecture.

**Call shape — one Claude API call per validation request, not per dimension:**
- Model: a single fixed model constant configured in `config.py` (`claude-sonnet-5` by default) — not user-selectable, not read from client input.
- Temperature: **no `temperature` parameter is sent.** This was originally specified as `0` to maximize repeatability, but `claude-sonnet-5` (the configured model) rejects `temperature` as a deprecated parameter for this model generation — confirmed against the live API, not a hypothetical. See the determinism note in SCOPE.md's Validation Engine section: this was already documented as best-effort consistency, not a byte-for-byte determinism guarantee, and remains so with no sampling control set at all.
- Authentication: the Anthropic API key supplied by the user for this request (see Section 4.1 and Section 6 below) — never a server-configured key.
- Timeout: a 60-second bound on the Claude API call, set explicitly rather than relying on the Anthropic SDK's own 600-second default. Without this, a stalled (not actively refused) outbound network path — a proxy or firewall silently dropping the connection rather than rejecting it — leaves the request hanging for up to ten minutes with no error shown to the user. A timeout surfaces as `502 llm_service_error` (Section 6.3) with a message pointing at outbound network access as the likely cause.
- Prompt content: the full extracted record text, plus, for every dimension `R1`–`R10`, its `name`, `question`, and all five prose `levels` (`"1"`–`"5"`) verbatim from the loaded rubric. No keyword/regex indicators exist anymore — the model reads the rubric's own language directly.
- Requested output: a single structured (tool-use / forced JSON schema) response containing, for each of the ten `rubric_id`s, exactly one object: `{"rubric_id": "R#", "score": <1-5 integer or the literal string "N/E">, "evidence_quote": <a verbatim substring of the record text supporting the score, or null when score is "N/E">}`. The model is instructed to select the **single best-fitting level** for each dimension from its five prose descriptions, or `"N/E"` if the record provides no evidence either way — the same discrete semantics the keyword/regex matcher enforced.

**Backend-side validation of the LLM response (do not trust it blindly):**
- The response must be valid structured output containing exactly the ten expected `rubric_id`s, each with `score` in `{1, 2, 3, 4, 5, "N/E"}` and no other value. Any deviation (missing dimension, out-of-range score, malformed JSON) is **not** silently coerced or defaulted — treat it as an `llm_service_error` (see Section 4.1).
- `evidence_quote` is verified as an actual case-insensitive substring of the extracted record text before it is trusted. If it verifies, it becomes that dimension's `matched_snippet`. If it does not verify (hallucinated quote, or the model returned `null`), `matched_snippet` is `null` — the dimension's `score` and `matched_level_text` are still used as returned; a failed quote-verification does not invalidate the score itself.
- `matched_level_text` is **never** taken from the LLM's own words — it is always looked up from the trusted, read-only rubric file itself: `dimension.levels[str(score)]` for a numeric score, or the fixed `N/E` scale-meaning text (same convention as before) when `score` is `"N/E"`. This keeps the level prose shown to the user authoritative and unchangeable by model output, even though the model now selects *which* level applies.
- No embeddings, no similarity scoring, no partial/fractional level scores — the result the backend accepts is always a discrete `1`–`5` integer or the literal `"N/E"`, exactly as before.
- **Evidence for "why":** the verified `matched_snippet` plus the rubric-sourced `matched_level_text` together satisfy SCOPE.md's Output requirement to show "which level description was matched/assigned and why." When the score is `N/E`, there is no snippet, same as before.

### 2.2.1 What stays exactly the same
Everything downstream of "the dimension has a score" is unchanged by this update: Section 2.3's weighted-points formula, hard-rule evaluation, decision-band lookup, and the `flagged_gaps` threshold all operate on the score value however it was derived, with no awareness of whether it came from keyword matching or LLM judgment.

### 2.3 Aggregation into overall result

**Resolved** (supersedes the pass/fail-fraction aggregation this section originally described, which does not apply to the weighted narrative rubric actually shipped):

- **Per-dimension points:** `points = (score / 5) * weight` per `scoring_method` in the rubric file (`N/E` = 0 points).
- **Overall score:** sum of all ten dimensions' points, 0–100, rounded to 1 decimal using half-up rounding (`decimal.ROUND_HALF_UP`), not Python's built-in `round()` (banker's rounding / round-half-to-even) — e.g. `2.25` rounds to `2.3`, not `2.2`. Per-dimension points are rounded the same way.
- **Decision band:** the `decision_bands[]` range (from the rubric file) containing the overall score. **Decision (bugfix):** the rubric file's bands use adjacent integer `min`/`max` (58–73, 74–87, ...), but the overall score is a float — a naive `min <= score <= max` check leaves every boundary uncovered (e.g. `73.6` matches nothing and previously crashed with an unhandled 500). The correct, intended behavior: sort bands descending by `min` and take the first one the score meets or exceeds — this treats each band's `max` as extending up to (but not including) the next band's `min`, which is what the integer ranges were always meant to express for a score that can land on any tenth.
- **Hard rules:** evaluate every entry in the rubric file's top-level `hard_rules[]` against the assigned dimension scores. Any hard rule whose `trigger` condition is met contributes its `action` as a candidate decision.
- **Resolving multiple triggered hard rules:** if more than one hard rule triggers with different `action`s, the **most severe** action wins, using the rubric file's `severity_order[]` (index order = best-to-worst) to compare. This tie-break isn't specified elsewhere and is fixed here.
- **Final decision:** if any hard rule triggered, its (most severe, if multiple) action is the final `decision`, overriding the weighted-total band entirely. Otherwise, the weighted-total band from `decision_bands[]` is the final `decision`.
- **Flagged gaps:** every dimension scoring `N/E`, `1`, or `2` is a "gap," surfaced separately (per SCOPE.md's requirement to show what's missing) — this threshold follows the rubric's own language, where `1`–`2` describe material/significant deficiencies and `N/E` means no evidence at all.

---

## 3. Scoring Output Shape (JSON Schema)

**Resolved.** The shape below replaces the flat-criteria schema this section originally described (`criteria_results`, `score_fraction`, `required_total`, etc.), which does not apply to the weighted narrative dimension rubric actually shipped in `med_record_rubrics.json`. It follows directly from the scoring/aggregation rules in Sections 2.1–2.3 and from SCOPE.md's Output requirements (per-dimension score, weighted overall score, decision band, which level was matched and why, and any triggered `hard_rules`).

```json
{
  "record_filename": "patient_discharge_0472.pdf",
  "rubric_title": "Medical Record Narrative - Clinical Documentation Integrity Evaluation Rubric",
  "rubric_version": "1.0",
  "overall": {
    "score_points": 82.4,
    "score_max": 100,
    "decision": "ACCEPTED WITH QUERY",
    "decision_note": "Codable, but one or more elements require a compliant provider query before final code assignment.",
    "hard_rules_triggered": []
  },
  "dimension_results": [
    {
      "rubric_id": "R1",
      "name": "Authentication and Legal Integrity",
      "weight": 8,
      "score": 4,
      "points_earned": 6.4,
      "matched_level_text": "Fully authenticated with one minor lapse - a verbal order co-signed outside the policy window, or a late entry labelled but without a stated reason.",
      "matched_snippet": "...co-signed by Dr. Rao on 03/14 at 22:10, one day after the policy window...",
      "hard_rule_triggered": null
    },
    {
      "rubric_id": "R5",
      "name": "Diagnostic Specificity and Coding Support",
      "weight": 14,
      "score": 1,
      "points_earned": 2.8,
      "matched_level_text": "The narrative will not support assignment of a principal diagnosis; or diagnoses appear only as 'possible', 'probable' or 'rule out' in an outpatient record, where such statements are not codable.",
      "matched_snippet": null,
      "hard_rule_triggered": "HR-2"
    }
  ],
  "flagged_gaps": [
    {
      "rubric_id": "R5",
      "name": "Diagnostic Specificity and Coding Support",
      "weight": 14,
      "score": 1
    }
  ],
  "processed_at": "2026-08-26T10:15:00Z"
}
```

- **Decision:** Field names are fixed as shown — `snake_case` throughout, ISO-8601 UTC timestamp for `processed_at`.
- **Decision:** `dimension_results` always ordered `R1`→`R10`, matching the rubric file's `rubrics[]` order — not by score, not alphabetically.
- **Decision:** `score` is either an integer `1`–`5` or the literal string `"N/E"`.
- **Decision:** `matched_snippet` is `null` whenever `score` is `"N/E"`, and **may also be `null` for a numeric score** if the LLM's quoted evidence fails substring verification against the record text (Section 2.2) — a null snippet on a scored dimension does not mean the score is untrusted, only that no verifiable quote is shown. `matched_level_text` is always populated regardless of whether a snippet exists — it's the assigned level's prose, sourced from the rubric file, never from the LLM.
- **Decision:** `overall.hard_rules_triggered` lists every hard rule that fired (`{"id", "rubric_id", "action", "reason"}`, from the rubric file's `hard_rules[]`), even when only one determines the final decision under Section 2.3's severity tie-break — so the UI can surface every compliance flag, not just the deciding one.
- **Decision:** `flagged_gaps` includes dimensions scoring `N/E`, `1`, or `2` (Section 2.3's gap threshold) — a derived convenience view, not a separate data source.
- No `rubric_id`/`rubric_name` selection fields on this response — per Sections 4.1/4.2 below, there is exactly one active rubric and no per-run rubric choice.
- This schema is the complete and only response shape for a successful validation. No optional/nullable top-level fields beyond what's shown.

---

## 4. API Contract

Base path: `/api/v1`

### 4.1 `POST /api/v1/validate`
Runs extraction + LLM-judged validation in one synchronous call.

**Request:** `multipart/form-data`
| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | yes | PDF, TXT, or DOCX, ≤10 MB |
| `anthropic_api_key` | text | yes | The user's own Claude API key, collected by the frontend before the upload step is shown (Section 6). Used only for this request's Claude API call; never persisted, never logged. |

- **Decision (resolves SCOPE.md ambiguity #8):** No `rubric_id` field. There is exactly one active rubric (`med_record_rubrics.json`), loaded once at startup — nothing to select per run.
- **Decision:** the API key travels as a same-request multipart form field rather than a header or a separate "register key" endpoint — this keeps the app's no-session, no-persistence, single-request-cycle architecture intact (SCOPE.md's Architecture section): there is nothing to store between a key-entry step and an upload step, because they happen in the same HTTP request.

**Success response:** `200 OK`, body = the schema in Section 3.

**Error responses:**
| Status | Condition | Body |
|---|---|---|
| 400 | Missing `file` field | `{"error": "missing_field", "message": "..."}` |
| 400 | Missing `anthropic_api_key` field | `{"error": "missing_api_key", "message": "..."}` |
| 415 | File MIME type not PDF/TXT/DOCX | `{"error": "unsupported_file_type", "message": "..."}` |
| 413 | File exceeds 10 MB | `{"error": "file_too_large", "message": "..."}` |
| 422 | Extraction failure (corrupted, password-protected, empty/near-empty text) | `{"error": "extraction_failed", "message": "...", "reason": "corrupted \| password_protected \| empty_content \| decode_error"}` |
| 401 | Claude API rejected the supplied key (authentication error) | `{"error": "invalid_api_key", "message": "..."}` |
| 502 | Claude API call failed for any other reason (network error, rate limit, timeout, or a response that fails the Section 2.2 structured-output validation) | `{"error": "llm_service_error", "message": "..."}` |
| 500 | Unhandled server error | `{"error": "internal_error", "message": "An unexpected error occurred."}` |

- **Decision:** All error bodies follow the same two-key minimum shape (`error`, `message`), with `reason` as an optional third key only for `extraction_failed`. This is the one and only error envelope used across every endpoint.
- **Decision:** the `anthropic_api_key` value itself never appears in any error body, log line, or traceback — the same rule that already applies to record text (`CLAUDE.md` PHI rules) applies to the API key, and is spelled out separately in Section 6 below since a credential warrants at least as much care as record content.

### 4.1.1 `POST /api/v1/api-key/validate`
**Added.** A live, no-cost pre-check for the key `ApiKeyGate.jsx` collects, run before the upload step is shown at all (Section 6.1) — so a bad key is caught immediately with a clear message, rather than only surfacing after the user has already picked a file, waited through extraction, and hit `401` on the real `/validate` call.

**Request:** `application/json` (no file involved, so no multipart form here)
```json
{ "anthropic_api_key": "sk-ant-..." }
```

- **Decision:** validation calls `GET /v1/models` via the Anthropic SDK (`client.models.list(limit=1)`) with the supplied key — a pure authentication check against a metadata endpoint, not a scoring call, so it costs no tokens and doesn't touch record content at all (there is none at this point).
- **Decision:** this is a genuine live check against the Claude API, not a client-side format check (e.g. regexing for an `sk-ant-` prefix) — a syntactically valid but revoked/wrong key still fails here rather than being accepted and only failing later.

**Success response:** `200 OK`, `{"valid": true}`.

**Error responses:**
| Status | Condition | Body |
|---|---|---|
| 400 | Missing/empty `anthropic_api_key` | `{"error": "missing_api_key", "message": "..."}` |
| 401 | Claude API rejected the supplied key | `{"error": "invalid_api_key", "message": "..."}` |
| 502 | Claude API call failed for any other reason (network, timeout, unexpected error) | `{"error": "llm_service_error", "message": "..."}` |

- **Decision:** same error envelope, same two error codes (`invalid_api_key`, `llm_service_error`) as `POST /validate` (Section 4.1) — the frontend's existing error-handling for those codes covers this endpoint too, no new cases to add on the client beyond wiring this call into `ApiKeyGate.jsx`.
- **Decision:** passing this check is advisory, not a session/token the backend remembers — `POST /validate` still requires and independently re-validates `anthropic_api_key` on every call (Section 4.1). A key could be revoked in the gap between the two checks; `/validate`'s own `401`/`502` handling remains the authoritative, final check.

### 4.2 `GET /api/v1/rubrics`
Returns metadata for the single active rubric (resolves SCOPE.md ambiguity #8). There is no rubric dropdown/selection step in v1; this endpoint lets the frontend display which rubric is active rather than let the user choose one.

**Request:** none.

**Success response:** `200 OK`
```json
{
  "rubric_title": "Medical Record Narrative - Clinical Documentation Integrity Evaluation Rubric",
  "rubric_version": "1.0",
  "framework": "AHIMA/ACDIS high-quality documentation criteria, PDQI-9 note-quality domains, CMS 42 CFR 482.24, ICD-10-CM Official Guidelines",
  "dimensions": [
    {"rubric_id": "R1", "name": "Authentication and Legal Integrity", "weight": 8},
    {"rubric_id": "R2", "name": "Chief Complaint and History of Present Illness", "weight": 10}
  ]
}
```
- **Decision:** A single object, not a `{"rubrics": [...]}` array — there is only ever one active rubric. `dimensions[]` lists all ten `R1`–`R10` entries with just `rubric_id`/`name`/`weight` (no `levels` prose, no `hard_rules`). Full rubric content is never exposed via the API; it stays an internal, server-side detail loaded once at startup.

### 4.3 `GET /api/v1/health`
**Decision:** Included for basic liveness checking even though monitoring/observability is out of scope — this is a trivial, standard endpoint, not an observability stack.

**Response:** `200 OK`, `{"status": "ok"}`. No dependencies checked (no DB to check).

### 4.4 CORS
- **Decision:** CORS enabled via `flask-cors`, restricted to the specific origin the React dev/prod server runs on (configured via environment variable `ALLOWED_ORIGIN`, single value, not a wildcard).

### 4.5 Error envelope (global)
- **Decision:** All 4xx/5xx responses across all endpoints return `Content-Type: application/json` and never leak stack traces to the client. Server-side, the full traceback is logged (PHI-redacted per Section 1.3); client-side, only the fields in the tables above are ever returned.
- **Decision:** No API versioning strategy beyond the `/v1` path prefix baked in from day one — no header-based or query-param versioning.

---

## 5. File / Directory Structure

```
cdi-scorer/
├── backend/
│   ├── app.py                      # Flask app factory, blueprint registration, CORS setup
│   ├── config.py                   # Env-driven config (ALLOWED_ORIGIN, MAX_FILE_SIZE_MB, CLAUDE_MODEL, etc.) — no API key here
│   ├── requirements.txt
│   ├── med_record_rubrics.json     # Fixed rubric definitions
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── validate.py             # POST /api/v1/validate, POST /api/v1/api-key/validate
│   │   ├── rubrics.py              # GET /api/v1/rubrics
│   │   └── health.py               # GET /api/v1/health
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── detect.py               # MIME sniffing, size checks
│   │   ├── pdf_extractor.py
│   │   ├── docx_extractor.py
│   │   ├── txt_extractor.py
│   │   └── errors.py               # ExtractionError and subtypes
│   ├── phi/
│   │   ├── __init__.py
│   │   ├── presidio_config.py      # Analyzer/anonymizer setup, custom AADHAAR/PAN recognizers
│   │   └── redact.py               # redact_for_logging(text) helper used by logging + error paths
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── rubric_loader.py        # Loads/validates med_record_rubrics.json at startup
│   │   ├── llm_judge.py            # Claude API call + structured-output validation (Section 2.2) — replaces the retired matcher.py / dimension_indicators.py
│   │   └── scorer.py               # Aggregation into overall result (Section 2.3, Section 3 schema) — unchanged
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── validation_result.py    # Dataclass/pydantic model mirroring Section 3 schema
│   └── tests/
│       ├── golden/                 # Fixed sample records + expected JSON outputs
│       ├── test_golden.py
│       ├── test_extraction.py
│       ├── test_llm_judge.py       # renamed from test_matcher.py — mocks the Claude API call
│       ├── test_scorer.py          # aggregation edge cases (decision-band boundaries, Section 2.3)
│       └── test_api.py
├── frontend/
│   ├── package.json
│   ├── public/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api/
│   │   │   └── client.js           # fetch wrappers for /validate, /api-key/validate, /rubrics, /health
│   │   ├── components/
│   │   │   ├── ApiKeyGate.jsx      # collects the user's Claude API key, live-checks it via POST /api-key/validate, and only then gates the upload step open (Section 4.1.1, Section 6)
│   │   │   ├── UploadForm.jsx
│   │   │   ├── RubricSelector.jsx
│   │   │   ├── ResultsSummary.jsx
│   │   │   ├── CriteriaList.jsx
│   │   │   └── GapsList.jsx
│   │   └── styles/
│   │       └── tokens.css          # design tokens (Section 7.1) — the only place colors/spacing/type sizes are defined
│   └── .env                        # REACT_APP_API_BASE_URL
├── SCOPE.md
├── SPEC.md
└── README.md
```

- **Decision:** Backend is a Flask **application factory** pattern (`create_app()` in `app.py`) with blueprints per route group — chosen for testability with the golden-file suite, not because scale requires it.
- **Decision:** Rubric file lives inside `backend/` and is loaded once at app startup into memory (not re-read per request) — reloaded only on process restart, consistent with "not user-editable through the UI."
- **Decision:** No `models/` or `db/` directory — there is no database, per SCOPE.md.
- **Decision:** No `services/` layer separate from `validation/` and `extraction/` — those two packages are the service layer; no additional abstraction layer is introduced for v1. The Claude API client call lives directly in `validation/llm_judge.py`, not in a new `llm/` or `clients/` directory — same reasoning as the rest of this decision.
- **Decision:** `dimension_indicators.py` is removed — it has no role once dimension scoring is LLM-judged. `matcher.py` is renamed `llm_judge.py` to reflect what it now does; `test_matcher.py` is renamed `test_llm_judge.py` accordingly (mocking the Anthropic client so the test suite never makes a real network call or requires a real API key).

---

## 6. LLM Judging &amp; API Key Contract

This section is the authoritative source for the Claude API integration added on top of the original spec — Section 2.2 covers the scoring call itself; this section covers where the required API key comes from and how it is handled.

### 6.1 Where the key comes from
- The backend has **no** server-configured Anthropic API key (no `ANTHROPIC_API_KEY` environment variable is read by the app). Every `/validate` call must supply its own key via the `anthropic_api_key` form field (Section 4.1).
- The frontend collects this key from the user via `ApiKeyGate.jsx` **before** the upload step (`UploadForm.jsx`) becomes available — the user cannot reach the file picker without first entering a key.
- **Updated:** `ApiKeyGate.jsx` no longer just gates the UI client-side — on submit, it calls `POST /api-key/validate` (Section 4.1.1) and only reveals `UploadForm.jsx` if that call succeeds. A key that fails is never sent anywhere else; the user sees the rejection immediately and can correct it before touching the upload flow at all.

### 6.2 Handling rules (non-negotiable, same rigor as PHI)
- The key exists in the frontend only in component state for the current page session — **never** written to `localStorage`, `sessionStorage`, cookies, or any browser storage that survives a refresh. Re-entering the key after a page reload is expected behavior, not a bug.
- The key exists on the backend only for the duration of the single request that carries it — passed directly to the Anthropic client call in `llm_judge.py` and discarded when the request completes. It is never written to disk, never included in application state, never cached.
- The key is never logged, in whole or in part, at any log level, in this module or any other. Unlike record text, there is no "redact and log" fallback for the key — it simply never appears in a log statement at all.
- The key never appears in any HTTP response body, including error responses. A `401 invalid_api_key` response describes the failure; it does not echo back any part of the key that caused it.

### 6.3 Failure handling
- An Anthropic authentication error (invalid/revoked key) surfaces as `401 invalid_api_key` (Section 4.1, Section 4.1.1).
- Any other Claude API failure — network error, timeout, rate limit, or a response that fails the Section 2.2 structured-output validation — surfaces as `502 llm_service_error`. These are distinguished so the frontend can show "check your API key" versus "try again in a moment" rather than one generic message.
- `validation/llm_judge.py` shares one internal error-translation path between the scoring call (`judge_record`) and the key-check call (`validate_api_key`, backing Section 4.1.1) — both raise only `InvalidApiKeyError` or `LLMServiceError`, never a raw exception, so a route handler never has to guess what an unclassified failure means.

---

## 7. Frontend Visual Design System

**Why this section exists:** Sections 1–6 specify data shape and behavior exhaustively but say nothing about how the UI should actually look — left unspecified, that produces an unstyled, hard-to-read app. This section is as binding as the rest of the contract: a build that satisfies Sections 1–6 but ignores this one is not spec-complete.

### 7.1 Design tokens
- All colors, spacing, type sizes, and radii are defined once as CSS custom properties in `frontend/src/styles/tokens.css`, imported once (in `index.js` or `App.jsx`) — never scattered as ad hoc/magic values across individual component stylesheets.
- **Color palette** — semantic, tied to the app's actual signal (decision outcomes), not decorative:
  - `--color-bg`, `--color-surface`, `--color-border`, `--color-text`, `--color-text-muted`.
  - `--color-accepted` (green family) for `DOCUMENTATION ACCEPTED`.
  - `--color-query` (amber family) for `ACCEPTED WITH QUERY`.
  - `--color-clarification` (orange family) for `RETURN FOR CLARIFICATION`.
  - `--color-deficient` (red family) for `DEFICIENT`.
  - `--color-primary` — one accent for interactive elements (buttons, links, focus rings), independent of the decision-band colors above so the two meanings are never visually confused.
- **Typography** — one system font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`; no webfont dependency), a fixed type scale (13 / 14 / 16 / 20 / 28 / 36px for label / body / subhead / heading / score-display), line-height 1.5 for body text and 1.2 for headings.
- **Spacing** — a 4px base unit (4 / 8 / 12 / 16 / 24 / 32 / 48px), applied via the custom properties above, not ad hoc per-component pixel values.
- **Radius and elevation** — one radius for cards/inputs (8px) and a smaller one for badges/pills (4px); a single subtle shadow for cards and nothing else — flat design otherwise, not a shadow on every element.

### 7.2 Layout
- Centered single-column content area, max-width ~720px, with side padding that keeps it usable down to a 375px-wide viewport without horizontal scroll (mobile-first, not desktop-only).
- A persistent app header (app name + the active rubric's title/version from `GET /rubrics`, Section 4.2) shown across every step.
- Each step — key entry, upload, results — renders as its own visually distinct "card" (surface + border + padding), never a bare, unstyled block of form controls sitting directly on the page background.

### 7.3 Component-specific requirements
- **`ApiKeyGate.jsx`** — a real styled text input (type `password`) with a visible `<label>` and help text, and a submit button with three distinct visual states: idle, checking (spinner, disabled), and error (red-toned border plus an inline error message) — not plain text silently appearing or disappearing.
- **`UploadForm.jsx`** — a clearly bounded file-selection area (at minimum a styled row showing the chosen filename, ideally a dashed-border drop-zone treatment) plus a primary submit button with a loading state during the `/validate` call (spinner, disabled — never a frozen page with no feedback).
- **`ResultsSummary.jsx`** — the overall score is the single most visually prominent element on the results view: a large numeral (`score_points`/100), a colored decision-band badge using Section 7.1's palette, and `decision_note` as supporting text beneath — not a plain "Score: 82.4, Decision: ACCEPTED WITH QUERY" text line. When `hard_rules_triggered` is non-empty, show it as a prominent alert banner above the score, not buried in the criteria table below — a hard rule overriding the weighted decision is the single most important fact about the result.
- **`CriteriaList.jsx`** — each of the ten dimensions as its own row/card: name, weight, and score shown as a small colored badge (Section 7.1's palette, keyed by score: 4–5 accepted-toned, 3 query-toned, 1–2 or `N/E` deficient-toned), `matched_level_text` as body copy, and `matched_snippet` (when present) visually set apart as a quote — left border, italic, muted background — rather than inline plain text.
- **`GapsList.jsx`** — visually distinct from `CriteriaList`, not a duplicate plain list: a clearly separated "Flagged Gaps" section with a warning-toned header, since its entire purpose is to draw the eye to what needs attention.

### 7.4 States every screen must handle visually
- **Loading** (API key check, or the `/validate` call in flight) — a visible spinner/progress indicator, submit controls disabled, no possibility of a duplicate double-submit.
- **Error** (every error code in Section 4.1/4.1.1's tables) — a styled inline message (CLAUDE.md already requires each error code to map to a distinct, specific message; this section requires that message be *styled* — e.g. a red-toned inline banner — never a raw browser `alert()` or an unstyled text dump).
- **Empty/initial** — nothing renders looking broken or like a placeholder was forgotten (e.g. `UploadForm` before any file is chosen shows real, styled empty-state copy, not blank space).

### 7.5 Accessibility baseline
- Every text/background color pairing defined in 7.1 meets WCAG AA contrast (4.5:1 for body text) — a real constraint on the palette values chosen, not a stylistic afterthought.
- Every interactive element has a visible focus state (outline or ring) — never `outline: none` with nothing substituted in its place.
- Every form input has an associated `<label>`, not a placeholder standing in for one.

### 7.6 What this section deliberately does not require
- No CSS framework or component library (Tailwind, MUI, Bootstrap, styled-components, etc.) — plain CSS with the custom-property token system in 7.1 is sufficient, and keeps `frontend/package.json`'s dependency list exactly as it already is. Adding one later is a "new dependency" decision under CLAUDE.md's "When to ask" rule, not something this section pre-authorizes.
- No animation/motion design beyond simple state transitions (e.g. `transition: background-color 150ms` on interactive elements) — no page-transition library, no complex choreography.
- No dark mode or theming toggle — one fixed light palette, consistent with the rest of this app's no-configuration-surface posture (SCOPE.md).