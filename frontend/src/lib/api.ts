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

export type WebhookEndpointRow = {
  id: string;
  label: string;
  url: string;
  event_types: string[];
  secret_prefix: string;
  is_active: boolean;
  created_at: string | null;
  last_succeeded_at?: string | null;
  last_failed_at?: string | null;
  revoked_at?: string | null;
};

export type WebhookDeliveryRow = {
  id: string;
  endpoint_id: string;
  event_id: string;
  event_type: string;
  attempt: number;
  outcome: "pending" | "success" | "failure" | "retrying" | "abandoned";
  response_status: number | null;
  response_body_excerpt: string;
  error_class: string;
  duration_ms: number | null;
  queued_at: string | null;
  delivered_at: string | null;
  payload_excerpt: string;
};

export type BillingPlan = {
  id: string;
  slug: string;
  version: number;
  name: string;
  description: string;
  tier: string;
  monthly_price_cents: number;
  annual_price_cents: number;
  billing_currency: string;
  included_invoices_per_month: number;
  per_overage_cents: number;
  included_users: number;
  included_api_keys: number;
  features: Record<string, unknown>;
};

export type BillingSubscription = {
  id: string;
  status: "active" | "trialing" | "past_due" | "cancelled" | "replaced";
  billing_cycle: "monthly" | "annual";
  plan: BillingPlan;
  current_period_start: string | null;
  current_period_end: string | null;
  trial_started_at: string | null;
  trial_ends_at: string | null;
  cancel_at_period_end: boolean;
  cancelled_at: string | null;
  stripe_customer_id: string;
  stripe_subscription_id: string;
};

export type BillingUsage = {
  event_type: string;
  period_start: string | null;
  period_end: string | null;
  count: number;
  limit: number;
  overage_count: number;
};

export type NotificationPreferenceRow = {
  key: string;
  label: string;
  description: string;
  in_app: boolean;
  email: boolean;
};

export type APIKeyRow = {
  id: string;
  label: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string | null;
  created_by_user_id?: string | null;
  last_used_at?: string | null;
  revoked_at?: string | null;
};

export type OrganizationMemberRow = {
  id: string;
  user_id: string;
  email: string;
  role: string;
  is_active: boolean;
  joined_date: string | null;
};

export type IntegrationCard = {
  integration_key: string;
  label: string;
  description: string;
  fields: Array<{
    key: string;
    label: string;
    kind: "credential" | "config";
    placeholder?: string;
    required?: boolean;
  }>;
  active_environment: "sandbox" | "production";
  sandbox: {
    values: Record<string, string>;
    credential_present: Record<string, boolean>;
  };
  production: {
    values: Record<string, string>;
    credential_present: Record<string, boolean>;
  };
  last_test_sandbox: { at: string; ok: boolean; detail: string } | null;
  last_test_production: { at: string; ok: boolean; detail: string } | null;
  configured: boolean;
};

export type InvitationRow = {
  id: string;
  email: string;
  role: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  invited_by_email: string | null;
  expires_at: string | null;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
};

export type Membership = {
  id: string;
  organization: { id: string; legal_name: string; tin: string };
  role: string;
  joined_date: string;
};

export type ImpersonationContext = {
  session_id: string;
  organization_id: string;
  tenant_legal_name: string;
  started_at: string;
  expires_at: string;
  reason: string;
};

