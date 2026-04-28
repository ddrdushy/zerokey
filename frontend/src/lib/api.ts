// Thin client for the ZeroKey API.
//
// SPA + Django session auth: we fetch /csrf/ on app boot to get the cookie,
// then forward it as `X-CSRFToken` on every unsafe request. Cookies are
// included via `credentials: "include"`.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");

  const csrf = readCookie("csrftoken");
  if (csrf && init.method && !["GET", "HEAD", "OPTIONS"].includes(init.method)) {
    headers.set("X-CSRFToken", csrf);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 204) return undefined as T;

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      (body && typeof body === "object" && "detail" in body && String(body.detail)) ||
      `HTTP ${response.status}`;
    throw new ApiError(message, response.status, body);
  }
  return body as T;
}

// --- Identity --------------------------------------------------------------

export type Membership = {
  id: string;
  organization: { id: string; legal_name: string; tin: string };
  role: string;
  joined_date: string;
};

export type Me = {
  id: string;
  email: string;
  preferred_language: string;
  preferred_timezone: string;
  two_factor_enabled: boolean;
  memberships: Membership[];
  active_organization_id: string | null;
};

export type IngestionJob = {
  id: string;
  source_channel: string;
  original_filename: string;
  file_size: number;
  file_mime_type: string;
  status: string;
  upload_timestamp: string;
  completed_at: string | null;
  error_message: string;
  download_url: string | null;
};

async function uploadFile(file: File): Promise<IngestionJob> {
  const headers = new Headers();
  const csrf = readCookie("csrftoken");
  if (csrf) headers.set("X-CSRFToken", csrf);

  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/ingestion/jobs/upload/`, {
    method: "POST",
    headers,
    credentials: "include",
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      (body && typeof body === "object" && "detail" in body && String(body.detail)) ||
      `HTTP ${response.status}`;
    throw new ApiError(message, response.status, body);
  }
  return body as IngestionJob;
}

export const api = {
  ensureCsrf: () => request<{ detail: string }>("/identity/csrf/"),
  me: () => request<Me>("/identity/me/"),
  login: (email: string, password: string) =>
    request<Me>("/identity/login/", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<void>("/identity/logout/", { method: "POST" }),
  register: (data: {
    email: string;
    password: string;
    organization_legal_name: string;
    organization_tin: string;
    contact_email: string;
  }) =>
    request<Me>("/identity/register/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listJobs: () =>
    request<{ results: IngestionJob[] }>("/ingestion/jobs/").then((r) => r.results),
  uploadFile,
};
