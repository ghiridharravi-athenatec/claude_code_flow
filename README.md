# CDI Scorer -- Medical Record Validator

Upload a single medical record (PDF, TXT, or DOCX) and score it against the
fixed, weighted, narrative rubric in `backend/med_record_rubrics.json`. Each
dimension is scored by the Claude API using **your own** Anthropic API key,
which the app asks for in the browser before the upload step -- the key is
live-checked against the Claude API as soon as you enter it (a no-cost auth
check, SPEC.md Section 4.1.1), so a bad key is caught immediately rather than
after you've already picked a file. The server never holds or configures a
key of its own (SPEC.md Section 6). See `SCOPE.md` and `SPEC.md` for the
binding requirements this app implements.

## Backend (Flask)

```
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python -m spacy download en_core_web_lg
python app.py                 # runs on http://localhost:5000
```

Environment variables (see `config.py`): `ALLOWED_ORIGIN`, `MAX_FILE_SIZE_MB`, `RUBRIC_PATH`, `CLAUDE_MODEL`.
There is no `ANTHROPIC_API_KEY` variable -- by design, the server never holds
its own key; every `/validate` call supplies one (SPEC.md Section 6).

### Windows note: `python-magic` needs `libmagic`

`extraction/detect.py` uses `python-magic` for MIME sniffing, per SPEC.md
Section 1.1. `python-magic` wraps the native `libmagic` library, which
Windows doesn't ship. `requirements.txt` handles this with a platform
marker -- `pip install -r requirements.txt` installs `python-magic-bin`
(which bundles the libmagic DLL) on Windows and plain `python-magic`
everywhere else, so no extra step is needed.

### Running tests

```
cd backend
pip install -r requirements.txt
python -m spacy download en_core_web_lg   # only needed to exercise phi/redact.py
pytest
```

All 48 tests (`test_llm_judge.py`, `test_scorer.py`, `test_golden.py`,
`test_extraction.py`, `test_api.py`) were run against this exact codebase
during development and pass. `test_api.py` monkeypatches `magic.from_buffer` so it doesn't require
a real record's MIME type to be sniffed correctly by libmagic; the sniffing
logic itself is covered separately by inspection of `extraction/detect.py`
against SPEC.md Section 1.1. `test_llm_judge.py` and `test_golden.py` mock
the Claude API call (`validation.llm_judge.anthropic.Anthropic` /
`validation.scorer.judge_record`) -- no test makes a real network call or
needs a real Anthropic API key. None of the tests require the
`en_core_web_lg` spaCy model, since `phi/redact.py` is only exercised on the
unhandled-500 error path, which the test suite doesn't trigger.

## Frontend (React)

```
cd frontend
npm install
npm start                     # runs on http://localhost:3000
```

Set `REACT_APP_API_BASE_URL` in `frontend/.env` if the backend isn't on
`http://localhost:5000/api/v1`.
