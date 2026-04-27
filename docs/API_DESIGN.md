# API DESIGN — ZeroKey

> The contract between ZeroKey and any system that talks to it programmatically. This document specifies the REST API conventions, authentication, versioning, error shapes, webhook delivery, and the discipline that keeps the API a first-class product surface rather than an afterthought.

## API as a product

ZeroKey's API is a product, not an implementation detail. It is the primary surface for two of our six personas (Wei Lun the finance manager evaluating integrations, and Ravi the technical integrator), and it is the long-term path through which platforms, accounting systems, and enterprise integrations connect to us. A poorly designed API is not just a technical inconvenience; it is a strategic failure that blocks the most leveraged distribution channels.

This document is therefore written with the same care as the customer-facing UX documentation. The conventions here are the equivalent of UX principles for the developer audience.

## Foundational principles

Five principles govern API design, in precedence order.

The first principle is **predictability over cleverness**. A developer reading our API documentation should be able to predict the shape of any endpoint they have not yet read. Every list endpoint paginates the same way. Every resource has the same identifier conventions. Every error has the same structure. Cleverness in API design is paid for in confused developers; predictability is paid for once at design time.

The second principle is **stability is non-negotiable**. The API contract is a promise. Once a public endpoint exists, breaking it requires a major version bump and a deprecation cycle, never a silent change. Internal endpoints that are consumed only by our own frontend can evolve more freely, but the public API is fixed.

The third principle is **errors are first-class**. Every error response is structured, machine-parseable, and includes both a stable error code and a human-readable explanation. A developer should be able to programmatically distinguish between "rate limited, retry later" and "permanent rejection, do not retry" without parsing prose.

The fourth principle is **idempotency is mandatory for mutations**. Any mutating operation can be safely retried without producing duplicate effects. This is enforced through idempotency keys, request deduplication windows, and careful state-machine design. Network failures must not result in duplicate invoices submitted to LHDN.

The fifth principle is **observability extends to the API**. Every API call is logged with the request ID, the API key or user identity, the endpoint, the response code, and the latency. Customers can see their own API usage in the dashboard. We can see aggregate API health at all times.

## API surface

The public API is exposed at `https://api.zerokey.symprio.com/v1/`. The version segment in the path is the major version; minor and patch versions are tracked in the API documentation but do not require URL changes.

The internal API used by our own Next.js frontend is exposed at `https://app.zerokey.symprio.com/api/`. This is not versioned in the URL because the frontend and backend deploy together; backwards compatibility is preserved within a single deployment but not across deployments. The internal API is not documented for external use.

Authentication on the public API uses API keys passed in the `Authorization` header as `Bearer <key>`. API keys are scoped to a specific Organization and a specific permission set, are rotatable, and are revocable.

Authentication on the internal API uses session cookies set by the Django authentication system on login.

Both authentication paths funnel into the same authorization layer, where the user's role and permissions are evaluated against the requested operation.

## Resource conventions

Every API resource follows the same conventions.

**Identifiers** are opaque strings, not integers. They are prefixed by the resource type, an underscore, and a generated portion: `org_xyzABC123`, `inv_abc456DEF`, `cust_pqr789GHI`. The prefix makes it obvious what kind of resource an identifier refers to. Identifiers are URL-safe.

**Timestamps** are ISO 8601 strings in UTC with millisecond precision: `2026-04-28T10:23:45.123Z`. Customer-facing display is in their configured timezone, but the API always speaks UTC.

**Money** is represented as a decimal string with the currency code in a sibling field. We never use floating-point numbers for currency. An invoice grand total is `{"amount": "1234.56", "currency": "MYR"}` — never `1234.56` as a number.

**Pagination** uses cursor-based pagination, not offset. List responses include `data`, `next_cursor` (or `null` when at end), and `has_more` (boolean). Clients pass `?cursor=<value>` to fetch the next page. Cursor pagination scales correctly under heavy use; offset pagination falls apart at large datasets.

**Filtering** is done via query parameters with consistent naming: `created_after`, `created_before`, `status`, etc. Filter parameters are documented per endpoint.

**Sorting** is done via a `sort` query parameter with field and direction: `?sort=created_at:desc`. Multiple sort fields are comma-separated.

**Field selection** is supported on list endpoints via `?fields=` to reduce payload size when the client only needs specific fields.

## Standard endpoints

The following endpoint patterns appear consistently across resources.

**Create** is `POST /v1/<resource_type>` with the resource attributes in the JSON body. Returns the created resource with its assigned identifier and a `201 Created` status.

