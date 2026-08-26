# CLAUDE.md — Instructions for Claude Code

You are building the **Medical Record Validator ("Clinical Documentation Integrity Scorer")**: a React + Flask application that lets a user upload a single medical record (PDF, TXT, or DOCX) and receive a weighted, narrative-rubric score against `med_record_rubrics.json`'s ten fixed dimensions. There is no database, no user auth, and no async processing. **Dimension scoring is LLM-judged**: the backend calls the Claude API (Anthropic) with the record's full text and each dimension's rubric prose, and the model selects the best-fitting level per dimension. There is no server-configured API key — every user supplies their own Claude API key through the frontend, before the upload step is available, and it is used only for that one request. That key is live-validated against the Claude API (`POST /api/v1/api-key/validate`, SPEC.md Section 4.1.1) as soon as it's entered, before the upload step is even shown. See `SPEC.md` Sections 2.2, 4.1.1, and 6 for the full contract, and the "LLM API Key handling" section below.

`SCOPE.md` and `SPEC.md` are already in this repo. They are binding. Read both before writing any code. This file tells you how to work; those files tell you what to build. If anything below and `SPEC.md` ever conflict, `SPEC.md` wins.

---

## Directory structure — follow exactly

Create and use this structure. Do not introduce new top-level directories, and do not add abstraction layers (`services/`, `models/`, `db/`, etc.) beyond what's listed.

```
cdi-scorer/
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── requirements.txt
│   ├── med_record_rubrics.json
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── validate.py         # POST /validate, POST /api-key/validate
│   │   ├── rubrics.py
│   │   └── health.py
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── detect.py
│   │   ├── pdf_extractor.py
│   │   ├── docx_extractor.py
│   │   ├── txt_extractor.py
│   │   └── errors.py
│   ├── phi/
│   │   ├── __init__.py
│   │   ├── presidio_config.py
│   │   └── redact.py
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── rubric_loader.py
│   │   ├── llm_judge.py        # Claude API call (scoring + key validation) — replaces matcher.py / dimension_indicators.py
│   │   ├── errors.py           # InvalidApiKeyError, LLMServiceError (SPEC.md §6.3)
│   │   └── scorer.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── validation_result.py
│   └── tests/
│       ├── golden/
│       ├── test_golden.py
│       ├── test_extraction.py
│       ├── test_llm_judge.py   # mocks the Anthropic client — never makes a real API call or needs a real key
│       ├── test_scorer.py      # decision-band boundary regression coverage
│       └── test_api.py
├── frontend/
│   ├── package.json
│   ├── public/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api/
│   │   │   └── client.js
│   │   ├── components/
│   │   │   ├── ApiKeyGate.jsx   # collects the user's Claude API key, live-checks it via POST /api-key/validate, and only then unblocks UploadForm
│   │   │   ├── UploadForm.jsx
│   │   │   ├── RubricSelector.jsx
│   │   │   ├── ResultsSummary.jsx
│   │   │   ├── CriteriaList.jsx
│   │   │   └── GapsList.jsx
│   │   └── styles/
│   └── .env
├── SCOPE.md
├── SPEC.md
└── README.md
```

Backend uses the Flask application-factory pattern: `create_app()` lives in `app.py`; routes are registered as blueprints from `routes/`. Do not collapse this into a single-file Flask app.

---

## The rubric file is READ-ONLY to generated code

`backend/med_record_rubrics.json` is a fixed, hand-maintained input file.

- **Never write code that modifies, regenerates, auto-formats, or "fixes" this file.**
- **Never write code that writes to this file at runtime**, including admin routes, migration scripts, or setup scripts. There is no rubric-authoring feature — this is a hard exclusion from `SCOPE.md`, not an oversight.
- Load it exactly once, at app startup, in `validation/rubric_loader.py`, into memory. Do not re-read it per-request.
- If you need sample/test rubric content for `tests/golden/`, create **separate fixture files** — never point tests at a modified copy of the real rubric file, and never alter the real file to make a test pass.
- If a task seems to require changing this file's structure (e.g., adding a field to support something), **stop and ask** rather than editing it — see "When to ask" below.

---

## PHI handling — hard constraints, not suggestions

These rules are non-negotiable and apply to every line of code you write, not just the `phi/` module:

1. **Never write extracted record text, or any substring of it, to disk, to a database, or to any persistent store.** The uploaded file and its extracted text may only exist in memory for the duration of a single request.
2. **Never log raw extracted text.** Every log statement, at every level (`info`, `warning`, `error`, `exception`), that could contain record content **must** pass through `phi/redact.py`'s redaction helper first. This includes exception messages and tracebacks — if a traceback could contain interpolated record text, redact before logging, not after.
3. **Never include unredacted record text in an error response body.** If an error message needs to show what went wrong (e.g., a snippet from a failed parse), redact it first via the same helper used for logs.
4. The **only** places raw, unredacted extracted text is allowed to flow are: (a) into the Claude API request payload built by `validation/llm_judge.py` for dimension scoring, and (b) into the final JSON response's `matched_snippet` fields, per `SPEC.md` Sections 1.3, 2.2, and 6 — these are deliberate, documented exceptions (the uploader sees their own content; the LLM needs the content to judge it), not gaps to "fix" by adding redaction there. Do not add redaction to the Claude API call or to the success-response path — that would contradict the spec and break scoring.
5. Do not implement any PHI handling logic outside `phi/presidio_config.py` and `phi/redact.py`. If another module seems to need PHI-awareness, import the helper from `phi/` rather than reimplementing detection logic inline.
6. If you are ever unsure whether a piece of data is "record text" for the purposes of these rules, treat it as if it is.

