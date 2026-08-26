# SCOPE.md — Medical Record Validator (Clinical Documentation Integrity Scorer)

## Problem Statement (as given)
Build a medical record validation tool that checks records against a predefined rubric.

---

## IN SCOPE

### Input
- Accept a single medical record upload per validation run, in **PDF, TXT, or DOCX** format.
- Extract text content from the uploaded file (native text layers only — see Out of Scope for scanned/image PDFs).
- Basic file-type and size validation before processing (reject unsupported formats with a clear error).

### Rubric
- Rubric is a **fixed, predefined JSON file** (`med_record_rubrics.json`) bundled with the app — not user-editable through the UI, not uploaded per-run.
- The rubric is a **single narrative-scored rubric set**, not a collection of keyword/regex criteria: ten fixed, weighted dimensions (`R1`–`R10` — e.g. Authentication and Legal Integrity, Diagnostic Specificity and Coding Support), each with a `weight` (points out of a 100-point total) and five prose `levels` (1–5) describing what documentation looks like at that score. A record is scored 1–5 (or `N/E`, "no evidence," which contributes 0 points) against each dimension's level descriptions — not matched against a keyword/pattern list.
- Select dimensions carry a `hard_rules` override that can force a specific overall decision outright (e.g. an Authentication score of 1 forces `DEFICIENT`) regardless of the weighted total — see SPEC.md Section 2.1.

### Validation Engine
- Score each of the ten rubric dimensions 1–5 (or `N/E`) against its narrative level descriptions, per SPEC.md Section 2.1/2.2.
- Convert each dimension score to weighted points (`(score / 5) * weight`) and sum across all ten dimensions for a 0–100 overall score, per SPEC.md's `scoring_method`.
- Map the overall score to one of four `decision_bands` (`DOCUMENTATION ACCEPTED`, `ACCEPTED WITH QUERY`, `RETURN FOR CLARIFICATION`, `DEFICIENT`), applying any triggered `hard_rules` override first.
- **Updated:** each dimension is scored by an LLM (the Claude API) that reads the record's full extracted text alongside that dimension's five prose `levels` and selects the single best-fitting level, or `N/E` if none fits — genuine narrative judgment, not a keyword/regex proxy for it. This replaces the earlier keyword/regex-indicator matcher entirely. See SPEC.md Section 2.2 for the full prompt/response contract and Section 2.3 for how dimension scores (however derived) aggregate into the overall decision, which is unchanged.
- No longer strictly deterministic bit-for-bit — the LLM call was originally specified with temperature 0 to maximize repeatability, but the configured model (`claude-sonnet-5`) rejects `temperature` as deprecated, so no sampling control is set at all; LLM output is not guaranteed byte-identical across calls the way keyword/regex matching was. This supersedes the earlier "deterministic" requirement. The discrete output contract (integer 1–5 or the literal `N/E`, no confidence scores) is unchanged and still enforced.

### PHI Handling
- Apply PHI detection/redaction (e.g., via Presidio) to extracted text before it is logged, displayed in debug output, or persisted anywhere outside the active session.
- No PHI written to application logs.
- **Known, accepted tradeoff:** the full unredacted extracted text is now also sent to the Claude API for LLM-judged scoring (see Validation Engine, above, and SPEC.md Section 2.2). This is a new category of exposure beyond what earlier versions of this app had — record text leaves the local process boundary in a third-party API call. This is intentional and required for the LLM to judge the record against the rubric; it is not a gap to "fix" by redacting the text sent to the LLM, which would break scoring. Anyone deploying this app is exposing uploaded record content to Anthropic's API on every validation run.