**Retrieve** is `GET /v1/<resource_type>/<id>` returning the resource with a `200 OK` status, or `404 Not Found` if the identifier does not exist or is not visible to the caller.

**List** is `GET /v1/<resource_type>` with query parameters for filtering, pagination, and sorting. Returns a paginated list with a `200 OK` status.

**Update** is `PATCH /v1/<resource_type>/<id>` with the partial attributes to update in the JSON body. Returns the updated resource. We use PATCH consistently rather than PUT; whole-resource replacement is rarely the right semantic.

**Delete** is `DELETE /v1/<resource_type>/<id>` returning a `204 No Content` on success. Deletes are typically soft (marking inactive) rather than hard (physical row removal); the response semantics are the same regardless.

**Custom actions** that do not fit CRUD shape use `POST /v1/<resource_type>/<id>/<action>`, such as `POST /v1/invoices/inv_abc/submit` for explicit submission. Custom actions are documented as named operations.

## Resource catalog

The public API exposes the following resource types in v1.

The **Invoice** resource is the central resource. Endpoints support creating an invoice (which kicks off the extraction or accepts already-structured data), retrieving an invoice with all line items and current state, listing invoices with filters for status, date range, buyer, and amount, updating an invoice's draft fields before submission, submitting an invoice to LHDN, cancelling a validated invoice within the LHDN seventy-two-hour window, and issuing a credit note or debit note referencing the invoice.

The **CustomerMaster** resource exposes the customer's accumulated buyer records. Endpoints support listing, retrieving, creating, updating, and merging duplicate buyer records.

The **ItemMaster** resource exposes the customer's accumulated item records with the same operations.

The **IngestionJob** resource exposes the raw upload-and-extraction lifecycle. Endpoints support creating an upload (returning a job ID and a presigned upload URL), retrieving a job's current status, listing jobs, and cancelling an in-flight job. The relationship between IngestionJob and Invoice is that an IngestionJob produces one or more Invoice resources once extraction completes.

The **Webhook** resource manages the customer's webhook endpoints. Endpoints support creating a webhook subscription, listing active subscriptions, updating a subscription's URL or event filter, and deleting a subscription. Detailed webhook semantics are below.

The **Member** resource manages user membership in the customer's Organization. Endpoints support inviting a user, listing members, updating a member's role, and removing a member. Subject to permission checks based on the caller's role.

The **APIKey** resource manages API keys for programmatic access. Endpoints support creating a key (returned exactly once at creation, never retrievable again), listing keys with their metadata but not their secret values, and revoking a key.

The **AuditEvent** resource exposes the customer's audit log. Read-only. Endpoints support listing events with filters for date, user, action type, and entity, retrieving a specific event, and exporting a date range as a tamper-evident bundle.

The **UsageReport** resource exposes the customer's plan usage and billing state. Read-only. Endpoints support retrieving the current period's usage, listing historical periods, and retrieving the most recent customer-facing invoice from ZeroKey.

Several other resources (Notification, ApprovalRequest, ConnectorConfiguration, etc.) are exposed through the internal API but are not yet first-class in the public API for v1. These are documented in the internal API reference.

## Authentication and key management

API keys are the primary authentication mechanism for the public API. Keys are created in the customer's settings area (in the dashboard) or programmatically through the internal API by an authorized user.

Each key has a unique identifier, a name (chosen by the customer), a scope (a set of permissions the key is authorized for), an expiration timestamp (optional), and a last-used timestamp (updated on every authenticated call). The actual secret value is shown to the customer exactly once at creation; afterward, only a hash is stored, and the key cannot be retrieved.

Scopes are a strict subset of the customer's user permissions. A key with the `invoice:write` scope can create and update invoices but not export the audit log. A key with `audit:read` can list audit events but not modify any data. The scope mechanism prevents API keys from being used as backdoor full-access credentials.

API keys can be revoked at any time. Revocation is immediate; subsequent calls with the revoked key receive a `401 Unauthorized` response with an error code of `key_revoked`.

API keys for Custom-tier customers can be IP-allowlisted: calls from outside the configured IP ranges are rejected at the edge.

## Authorization model

Authorization happens after authentication, before any business logic. Every endpoint declares the permissions it requires. The middleware checks the authenticated identity's permissions against the endpoint's requirements, returning `403 Forbidden` if the check fails.

Role-based permission mapping is defined in the identity domain (see `DATA_MODEL.md`). The Owner role has all permissions. The Admin role has all permissions except billing. The Approver role can submit and approve. The Submitter role can create drafts but not submit. The Viewer role can only read.

