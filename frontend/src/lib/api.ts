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

export type LineItem = {
  id: string;
  line_number: number;
  description: string;
  unit_of_measurement: string;
  quantity: string | null;
  unit_price_excl_tax: string | null;
  line_subtotal_excl_tax: string | null;
  tax_type_code: string;
  tax_rate: string | null;
  tax_amount: string | null;
  line_total_incl_tax: string | null;
  classification_code: string;
};

export type ValidationIssue = {
  code: string;
  severity: "error" | "warning" | "info";
  field_path: string;
  message: string;
  detail: Record<string, unknown>;
};

export type ValidationSummary = {
  errors: number;
  warnings: number;
  infos: number;
  has_blocking_errors: boolean;
};

export type Invoice = {
  id: string;
  ingestion_job_id: string;
  status: string;
  invoice_number: string;
  issue_date: string | null;
  due_date: string | null;
  currency_code: string;
  supplier_legal_name: string;
  supplier_tin: string;
  supplier_address: string;
  buyer_legal_name: string;
  buyer_tin: string;
  buyer_address: string;
  subtotal: string | null;
  total_tax: string | null;
  grand_total: string | null;
  overall_confidence: number | null;
  per_field_confidence: Record<string, number>;
  structuring_engine: string;
  error_message: string;
  line_items: LineItem[];
  validation_issues: ValidationIssue[];
  validation_summary: ValidationSummary;
  created_at: string;
  updated_at: string;
};

export type AuditStats = {
  total: number;
  last_24h: number;
  last_7d: number;
  sparkline: Array<{ date: string; count: number }>;
};

export type ThroughputPoint = {
  date: string;
  day: string;
  validated: number;
  review: number;
};

export type Throughput = {
  series: ThroughputPoint[];
  totals: {
    validated: number;
    review: number;
    in_flight: number;
    failed: number;
    uploads: number;
  };
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
  extracted_text?: string;
  extraction_engine?: string;
  extraction_confidence?: number | null;
  state_transitions?: Array<{ status: string; at: string }>;
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
  getJob: (id: string) => request<IngestionJob>(`/ingestion/jobs/${id}/`),
  getInvoiceForJob: (jobId: string) => request<Invoice>(`/invoices/by-job/${jobId}/`),
  auditStats: () => request<AuditStats>("/audit/stats/"),
  throughput: (days = 7) => request<Throughput>(`/ingestion/throughput/?days=${days}`),
  uploadFile,
};
