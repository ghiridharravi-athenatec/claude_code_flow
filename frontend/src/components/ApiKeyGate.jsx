import { useState } from "react";

import { ApiError, validateApiKey } from "../api/client";

// Collects the user's own Claude API key, live-checks it against the Claude
// API (SPEC.md Section 4.1.1 -- a no-cost auth check, not a scoring call),
// and only then unblocks UploadForm (SPEC.md Section 6.1). The key is held
// only in this component's parent state for the current page session --
// never written to localStorage/sessionStorage/cookies (CLAUDE.md's LLM API
// key rules).
function ApiKeyGate({ onSubmit }) {
  const [value, setValue] = useState("");
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || isChecking) {
      return;
    }

    setIsChecking(true);
    setError(null);

    try {
      await validateApiKey(trimmed);
      onSubmit(trimmed);
    } catch (err) {
      if (err instanceof ApiError && err.error === "invalid_api_key") {
        setError("That API key was rejected by Claude. Please check it and try again.");
      } else if (err instanceof ApiError && err.error === "llm_service_error") {
        setError("Could not reach the Claude API to verify this key. Please try again.");
      } else {
        setError("Could not verify this key. Please try again.");
      }
    } finally {
      setIsChecking(false);
    }
  }

  return (
    <form className="api-key-gate" onSubmit={handleSubmit}>
      <label htmlFor="anthropic-api-key">Your Claude API key</label>
      <p className="api-key-hint">
        Checked live against the Claude API (no cost, no record content involved yet), then used only for this
        session -- never stored on the server or in your browser.
      </p>
      <input
        id="anthropic-api-key"
        type="password"
        autoComplete="off"
        placeholder="sk-ant-..."
        value={value}
        onChange={(event) => setValue(event.target.value)}
        disabled={isChecking}
      />
      {error && <p className="error-message">{error}</p>}
      <button type="submit" disabled={!value.trim() || isChecking}>
        {isChecking ? "Checking..." : "Continue"}
      </button>
    </form>
  );
}

export default ApiKeyGate;
