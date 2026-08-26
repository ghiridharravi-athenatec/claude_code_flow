import { useEffect, useState } from "react";

import { ApiError, getActiveRubric, validateRecord } from "./api/client";
import ApiKeyGate from "./components/ApiKeyGate";
import CriteriaList from "./components/CriteriaList";
import GapsList from "./components/GapsList";
import ResultsSummary from "./components/ResultsSummary";
import RubricSelector from "./components/RubricSelector";
import UploadForm from "./components/UploadForm";
import "./styles/App.css";

const EXTRACTION_FAILURE_REASONS = {
  corrupted: "The file appears to be corrupted and could not be read.",
  password_protected: "The file is password-protected. Remove the password and try again.",
  empty_content: "No readable text could be found in this file (it may be a scanned image).",
  decode_error: "The file's text encoding could not be read.",
};

function describeError(err) {
  if (!(err instanceof ApiError)) {
    return "Could not reach the server. Please try again.";
  }

  switch (err.error) {
    case "missing_field":
      return "Please choose a file to upload.";
    case "missing_api_key":
      return "Please enter your Claude API key.";
    case "unsupported_file_type":
      return "Unsupported file type. Please upload a PDF, TXT, or DOCX file.";
    case "file_too_large":
      return "This file is too large. The maximum size is 10 MB.";
    case "extraction_failed":
      return EXTRACTION_FAILURE_REASONS[err.reason] || err.message;
    case "invalid_api_key":
      return "Your Claude API key was rejected. Please re-enter it.";
    case "llm_service_error":
      return "The Claude API call failed. Please try again in a moment.";
    case "internal_error":
      return "Something went wrong on the server. Please try again.";
    default:
      return err.message || "Something went wrong.";
  }
}

function App() {
  const [apiKey, setApiKey] = useState(null);
  const [rubric, setRubric] = useState(null);
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    getActiveRubric()
      .then(setRubric)
      .catch(() => setRubric(null));
  }, []);

  async function handleSubmit(file) {
    setIsSubmitting(true);
    setErrorMessage(null);
    setResult(null);

    try {
      const validationResult = await validateRecord(file, apiKey);
      setResult(validationResult);
    } catch (err) {
      setErrorMessage(describeError(err));
      // An invalid_api_key error sends the user back to the key-entry step
      // rather than leaving a broken key silently reused on the next try.
      if (err instanceof ApiError && err.error === "invalid_api_key") {
        setApiKey(null);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!apiKey) {
    return (
      <div className="app">
        <header>
          <h1>CDI Scorer</h1>
          <p>Medical Record Validator</p>
        </header>
        <ApiKeyGate onSubmit={setApiKey} />
        {errorMessage && <p className="error-message">{errorMessage}</p>}
      </div>
    );
  }

  return (
    <div className="app">
      <header>
        <h1>CDI Scorer</h1>
        <p>Medical Record Validator</p>
      </header>

      <RubricSelector rubric={rubric} />

      <button type="button" className="change-key-link" onClick={() => setApiKey(null)}>
        Use a different API key
      </button>

      <UploadForm onSubmit={handleSubmit} isSubmitting={isSubmitting} />

      {errorMessage && <p className="error-message">{errorMessage}</p>}

      {result && (
        <section className="results">
          <ResultsSummary result={result} />
          <GapsList flaggedGaps={result.flagged_gaps} />
          <CriteriaList dimensionResults={result.dimension_results} />
        </section>
      )}
    </div>
  );
}

export default App;