API keys carry their own scope independent of any user role. A key created with `invoice:write` scope by an Owner has only that scope; the key does not inherit the Owner's full permissions.

Multi-tenancy authorization is enforced at the database layer through Row-Level Security policies, in addition to application-layer checks. An API key for one Organization cannot retrieve another Organization's data even if the application code had a bug; the database refuses to return rows.

## Error response shape

Every error response uses the same shape:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "The buyer TIN is required for this invoice type.",
    "field": "buyer.tin",
    "documentation_url": "https://docs.zerokey.symprio.com/errors/validation_failed",
    "request_id": "req_abc123def456"
  }
}
```

The `code` is a stable, machine-parseable error identifier. Codes are documented in the API reference and never change once published. Examples include `authentication_failed`, `permission_denied`, `validation_failed`, `rate_limited`, `external_service_unavailable`, `lhdn_rejection`, `idempotency_conflict`.

The `message` is a human-readable explanation, suitable for displaying in a developer's UI or logging for debugging. Messages are written in clear English and are not localized in v1; if developers need localized error messages for their own users, they translate based on the code.

The `field` is present for validation errors and points to the JSON path of the offending field.

The `documentation_url` links to a reference page explaining the error and common resolutions.

The `request_id` is a unique identifier for the API call that can be used in support tickets to look up the exact call in our logs.

HTTP status codes follow standard conventions: `400` for client errors with malformed requests, `401` for authentication failures, `403` for authorization failures, `404` for not-found, `409` for conflicts (idempotency, state transitions), `422` for semantic validation errors, `429` for rate limiting, `500` for unexpected server errors, `502` and `503` for external dependency failures, `504` for timeouts.

## Idempotency

All mutating endpoints accept an optional `Idempotency-Key` HTTP header. Requests with the same idempotency key within a 24-hour window are deduplicated: the second request returns the result of the first without performing the mutation again.

For invoice submission specifically, an idempotency key is strongly recommended. A network failure during the submit call could otherwise lead a client to retry and accidentally double-submit to LHDN. With an idempotency key, the retry is safe.

Idempotency keys are scoped to the API key making the call, so two different integrations with their own keys can use the same idempotency key string without conflict.

The 24-hour window is a deliberate trade-off: long enough to handle reasonable retry scenarios, short enough that we do not retain idempotency state indefinitely.

## Rate limiting

Rate limits apply per API key with limits configured by the customer's Plan. Default limits at launch are: 60 requests per minute on Starter, 300 per minute on Growth, 1,200 per minute on Scale, and 6,000 per minute on Pro. Custom-tier limits are negotiated per deal.

Rate limit responses include standard headers: `X-RateLimit-Limit` (the cap), `X-RateLimit-Remaining` (calls remaining in the current window), `X-RateLimit-Reset` (when the window resets), and `Retry-After` (suggested wait in seconds). Clients that respect these headers experience graceful degradation rather than abrupt rejection.

Beyond per-API-key limits, certain expensive operations (bulk submit, large export) have their own per-Organization concurrency limits to prevent any single customer from monopolizing shared infrastructure.

## Pagination details

Cursor-based pagination uses opaque cursor strings. The cursor encodes the position in the result set in a way that is stable even if new records are inserted while pagination is in progress.

A typical paginated request looks like `GET /v1/invoices?limit=50&cursor=eyJ0aW1lc3RhbXAi...`. The response is `{"data": [...], "next_cursor": "...", "has_more": true}`.

The default page size is 50, the maximum is 200. Larger page sizes have higher per-call cost but lower aggregate cost over many pages.

For long-running list operations where the client wants every record (typically for export), the recommended pattern is to paginate with the maximum page size until `has_more` is false. We do not provide a synchronous "give me all records" endpoint; the cost would be unbounded.

## Webhooks

Webhooks are how ZeroKey notifies external systems of state changes asynchronously.

A webhook subscription is configured per Organization with the destination URL, the event types to subscribe to, and a shared secret used for HMAC signing. Common event types include `invoice.validated`, `invoice.rejected`, `invoice.cancelled`, `invoice.requires_attention`, `ingestion_job.completed`, `ingestion_job.failed`, `subscription.usage_threshold_reached`, and `subscription.payment_failed`.

When an event occurs, ZeroKey enqueues a delivery to each matching subscription. Deliveries are HTTP POSTs with a JSON body containing the event metadata and the relevant resource snapshot. Each delivery includes an `X-ZeroKey-Signature` header containing an HMAC-SHA256 of the body using the subscription's shared secret. Receivers verify the signature to confirm the request actually came from us.

Delivery includes retries with exponential backoff. The initial delivery is attempted immediately. Failures (non-2xx response, timeout) are retried at 1 minute, 5 minutes, 30 minutes, 2 hours, 12 hours, and 24 hours. After all retries fail, the delivery moves to a dead-letter queue visible in the customer's webhook dashboard.

Webhook payloads are versioned alongside the API. A v1 webhook subscription receives v1-shaped payloads. A subscription created against a future v2 receives v2-shaped payloads. Customers control the version their webhook subscription uses.

Webhook delivery includes the originating event's idempotency-key (for events that were initiated by an idempotent API call), so receivers can deduplicate if they receive the same event multiple times due to retries.

## API versioning

The major version is in the URL: `/v1/`, eventually `/v2/`. A new major version is introduced only for genuinely breaking changes. Within a major version, additive changes (new fields in responses, new optional fields in requests, new endpoints) are made freely and do not require version bumps.

When a v2 is introduced, v1 continues to be supported for at least 18 months. Customers are notified, given migration guidance, and helped through the transition. The deprecation timeline is announced at v2 launch.

Within a major version, individual endpoints can be deprecated. Deprecated endpoints continue to work but include a `Sunset` HTTP response header indicating when they will be removed and a link to the replacement.

## Sandbox environment

A complete sandbox environment is exposed at `https://api.zerokey.symprio.com/v1/sandbox/` (or as a separate base URL — to be finalized at implementation time). The sandbox is a separate set of databases, separate API keys, and submissions go to LHDN's MyInvois sandbox rather than production.

