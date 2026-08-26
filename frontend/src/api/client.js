// All fetch calls to the backend live here -- components never call fetch directly.

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || "http://localhost:5000/api/v1";

class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || "Request failed");
    this.status = status;
    this.error = body?.error;
    this.reason = body?.reason;
  }
}

async function parseJsonOrThrow(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    throw new ApiError(response.status, body);
  }

  return body;
}

export async function checkHealth() {
  const response = await fetch(`${API_BASE_URL}/health`);
  return parseJsonOrThrow(response);
}

export async function getActiveRubric() {
  const response = await fetch(`${API_BASE_URL}/rubrics`);
  return parseJsonOrThrow(response);
}

export async function validateApiKey(apiKey) {
  const response = await fetch(`${API_BASE_URL}/api-key/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ anthropic_api_key: apiKey }),
  });

  return parseJsonOrThrow(response);
}

export async function validateRecord(file, apiKey) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("anthropic_api_key", apiKey);

  const response = await fetch(`${API_BASE_URL}/validate`, {
    method: "POST",
    body: formData,
  });

  return parseJsonOrThrow(response);
}

export { ApiError };