### LLM API Key Handling
- The application does **not** hold or configure its own Anthropic API key. Each user supplies their **own** Claude API key through the frontend, before the upload step is made available.
- **Updated:** the key is validated live against the Claude API (a no-cost auth check, not a scoring call — see SPEC.md Section 4.1.1) before the upload step is shown, not just checked for non-emptiness client-side. A wrong, revoked, or malformed key is caught immediately, before the user has picked a file or waited through extraction — not only after a full `/validate` round-trip fails.
- The key is used only for the duration of a single request (the key-check request, or a `/validate` request — to authenticate that request's Claude API call) and is **never persisted** — not to disk, not to a database, not in server memory beyond the request, not in browser storage across sessions. This mirrors the no-persistence rule already in place for uploaded records.
- The key is never logged, in whole or redacted form, and never included in any error response body — treat it with at least the same rigor as PHI (see `CLAUDE.md`'s API-key handling rules).

### Output
- Display validation results (per-dimension 1–5 score or `N/E`, the weighted overall score out of 100, and the resulting decision band) in the UI.
- Allow the user to view, per dimension, which level description was matched/assigned and why, plus any `hard_rules` that were triggered and the resulting override.

### Architecture
- **Frontend:** React single-page app.
- **Backend:** Flask REST API.
- **Processing model:** synchronous request/response — user uploads, waits, gets a result in the same HTTP request/response cycle. This cycle now includes one outbound call to the Claude API (Anthropic) per validation run, made with the user-supplied API key — the app requires outbound internet access to function, which it did not before this change.
- Single environment, single deployment target (no environment-specific config beyond dev/prod basics).

### Testing
- Golden-file regression test suite covering the parser and validator against a fixed set of sample records and expected results.

---

## OUT OF SCOPE (explicit)

### Input handling
- No OCR for scanned/image-only PDFs — only PDFs with an extractable text layer are supported.
- No support for HL7, FHIR, CCD/CCDA, or other structured clinical data formats — only PDF/TXT/DOCX.
- No batch upload or multi-file upload in a single run — one record per validation run.
- No drag-and-drop folder ingestion, email ingestion, or integration with an EHR/EMR system for automatic record retrieval.
- No handwriting recognition.

### Rubric handling
- No rubric authoring UI — rubrics are not created, edited, or versioned through the application.
- No support for multiple simultaneously-selectable rubrics per run (one fixed rubric file, one active version).
- No per-user or per-organization custom rubrics.

### Validation logic
- **Superseded, see Ambiguous Areas item 10 below:** dimension scoring now uses an LLM-based judgment layer (the Claude API) — this reverses the earlier "no LLM judgment, deterministic only" default. What's still out of scope: embedding- or vector-similarity-based matching (a different technique from LLM narrative judgment) — the LLM reads and reasons over the full text and rubric prose directly, not via a retrieval/similarity step.
- No confidence scores or probabilistic outputs in the response — results are still discrete per dimension (an integer 1–5, or `N/E`), not a probability or similarity score; the LLM is constrained to return one of these discrete values, never a numeric confidence.
- No clinical decision support, diagnosis suggestion, or treatment recommendation of any kind — the LLM's role is strictly to grade documentation quality against the rubric's own prose, the same scope the keyword/regex matcher had, not to reason about clinical correctness.
- No cross-record comparison or trend analysis across multiple records.
- No LLM involvement anywhere except dimension scoring — extraction, PHI redaction, weighted aggregation, hard-rule evaluation, and decision-band lookup all remain plain deterministic code (SPEC.md Sections 1, 2.3).

### Users & access
- No user authentication or multi-user accounts.
- No role-based access control (e.g., admin vs. reviewer vs. auditor).
- No per-user history, saved sessions, or personalized dashboards.
- No audit trail of who validated what and when.

### Data persistence & security
- No database — no persistent storage of uploaded records or validation results beyond the active session/response.
- No encryption-at-rest (nothing is stored at rest in scope).
- No secure long-term archival or record retention policy.
- No data export beyond what's shown on screen (no PDF/CSV report generation) unless explicitly added later.
- No server-side storage of the user-supplied Anthropic API key, in any form — see "LLM API Key Handling" above. No API-key-management UI (no saved keys, no key rotation, no multiple stored keys).

### Infrastructure & operations
- No async job queue — no Celery, Redis, or background worker processing; all processing is synchronous within the HTTP request.
- No horizontal scaling, load balancing, or multi-instance deployment considerations.
- No CI/CD pipeline setup (build/test only, not deploy automation).
- No monitoring, alerting, or observability stack (e.g., no Sentry, Prometheus, structured log aggregation).
- No containerization/Docker packaging unless separately requested.
- No rate limiting or API throttling.

### Integrations
- No third-party EHR/EMR integration (Epic, Cerner, etc.).
- No email/SMS notifications on validation completion.
- No webhook or external API callback support.
- **Clarification:** the Claude API call added for LLM-judged scoring (see Validation Engine, above) is the one explicit, sanctioned external API dependency this app has — it is not a "webhook" or "callback" integration in the sense excluded above (it's a synchronous, in-request call the backend makes and waits on, not an inbound integration or async notification).

### Internationalization
- No multi-language rubric support or multi-language record parsing — English-language records and rubric only.

---

## AMBIGUOUS AREAS — Decisions Needed (with proposed defaults)

1. **What counts as a "record"?** A single document, or a bundle of documents representing one patient encounter?
   → **Default:** One uploaded file = one record = one validation run. Multi-document encounters are out of scope for v1.

2. **Rubric criteria structure** — is each criterion a simple keyword/regex match, or does it need structured logic (AND/OR combinations, conditional criteria depending on record type)?
   → **RESOLVED by SPEC.md Section 2.1**, matching the actual `med_record_rubrics.json` file: rubric dimensions are not keyword/regex criteria at all. There are ten fixed dimensions (`R1`–`R10`), each scored 1–5 against prose level descriptions, weighted, and summed into a 0–100 total. No nested/conditional criteria — but also no AND/OR keyword logic *in the rubric file itself*; the earlier keyword/regex default above no longer applies to the rubric's own structure. (SPEC.md Section 2.2 separately resolves *how* a 1–5 score is derived, using per-level keyword/regex indicators defined outside the rubric file — that's an implementation detail of the matcher, not a change to the rubric file's structure.)

3. **Partial credit** — does a criterion resolve to pass/fail only, or can it be "partially met"?
   → **RESOLVED by SPEC.md Section 2.1:** each dimension resolves to a graded 1–5 score (or `N/E`, which scores 0 points), not pass/fail. This supersedes the earlier pass/fail-only default.

4. **Scoring model** — is the overall result a percentage, a letter grade, a pass/fail threshold, or a raw count of criteria met?
   → **RESOLVED by SPEC.md Section 2.1:** weighted points per dimension (`(score / 5) * weight`), summed to a 0–100 total, mapped to one of four `decision_bands` (`DOCUMENTATION ACCEPTED` / `ACCEPTED WITH QUERY` / `RETURN FOR CLARIFICATION` / `DEFICIENT`), with `hard_rules` able to force a band outright. Dimensions are explicitly *not* weighted equally — weights vary per dimension (e.g. Diagnostic Specificity = 14, Authentication = 8) — which supersedes the earlier equal-weighting default.

5. **What happens on extraction failure** (e.g., PDF has no extractable text, DOCX is corrupted)?
   → **Default:** Return a clear error to the user stating extraction failed and why, with no partial/fallback OCR attempt. The run does not proceed to validation.

6. **PHI handling depth** — is PHI redaction only for internal logging, or should redacted output also be shown to the end user in the UI?
   → **Default:** PHI is redacted before any logging/telemetry. The UI itself shows the user's own uploaded content unredacted (since they uploaded it and are presumably authorized to see it) — redaction protects what leaves the session, not what's displayed back to the uploader.

7. **Rubric versioning** — if `med_record_rubrics.json` changes over time, do old validation results need to indicate which rubric version produced them?
   → **Default:** No versioning tracked in v1, since results aren't persisted beyond the session. Revisit if/when persistence is added.

8. **"Predefined rubrics" (plural) vs. one rubric** — the problem statement says "rubrics," implying possibly more than one (e.g., per record type: discharge summary vs. progress note).
   → **RESOLVED by SPEC.md Section 2.1, opposite of the earlier default:** `med_record_rubrics.json` holds exactly **one** rubric set (ten weighted dimensions under a single `title`/`version`), not a dict of multiple selectable named rubrics. There is no rubric dropdown/selection step in v1.
   → **Resolved:** SPEC.md Section 4.1 does not take a `rubric_id` request field — `/validate` takes `file` plus, as of item 10 below, the required `anthropic_api_key` field. SPEC.md Section 4.2's `GET /api/v1/rubrics` now returns a single object describing the one active rubric (title, version, framework, and its ten dimensions' `rubric_id`/`name`/`weight`), not a list of selectable rubrics.

9. **Definition of "validation"** — does this mean compliance/completeness checking (are required elements present), or clinical accuracy checking (is the content clinically correct)?
   → **Default, refined by SPEC.md Section 2.1:** documentation-quality/compliance checking only — grading each rubric dimension (authentication, specificity, completeness of histories/exam/plan, etc.) against its narrative level descriptions, not a flat "required elements present" checklist. Still no clinical accuracy or correctness judgment (ties to the "no clinical decision support" exclusion above).

10. **How should narrative-level scoring actually be performed** — via keyword/regex proxy, or via genuine LLM judgment?
    → **Originally resolved** (see item 2 above) as keyword/regex indicators authored from each level's prose. **Re-resolved, superseding that:** dimension scoring now calls the Claude API with the record's full text and the dimension's five level descriptions, and the model selects the best-fitting level (or `N/E`). This directly reverses the "No LLM-based judgment layer" default under Out of Scope → Validation logic, which is now itself explicitly in scope. See SPEC.md Section 2.2 for the full contract, and the new "LLM API Key Handling" section above for how the required Anthropic API key is sourced (from the user, per session, never persisted) rather than configured server-side.