export type Me = {
  id: string;
  email: string;
  preferred_language: string;
  preferred_timezone: string;
  two_factor_enabled: boolean;
  is_staff: boolean;
  memberships: Membership[];
  active_organization_id: string | null;
  impersonation: ImpersonationContext | null;
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
  /** LHDN secondary-ID scheme (Slice 60+). */
  supplier_id_type: "" | "NRIC" | "PASSPORT" | "BRN" | "ARMY";
  supplier_id_value: string;
  buyer_legal_name: string;
  buyer_tin: string;
  buyer_address: string;
  buyer_id_type: "" | "NRIC" | "PASSPORT" | "BRN" | "ARMY";
  buyer_id_value: string;
  subtotal: string | null;
  total_tax: string | null;
  grand_total: string | null;
  overall_confidence: number | null;
  per_field_confidence: Record<string, number>;
  structuring_engine: string;
  /** Slice 58/59 LHDN submission state. */
  lhdn_uuid: string;
  lhdn_qr_code_url: string;
  validation_timestamp: string | null;
  cancellation_timestamp: string | null;
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

export type AdminMe = {
  id: string;
  email: string;
  is_staff: boolean;
  is_superuser: boolean;
};

export type SparklinePoint = { date: string; count: number };

export type PlatformOverview = {
  tenants: { total: number; active_last_7d: number };
  users: { total: number };
  ingestion: {
    total: number;
    last_7d: number;
    last_24h: number;
    sparkline: SparklinePoint[];
  };
  invoices: {
    total: number;
    last_7d: number;
    pending_review: number;
    sparkline: SparklinePoint[];
  };
  inbox: { open: number; sparkline: SparklinePoint[] };
  audit: { total: number; last_24h: number; sparkline: SparklinePoint[] };
  engines: {
    total: number;
    active: number;
    degraded: number;
    archived: number;
    calls_last_7d: Array<{
      engine: string;
      total: number;
      success: number;
      failure: number;
      unavailable: number;
    }>;
  };
};

export type SystemSettingFieldKind = "string" | "credential";

export type SystemSettingFieldSchema = {
  key: string;
  label: string;
  kind: SystemSettingFieldKind;
  placeholder?: string;
};

export type SystemSettingNamespace = {
  namespace: string;
  label: string;
  description: string;
  fields: SystemSettingFieldSchema[];
  values: Record<string, string>;
  credential_keys: Record<string, boolean>;
  updated_at: string | null;
};

export type AdminEngine = {
  id: string;
  name: string;
  vendor: string;
  model_identifier: string;
  adapter_version: string;
  capability: string;
  status: "active" | "degraded" | "archived";
  cost_per_call_micros: number;
  description: string;
  credential_keys: Record<string, boolean>;
  calls_last_7d?: number;
  calls_success_last_7d?: number;
  created_at?: string | null;
  updated_at: string | null;
};

export type TenantDetail = {
  id: string;
  legal_name: string;
  tin: string;
  contact_email: string;
  contact_phone: string;
  registered_address: string;
  subscription_state: string;
  trial_state: string;
  language_preference: string;
  timezone: string;
  billing_currency: string;
  certificate_uploaded: boolean;
  created_at: string | null;
  stats: {
    member_count: number;
    ingestion_jobs_total: number;
    ingestion_jobs_recent_7d: number;
    invoices_total: number;
    invoices_pending_review: number;
    inbox_open: number;
    audit_events: number;
  };
  inbox_open_by_reason: Record<string, number>;
  ingestion_sparkline: SparklinePoint[];
  members: Array<{
    id: string;
    user_id: string;
    email: string;
    role: string;
    is_active: boolean;
    joined_date: string | null;
  }>;
  recent_jobs: Array<{
    id: string;
    filename: string;
    mime_type: string;
    size_bytes: number;
    status: string;
    engine: string;
    confidence: number | null;
    source_channel: string;
    created_at: string | null;
  }>;
  recent_invoices: Array<{
    id: string;
    invoice_number: string;
    buyer_legal_name: string;
    status: string;
    currency_code: string;
    grand_total: string | null;
    created_at: string | null;
  }>;
};

export type PlatformTenant = {
  id: string;
  legal_name: string;
  tin: string;
  contact_email: string;
  subscription_state: string;
  created_at: string | null;
  member_count: number;
  ingestion_jobs_total: number;
  ingestion_jobs_recent_7d: number;
  last_activity_at: string | null;
};

export type PlatformAuditEvent = {
  id: string;
  sequence: number;
  timestamp: string;
  organization_id: string | null;
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

export type LatestVerification = {
  status: "ok" | "tampered" | "error";
  ok: boolean;
  events_verified: number;
  source: "scheduled" | "manual";
  started_at: string;
  completed_at: string | null;
  support_message: string;
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
  /** "ai_vision" (default) | "ocr_only" — Slice 54 extraction lane. */
  extraction_mode: "ai_vision" | "ocr_only";
  created_at: string;
  updated_at: string;
};

// Slice 73 — provenance entry per field. Source values mirror the
// Python enum in apps.enrichment.services. The UI degrades to a
// generic "extracted" pill on unknown sources so a future server
// adding a new source key doesn't break the rendering.
export type FieldProvenanceSource =
  | "extracted"
  | "manual"
  | "manually_resolved"
  | "synced_csv"
  | "synced_autocount"
  | "synced_sql_accounting"
  | "synced_xero"
  | "synced_quickbooks"
  | "synced_shopify"
  | "synced_woocommerce";

export type FieldProvenanceEntry = {
  source: FieldProvenanceSource | string;
  extracted_at?: string;
  invoice_id?: string;
  synced_at?: string;
  source_record_id?: string;
  applied_via_proposal_id?: string;
  approved_by?: string;
  entered_at?: string;
  edited_by?: string;
};

export type Customer = {
  id: string;
  legal_name: string;
  aliases: string[];
  tin: string;
  tin_verification_state:
    | "unverified"
    | "unverified_external_source"
    | "verified"
    | "failed"
    | "manually_resolved";
  tin_last_verified_at: string | null;
  registration_number: string;
  msic_code: string;
  address: string;
  phone: string;
  sst_number: string;
  country_code: string;
  field_provenance: Record<string, FieldProvenanceEntry>;
  locked_fields: string[];
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

// --- Connectors (Slice 73-77) ----------------------------------------------

export type ConnectorType =
  | "csv"
  | "sql_accounting"
  | "autocount"
  | "xero"
  | "quickbooks"
  | "shopify"
  | "woocommerce";

export type SyncStatus = "never" | "proposed" | "applied" | "failed" | "reverted";

export type IntegrationConfigRow = {
  id: string;
  connector_type: ConnectorType;
  sync_cadence: "manual" | "hourly" | "daily";
  auto_apply: boolean;
  last_sync_at: string | null;
  last_sync_status: SyncStatus;
  last_sync_error: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ProposalStatus = "proposed" | "applied" | "reverted" | "expired" | "cancelled";

export type SyncDiffEntry = {
  source_record_id?: string;
  fields?: Record<string, string>;
  existing_id?: string;
  changes?: Record<string, { current: string; proposed: string; verdict: string }>;
  field?: string;
  existing_value?: string;
  existing_provenance?: FieldProvenanceEntry;
  incoming_value?: string;
  incoming_provenance?: FieldProvenanceEntry;
};

export type SyncDiff = {
  customers: {
    would_add: SyncDiffEntry[];
    would_update: SyncDiffEntry[];
    conflicts: SyncDiffEntry[];
    skipped_locked: SyncDiffEntry[];
    skipped_verified: SyncDiffEntry[];
  };
  items: {
    would_add: SyncDiffEntry[];
    would_update: SyncDiffEntry[];
    conflicts: SyncDiffEntry[];
    skipped_locked: SyncDiffEntry[];
    skipped_verified: SyncDiffEntry[];
  };
};

export type SyncProposalRow = {
  id: string;
  integration_config: string;
  actor_user_id: string;
  status: ProposalStatus;
  proposed_at: string;
  expires_at: string;
  applied_at: string | null;
  applied_by_user_id: string | null;
  reverted_at: string | null;
  reverted_by_user_id: string | null;
  diff: SyncDiff;
};

export type ConflictResolution =
  | "keep_existing"
  | "take_incoming"
  | "keep_both_as_aliases"
  | "enter_custom_value";

export type MasterFieldConflictRow = {
  id: string;
  sync_proposal: string;
  master_type: "customer" | "item";
  master_id: string;
  field_name: string;
  existing_value: string;
  existing_provenance: FieldProvenanceEntry;
  incoming_value: string;
  incoming_provenance: FieldProvenanceEntry;
  resolution: ConflictResolution | "";
  custom_value: string;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  is_open: boolean;
};

export type MasterFieldLockRow = {
  id: string;
  master_type: "customer" | "item";
  master_id: string;
  field_name: string;
  locked_by_user_id: string;
  locked_at: string;
  reason: string;
};

async function uploadCsvSync(args: {
  configId: string;
  file: File;
  columnMapping: Record<string, string>;
  target?: "customers" | "items";
}): Promise<SyncProposalRow> {
  const headers = new Headers();
  const csrf = readCookie("csrftoken");
  if (csrf) headers.set("X-CSRFToken", csrf);

  const form = new FormData();
  form.append("file", args.file);
  form.append("column_mapping", JSON.stringify(args.columnMapping));
  form.append("target", args.target ?? "customers");

  const response = await fetch(`${API_BASE}/connectors/configs/${args.configId}/sync-csv/`, {
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
  return body as SyncProposalRow;
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
  listJobs: () => request<{ results: IngestionJob[] }>("/ingestion/jobs/").then((r) => r.results),
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
    if (params?.beforeCreatedAt) search.set("before_created_at", params.beforeCreatedAt);
    const qs = search.toString();
    return request<InvoiceListResponse>(`/invoices/${qs ? `?${qs}` : ""}`);
  },
  auditStats: () => request<AuditStats>("/audit/stats/"),
  listAuditEvents: (params?: { actionType?: string; limit?: number; beforeSequence?: number }) => {
    const search = new URLSearchParams();
    if (params?.actionType) search.set("action_type", params.actionType);
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.beforeSequence !== undefined)
      search.set("before_sequence", String(params.beforeSequence));
    const qs = search.toString();
    return request<AuditEventListResponse>(`/audit/events/${qs ? `?${qs}` : ""}`);
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
  latestAuditVerification: () =>
    request<{ latest: LatestVerification | null }>("/audit/verify/last/").then((r) => r.latest),
  adminMe: () => request<AdminMe>("/admin/me/"),
  adminOverview: () => request<PlatformOverview>("/admin/overview/"),
  adminListPlatformAuditEvents: (params?: {
    actionType?: string;
    organizationId?: string;
    limit?: number;
    beforeSequence?: number;
  }) => {
    const search = new URLSearchParams();
    if (params?.actionType) search.set("action_type", params.actionType);
    if (params?.organizationId) search.set("organization_id", params.organizationId);
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.beforeSequence !== undefined)
      search.set("before_sequence", String(params.beforeSequence));
    const qs = search.toString();
    return request<{ results: PlatformAuditEvent[]; total: number }>(
      `/admin/audit/events/${qs ? `?${qs}` : ""}`,
    );
  },
  adminListPlatformActionTypes: () =>
    request<{ results: string[] }>("/admin/audit/action-types/").then((r) => r.results),
  adminListEngines: () =>
    request<{ results: AdminEngine[] }>("/admin/engines/").then((r) => r.results),
  adminListSystemSettings: () =>
    request<{ results: SystemSettingNamespace[] }>("/admin/system-settings/").then(
      (r) => r.results,
    ),
  adminUpdateSystemSetting: (
    namespace: string,
    body: { fields: Record<string, string>; reason: string },
  ) =>
    request<SystemSettingNamespace>(`/admin/system-settings/${namespace}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminTestEmail: (to: string) =>
    request<{ ok: boolean; detail: string; duration_ms: number }>(
      "/admin/system-settings/email/test/",
      { method: "POST", body: JSON.stringify({ to }) },
    ),
  adminUpdateEngine: (
    engineId: string,
    body: {
      fields?: Partial<{
        status: string;
        model_identifier: string;
        cost_per_call_micros: number;
        description: string;
      }>;
      credentials?: Record<string, string>;
    },
  ) =>
    request<AdminEngine>(`/admin/engines/${engineId}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminTenantDetail: (organizationId: string) =>
    request<TenantDetail>(`/admin/tenants/${organizationId}/`),
  adminUpdateTenant: (
    organizationId: string,
    body: {
      fields: Partial<{
        legal_name: string;
        contact_email: string;
        contact_phone: string;
        registered_address: string;
        language_preference: string;
        timezone: string;
        billing_currency: string;
        subscription_state: string;
        trial_state: string;
      }>;
      reason: string;
    },
  ) =>
    request<TenantDetail>(`/admin/tenants/${organizationId}/edit/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminStartImpersonation: (organizationId: string, reason: string) =>
    request<{
      session_id: string;
      organization_id: string;
      started_at: string;
      expires_at: string;
      redirect_to: string;
    }>(`/admin/tenants/${organizationId}/impersonate/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  adminEndImpersonation: () =>
    request<{ redirect_to: string }>("/admin/impersonation/end/", {
      method: "POST",
    }),
  adminUpdateMembership: (
    membershipId: string,
    body: { is_active?: boolean; role_name?: string; reason: string },
  ) =>
    request<{
      id: string;
      user_id: string;
      organization_id: string;
      role: string;
      is_active: boolean;
    }>(`/admin/memberships/${membershipId}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminListTenants: (params?: { search?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    const search = qs.toString();
    return request<{ results: PlatformTenant[] }>(
      `/admin/tenants/${search ? `?${search}` : ""}`,
    ).then((r) => r.results);
  },
  getOrganization: () => request<OrganizationDetail>("/identity/organization/"),
  listOrganizationMembers: () =>
    request<{ results: OrganizationMemberRow[] }>("/identity/organization/members/").then(
      (r) => r.results,
    ),
  patchOrganizationMember: (
    membershipId: string,
    body: { is_active?: boolean; role_name?: string },
  ) =>
    request<OrganizationMemberRow>(`/identity/organization/members/${membershipId}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  // Slice 56 — invitations
  listInvitations: () =>
    request<{ results: InvitationRow[] }>("/identity/organization/invitations/").then(
      (r) => r.results,
    ),
  createInvitation: (email: string, roleName: string) =>
    request<InvitationRow & { plaintext_token: string; invitation_url: string }>(
      "/identity/organization/invitations/",
      {
        method: "POST",
        body: JSON.stringify({ email, role_name: roleName }),
      },
    ),
  revokeInvitation: (invitationId: string) =>
    request<InvitationRow>(`/identity/organization/invitations/${invitationId}/`, {
      method: "DELETE",
    }),
  previewInvitation: (token: string) =>
    request<{
      email: string;
      role: string;
      organization_legal_name: string;
      expires_at: string;
    }>("/identity/invitations/preview/", { method: "POST", body: JSON.stringify({ token }) }),
  acceptInvitation: (token: string) =>
    request<{
      membership_id: string;
      organization_id: string;
      role: string;
      redirect_to: string;
    }>("/identity/invitations/accept/", { method: "POST", body: JSON.stringify({ token }) }),
  // Slice 57 — per-org integrations
  listIntegrations: () =>
    request<{ results: IntegrationCard[] }>("/identity/organization/integrations/").then(
      (r) => r.results,
    ),
  patchIntegrationCredentials: (
    integrationKey: string,
    environment: "sandbox" | "production",
    fields: Record<string, string>,
  ) =>
    request<IntegrationCard>(`/identity/organization/integrations/${integrationKey}/credentials/`, {
      method: "PATCH",
      body: JSON.stringify({ environment, fields }),
    }),
  switchIntegrationEnvironment: (
    integrationKey: string,
    environment: "sandbox" | "production",
    reason?: string,
  ) =>
    request<IntegrationCard>(
      `/identity/organization/integrations/${integrationKey}/active-environment/`,
      {
        method: "PATCH",
        body: JSON.stringify({ environment, reason: reason || "" }),
      },
    ),
  testIntegration: (integrationKey: string, environment: "sandbox" | "production") =>
    request<{ ok: boolean; detail: string; duration_ms: number }>(
      `/identity/organization/integrations/${integrationKey}/test/`,
      {
        method: "POST",
        body: JSON.stringify({ environment }),
      },
    ),
  // Slice 59B — LHDN signing certificate
  getCertificate: () =>
    request<{
      uploaded: boolean;
      kind: string;
      subject_common_name: string;
      serial_hex: string;
      expires_at: string | null;
    }>("/identity/organization/certificate/"),
  uploadCertificate: (cert_pem: string, private_key_pem: string) =>
    request<{
      uploaded: boolean;
      kind: string;
      subject_common_name: string;
      serial_hex: string;
      expires_at: string;
    }>("/identity/organization/certificate/", {
      method: "POST",
      body: JSON.stringify({ cert_pem, private_key_pem }),
    }),
  // Slice 68 — PFX/P12 cert upload (single bundle from CA).
  uploadCertificatePfx: (pfx_b64: string, pfx_password: string) =>
    request<{
      uploaded: boolean;
      kind: string;
      subject_common_name: string;
      serial_hex: string;
      expires_at: string;
    }>("/identity/organization/certificate/", {
      method: "POST",
      body: JSON.stringify({ pfx_b64, pfx_password }),
    }),
  // Slice 59B — LHDN lifecycle gestures on an invoice
  submitInvoiceToLhdn: (invoiceId: string) =>
    request<{
      ok: boolean;
      reason: string;
      submission_uid: string;
      invoice: Invoice;
    }>(`/invoices/${invoiceId}/submit-to-lhdn/`, { method: "POST" }),
  cancelInvoiceLhdn: (invoiceId: string, reason: string) =>
    request<{
      ok: boolean;
      reason: string;
      code: string;
      invoice: Invoice;
    }>(`/invoices/${invoiceId}/cancel-lhdn/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  pollInvoiceLhdn: (invoiceId: string) =>
    request<{
      ok: boolean;
      reason: string;
      document_status: string;
      lhdn_uuid: string;
      invoice: Invoice;
    }>(`/invoices/${invoiceId}/poll-lhdn/`, { method: "POST" }),
  // Slice 61 — issue a credit note against a Validated invoice.
  issueCreditNote: (invoiceId: string, reason: string) =>
    request<{
      credit_note_id: string;
      credit_note_number: string;
      ingestion_job_id: string;
      invoice: Invoice;
    }>(`/invoices/${invoiceId}/issue-credit-note/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  // Slice 62 — DN + RN follow the same shape, different LHDN type code.
  issueDebitNote: (invoiceId: string, reason: string) =>
    request<{
      debit_note_id: string;
      debit_note_number: string;
      ingestion_job_id: string;
      invoice: Invoice;
    }>(`/invoices/${invoiceId}/issue-debit-note/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  issueRefundNote: (invoiceId: string, reason: string) =>
    request<{
      refund_note_id: string;
      refund_note_number: string;
      ingestion_job_id: string;
      invoice: Invoice;
    }>(`/invoices/${invoiceId}/issue-refund-note/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  listApiKeys: () =>
    request<{ results: APIKeyRow[] }>("/identity/organization/api-keys/").then((r) => r.results),
  createApiKey: (label: string) =>
    request<APIKeyRow & { plaintext: string }>("/identity/organization/api-keys/", {
      method: "POST",
      body: JSON.stringify({ label }),
    }),
  revokeApiKey: (apiKeyId: string) =>
    request<APIKeyRow>(`/identity/organization/api-keys/${apiKeyId}/`, { method: "DELETE" }),
  getNotificationPreferences: () =>
    request<{ events: NotificationPreferenceRow[] }>(
      "/identity/organization/notification-preferences/",
    ),
  setNotificationPreferences: (updates: Record<string, { in_app?: boolean; email?: boolean }>) =>
    request<{ events: NotificationPreferenceRow[] }>(
      "/identity/organization/notification-preferences/",
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  getBillingOverview: () =>
    request<{
      subscription: BillingSubscription | null;
      usage: BillingUsage;
      available_plans: BillingPlan[];
    }>("/billing/overview/"),
  // Slice 65 — Stripe checkout + inbound email address
  startCheckout: (body: {
    plan_id: string;
    billing_cycle: "monthly" | "annual";
    success_url: string;
    cancel_url: string;
  }) =>
    request<{
      checkout_url: string;
      session_id: string;
      stripe_customer_id: string;
    }>("/billing/checkout/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getInboxAddress: () => request<{ address: string }>("/ingestion/inbox/address/"),
  rotateInboxToken: (reason: string) =>
    request<{ address: string }>("/ingestion/inbox/rotate-token/", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  listWebhooks: () =>
    request<{
      results: WebhookEndpointRow[];
      available_events: { key: string; label: string }[];
    }>("/integrations/webhooks/"),
  createWebhook: (body: { label: string; url: string; event_types: string[] }) =>
    request<WebhookEndpointRow & { plaintext_secret: string }>("/integrations/webhooks/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  revokeWebhook: (webhookId: string) =>
    request<WebhookEndpointRow>(`/integrations/webhooks/${webhookId}/`, {
      method: "DELETE",
    }),
  testWebhook: (webhookId: string) =>
    request<WebhookDeliveryRow>(`/integrations/webhooks/${webhookId}/test/`, { method: "POST" }),
  listWebhookDeliveries: (params?: { webhookId?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.webhookId) qs.set("webhook_id", params.webhookId);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    const search = qs.toString();
    return request<{ results: WebhookDeliveryRow[] }>(
      `/integrations/deliveries/${search ? `?${search}` : ""}`,
    );
  },
  updateOrganization: (updates: Partial<Record<keyof OrganizationDetail, string>>) =>
    request<OrganizationDetail>("/identity/organization/", {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  engineSummary: () => request<{ results: EngineSummary[] }>("/engines/").then((r) => r.results),
  listEngineCalls: (params?: { limit?: number; beforeStartedAt?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.beforeStartedAt) search.set("before_started_at", params.beforeStartedAt);
    const qs = search.toString();
    return request<{ results: EngineCallRecord[] }>(`/engines/calls/${qs ? `?${qs}` : ""}`).then(
      (r) => r.results,
    );
  },
  throughput: (days = 7) => request<Throughput>(`/ingestion/throughput/?days=${days}`),
  updateInvoice: (id: string, updates: Record<string, string | null>) =>
    request<Invoice>(`/invoices/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  listCustomers: () => request<{ results: Customer[] }>("/customers/").then((r) => r.results),
  getCustomer: (id: string) => request<Customer>(`/customers/${id}/`),
  updateCustomer: (id: string, updates: Partial<Record<keyof Customer, string>>) =>
    request<Customer>(`/customers/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  listCustomerInvoices: (id: string) =>
    request<{ results: CustomerInvoiceSummary[] }>(`/customers/${id}/invoices/`).then(
      (r) => r.results,
    ),
  uploadFile,
  // Connectors (Slices 73–77)
  listConnectorConfigs: () =>
    request<{ results: IntegrationConfigRow[] }>("/connectors/configs/").then((r) => r.results),
  createConnectorConfig: (connector_type: ConnectorType) =>
    request<IntegrationConfigRow>("/connectors/configs/", {
      method: "POST",
      body: JSON.stringify({ connector_type }),
    }),
  deleteConnectorConfig: (id: string) =>
    request<IntegrationConfigRow>(`/connectors/configs/${id}/`, {
      method: "DELETE",
    }),
  uploadCsvSync,
  getProposal: (id: string) => request<SyncProposalRow>(`/connectors/proposals/${id}/`),
  applyProposal: (id: string) =>
    request<SyncProposalRow>(`/connectors/proposals/${id}/apply/`, {
      method: "POST",
    }),
  revertProposal: (id: string, reason: string) =>
    request<SyncProposalRow>(`/connectors/proposals/${id}/revert/`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  listConflicts: (state: "open" | "resolved" | "all" = "open") =>
    request<{ results: MasterFieldConflictRow[] }>(`/connectors/conflicts/?state=${state}`).then(
      (r) => r.results,
    ),
  resolveConflict: (id: string, body: { resolution: ConflictResolution; custom_value?: string }) =>
    request<MasterFieldConflictRow>(`/connectors/conflicts/${id}/resolve/`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  lockMasterField: (body: {
    master_type: "customer" | "item";
    master_id: string;
    field_name: string;
    reason?: string;
  }) =>
    request<MasterFieldLockRow>("/connectors/locks/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  unlockMasterField: (body: {
    master_type: "customer" | "item";
    master_id: string;
    field_name: string;
  }) =>
    request<{ removed: boolean }>("/connectors/locks/unlock/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