Violating any of the above is treated as a bug severe enough to block the task, even if the feature otherwise works.

---

## LLM API key handling — hard constraints, not suggestions

The user's Anthropic API key is a credential, not record content — it gets rules at least as strict as the PHI rules above, not the same rules:

1. **Never log the key, in whole or in part, at any log level, anywhere.** Unlike record text, there is no "redact and log" fallback for it — a log statement that could contain the key must simply not include it, full stop.
2. **Never write the key to disk, to a database, or to any persistent store, on the backend or in the browser.** No `localStorage`, `sessionStorage`, or cookie persistence on the frontend; no file, cache, or in-memory store that outlives a single backend request.
3. **Never include the key in an error response body.** A `401 invalid_api_key` response (`SPEC.md` §4.1/§6.3) describes the failure without echoing any part of the key.
4. **The backend never reads an `ANTHROPIC_API_KEY` environment variable or any other server-configured key.** Every Claude API call uses the key supplied on that specific request's `anthropic_api_key` form field — there is no fallback/default key.
5. Do not implement API-key handling logic outside `validation/llm_judge.py` (backend) and `ApiKeyGate.jsx` / `api/client.js` (frontend). Don't pass the key through additional modules "just in case" — narrow its reach to exactly where it's used.

Violating any of the above is treated as a bug severe enough to block the task, even if the feature otherwise works.

---

## Golden regression suite — must always pass

`backend/tests/test_golden.py`, along with its fixtures in `backend/tests/golden/`, is the regression suite for the parser and validator. It may already exist in this repo, or you may be asked to create it — either way, treat it as load-bearing.

- Before considering any change to `extraction/`, `validation/`, or `schemas/` complete, run the full test suite, including `test_golden.py`, and confirm it passes.
- **Never edit an existing golden fixture or its expected-output file to make a failing test pass.** A failing golden test means your code changed behavior — figure out whether that behavior change was intended. If it genuinely was intended (e.g., you were explicitly asked to change matching behavior), update the fixture deliberately and say so; don't silently adjust expected output to paper over a regression.
- When you add new extraction or matching logic, add a corresponding new golden fixture rather than only relying on unit tests — golden fixtures are the source of truth for end-to-end behavior.

---

## Coding conventions

**Python (backend):**
- Python 3.11+. Use **type hints on every function signature** (params and return type) — no exceptions for "small" helper functions.
- Use `dataclasses` or `pydantic` models for structured data (rubric entries, criterion results, the final validation response) — no bare dicts passed between modules as if they were structured types. `schemas/validation_result.py` should define the canonical types used everywhere else.
- Naming: `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants. JSON field names in API responses are `snake_case`, matching `SPEC.md` Section 3 exactly — do not camelCase anything in a response body.
- **Error handling:** raise specific, named exception classes (defined in `extraction/errors.py` for extraction failures, `validation/errors.py` for `InvalidApiKeyError` / `LLMServiceError`) — never raise bare `Exception` or catch bare `except:`. Route handlers catch these specific exceptions and translate them into the exact error envelope defined in `SPEC.md` Section 4.5 (`{"error": ..., "message": ..., ["reason": ...]}`). No stack traces or exception text — and no fragment of the Claude API key — ever reach the client directly.
- No print statements for debugging left in committed code — use the standard `logging` module, and remember PHI rule #2 and the LLM-API-key rules above apply to every log call.
- The Anthropic Python SDK (`anthropic`) is a new required dependency in `backend/requirements.txt` for `validation/llm_judge.py` — this is the one new dependency this change introduces; do not add others (no LangChain, no other LLM-orchestration framework) for what is a single structured-output API call.

**JavaScript/React (frontend):**
- Functional components with hooks only — no class components.
- `camelCase` for variables/functions, `PascalCase` for component names/files.
- API calls isolated in `src/api/client.js` — components never call `fetch` directly.
- Handle all documented error responses from `SPEC.md` Section 4.1 distinctly enough that the user sees a message matching the actual failure (wrong file type vs. too large vs. extraction failed vs. invalid API key vs. LLM service error vs. server error) — don't collapse them into one generic "something went wrong." `invalid_api_key` specifically should point the user back to `ApiKeyGate.jsx`, not just show a generic error.

**General:**
- Match `SPEC.md`'s JSON schemas and endpoint contracts exactly — field names, status codes, and error shapes are not stylistic choices you can adjust.
- Comment sparingly and only to explain *why*, not *what* — the code should be readable without a narration layer.

---

## When to ask instead of improvising

`SCOPE.md` and `SPEC.md` were written to close off ambiguity, but they don't cover everything. If you hit a decision that:

- isn't explicitly settled in `SPEC.md` or `SCOPE.md`, **and**
- would affect the API contract, the JSON response shape, the rubric file format, PHI handling behavior, or the overall architecture (new dependencies, new services, new persistence, new directories)

**stop and ask before proceeding.** Do not pick a reasonable-seeming default and move on, and do not silently expand scope to "make things more robust." Small, purely local implementation details (e.g., internal variable names, which specific `pypdf` call to use for a sub-step, how to structure a helper function inside an already-decided module) do not require asking — use your judgment there.

When you do ask, state the specific decision point, the options you see, and which option you'd lean toward and why — don't just ask an open-ended "how should I do this?"