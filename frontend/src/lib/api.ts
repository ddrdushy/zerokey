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

export type EngineSummary = {
  engine_name: string;
  vendor: string;
  capability: string;
  total_calls: number;
  success_count: number;
  failure_count: number;
  timeout_count: number;
  unavailable_count: number;
  success_rate: number;
  avg_duration_ms: number;
  total_cost_micros: number;
};

export type EngineCallRecord = {
  id: string;
  engine_name: string;
  vendor: string;
  request_id: string | null;
  started_at: string;
  duration_ms: number;
  outcome: "success" | "failure" | "timeout" | "unavailable";
  error_class: string;
  cost_micros: number;
  confidence: number | null;
  diagnostics: Record<string, unknown>;
};

export type AuditEvent = {
  id: string;
  sequence: number;
  timestamp: string;
  actor_type: string;
  actor_id: string;
  action_type: string;
  affected_entity_type: string;
  affected_entity_id: string;
  payload: Record<string, unknown>;
  payload_schema_version: number;
  content_hash: string;
  chain_hash: string;
};

export type AuditEventListResponse = {
  results: AuditEvent[];
  total: number;
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

export type CustomerInvoiceSummary = {
  id: string;
  ingestion_job_id: string;
  invoice_number: string;
  issue_date: string | null;
  currency_code: string;
  grand_total: string | null;
  status: string;
  created_at: string;
};

export type OrganizationDetail = {
  id: string;
  legal_name: string;
  tin: string;
  sst_number: string;
  registered_address: string;
  contact_email: string;
  contact_phone: string;
  billing_currency: string;
  trial_state: string;
  subscription_state: string;
  certificate_uploaded: boolean;
  certificate_expiry_date: string | null;
  logo_url: string;
  language_preference: string;
  timezone: string;
  created_at: string;
  updated_at: string;
};

export type Customer = {
  id: string;
  legal_name: string;
  aliases: string[];
  tin: string;
  tin_verification_state: "unverified" | "verified" | "failed";
  tin_last_verified_at: string | null;
  registration_number: string;
  msic_code: string;
  address: string;
  phone: string;
  sst_number: string;
  country_code: string;
  usage_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};

export type InboxItem = {
  id: string;
  reason:
    | "validation_failure"
    | "structuring_skipped"
    | "low_confidence_extraction"
    | "lhdn_rejection"
    | "manual_review_requested";
  priority: "normal" | "urgent";
  status: "open" | "resolved";
  detail: Record<string, unknown>;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  resolution_note: string;
  created_at: string;
  updated_at: string;
  invoice_id: string;
  ingestion_job_id: string;
  invoice_number: string;
  invoice_status: string;
  buyer_legal_name: string;
};

export type InboxListResponse = {
  results: InboxItem[];
  total: number;
};

export type InvoiceListSummary = {
  id: string;
  ingestion_job_id: string;
  invoice_number: string;
  issue_date: string | null;
  currency_code: string;
  grand_total: string | null;
  buyer_legal_name: string;
  buyer_tin: string;
  status: string;
  created_at: string;
};

export type InvoiceListResponse = {
  results: InvoiceListSummary[];
  total: number;
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
  listInbox: (params?: { reason?: string; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.reason) search.set("reason", params.reason);
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    const qs = search.toString();
    return request<InboxListResponse>(`/inbox/${qs ? `?${qs}` : ""}`);
  },
  resolveInboxItem: (id: string, note?: string) =>
    request<InboxItem>(`/inbox/${id}/resolve/`, {
      method: "POST",
      body: JSON.stringify(note ? { note } : {}),
    }),
  listInvoices: (params?: {
    status?: string;
    search?: string;
    limit?: number;
    beforeCreatedAt?: string;
  }) => {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.search) search.set("search", params.search);
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.beforeCreatedAt)
      search.set("before_created_at", params.beforeCreatedAt);
    const qs = search.toString();
    return request<InvoiceListResponse>(`/invoices/${qs ? `?${qs}` : ""}`);
  },
  auditStats: () => request<AuditStats>("/audit/stats/"),
  listAuditEvents: (params?: {
    actionType?: string;
    limit?: number;
    beforeSequence?: number;
  }) => {
    const search = new URLSearchParams();
    if (params?.actionType) search.set("action_type", params.actionType);
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.beforeSequence !== undefined)
      search.set("before_sequence", String(params.beforeSequence));
    const qs = search.toString();
    return request<AuditEventListResponse>(
      `/audit/events/${qs ? `?${qs}` : ""}`,
    );
  },
  listAuditActionTypes: () =>
    request<{ results: string[] }>("/audit/action-types/").then((r) => r.results),
  verifyAuditChain: () =>
    request<{
      ok: boolean;
      events_verified: number;
      tampering_detected: boolean;
      support_message: string;
    }>("/audit/verify/", { method: "POST" }),
  getOrganization: () =>
    request<OrganizationDetail>("/identity/organization/"),
  updateOrganization: (updates: Partial<Record<keyof OrganizationDetail, string>>) =>
    request<OrganizationDetail>("/identity/organization/", {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  engineSummary: () =>
    request<{ results: EngineSummary[] }>("/engines/").then((r) => r.results),
  listEngineCalls: (params?: { limit?: number; beforeStartedAt?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.beforeStartedAt)
      search.set("before_started_at", params.beforeStartedAt);
    const qs = search.toString();
    return request<{ results: EngineCallRecord[] }>(
      `/engines/calls/${qs ? `?${qs}` : ""}`,
    ).then((r) => r.results);
  },
  throughput: (days = 7) => request<Throughput>(`/ingestion/throughput/?days=${days}`),
  updateInvoice: (id: string, updates: Record<string, string | null>) =>
    request<Invoice>(`/invoices/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  listCustomers: () =>
    request<{ results: Customer[] }>("/customers/").then((r) => r.results),
  getCustomer: (id: string) => request<Customer>(`/customers/${id}/`),
  updateCustomer: (id: string, updates: Partial<Record<keyof Customer, string>>) =>
    request<Customer>(`/customers/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  listCustomerInvoices: (id: string) =>
    request<{ results: CustomerInvoiceSummary[] }>(
      `/customers/${id}/invoices/`,
    ).then((r) => r.results),
  uploadFile,
};