Sandbox API keys are self-serve from the dashboard for any tier including Free Trial. There is no waiting period or approval. This serves Ravi (the integrator persona) and any developer evaluating ZeroKey.

The sandbox is reset weekly to a known baseline state. Customers should not store sandbox-only data they cannot recreate.

## Documentation as a deliverable

The API documentation is a first-class deliverable, hosted at `docs.zerokey.symprio.com`. It is generated from OpenAPI specifications that are part of the codebase, ensuring it is always synchronized with the actual API surface.

Every endpoint has a complete reference page including request and response shapes, all parameters, all error codes that endpoint can produce, and runnable examples in curl, JavaScript, Python, and Go. The runnable examples are tested as part of the CI pipeline; documentation that does not actually work is treated as a bug.

Conceptual guides explain how to do common tasks: how to ingest an invoice, how to handle webhooks, how to handle rate limits, how to debug LHDN rejections. These guides are written for the integrator persona and assume technical literacy without assuming familiarity with our domain.

The documentation is searchable, linkable to specific anchors, and includes a clear changelog of what has changed in each release.

## Internal API differences

The internal API serving the Next.js frontend deviates from the public conventions in a few places where the trade-offs differ.

The internal API uses session cookies rather than API keys. The internal API is allowed to evolve in shape between deployments; the frontend and backend are deployed together so coordination is automatic. The internal API includes endpoints that aggregate data for specific UI surfaces (the dashboard summary, the exception inbox view) that would be overly chatty if implemented as separate public-API calls; these are pragmatic accommodations to UI performance, not intended for external use.

The internal API does not have a published schema; the frontend reads it through TypeScript types co-generated from the backend serializers. External developers should not consume internal endpoints; they may break without notice.

## Operational discipline

Several disciplines keep the API healthy over time.

Every endpoint has its own integration test suite verifying both the happy path and the major error cases. New endpoints are not merged without tests.

Every endpoint emits metrics with the endpoint name, the response code, and the latency. These are reviewed weekly to catch creeping regressions.

API changes are reviewed for backwards compatibility before merge. A change that would break v1 consumers without a version bump is rejected.

A weekly review of API errors identifies patterns: which endpoints are returning the most 4xx errors, what error codes are most common. Persistent error patterns indicate either a documentation gap or an API design issue, and both are addressed.

Customers reporting API issues get a response within their tier's SLA. Their report is investigated using the request ID they provide; we can look up the exact call in our logs and reproduce the issue.

## How this document evolves

When a new endpoint is introduced, this document is updated. When a convention changes (rare, requiring careful consideration of backwards compatibility), this document is updated. When a major version is introduced, a new version of this document is created alongside.

When this document and the actual API diverge, one is wrong. Either the document is updated to reflect the new reality, or the API is brought back into alignment with the documentation. We do not let drift accumulate.
