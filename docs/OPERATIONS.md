# OPERATIONS — ZeroKey

> How ZeroKey runs in production. This document covers deployment, environments, monitoring, alerting, on-call, incident response, and the operational disciplines that keep a regulated SaaS service reliable enough to be trusted with customer compliance.

## Operations philosophy

Five principles govern operational decisions, in precedence order.

The first principle is **reliability is the feature**. Customers do not pay for ZeroKey because it is sometimes available. They pay because they need their invoices submitted to LHDN reliably and the audit log preserved permanently. Operational reliability is not a separate concern from product quality; it is product quality.

The second principle is **observable by design, not by retrofit**. Every service emits structured logs, metrics, and traces from its first deployment. We do not deploy services we cannot debug at 2 AM during an incident.

The third principle is **automation over heroics**. Routine operational tasks are automated. Heroic 2 AM debugging sessions are a sign that automation is missing. Every incident produces a post-mortem that asks "what automation would have prevented this or made the response faster" as a central question.

The fourth principle is **graceful degradation is better than hard failure**. When a dependency fails, the system degrades gracefully where possible: queueing instead of erroring, falling back to alternate engines, surfacing helpful messages to customers instead of cryptic errors.

The fifth principle is **honesty during incidents**. Status pages reflect real state. Customer communications during incidents are direct and informative. Post-incident reviews are published when impact warrants. Trust during incidents is built or destroyed by transparency.

## Environments

Three environments serve distinct purposes and are isolated from each other in every meaningful way.

The **production environment** serves real customers and submits invoices to real LHDN MyInvois. It runs in `ap-southeast-5` (AWS Asia Pacific Malaysia) with disaster-recovery capacity in `ap-southeast-1` (Singapore). Production has the strictest access controls and change management.

The **staging environment** mirrors production architecture and is used for final pre-deployment validation. Staging connects to LHDN's MyInvois sandbox, not production. Staging data is synthetic; no real customer data is ever loaded into staging.

The **development environment** is for daily engineering work. It connects to the same LHDN sandbox as staging but is otherwise isolated. Each developer can run a local development environment that mirrors the deployed development environment for offline work.

A short-lived **preview environment** is spun up automatically for each pull request that introduces non-trivial changes, allowing visual review before merge. Preview environments are torn down after the pull request is closed.

Environment isolation is enforced at the credential layer (separate API keys per environment), the network layer (separate VPCs), the data layer (separate databases), and the policy layer (no production credential ever appears in any non-production environment).

## Deployment pipeline

Deployment to production is fully automated through GitHub Actions but requires explicit human approval at the production gate.

Every commit to a feature branch triggers the development pipeline: lint, type check, unit tests, integration tests against the development database, container image build, and deployment to a preview environment if applicable.

Every merge to the main branch triggers the staging pipeline: full test suite execution, deployment to staging, smoke tests against the deployed staging environment, and a hold for production approval.

Production deployment is gated by manual approval from the founder (in the founding period; from a designated release manager once the team grows). The approval is recorded with a timestamp and the approver's identity.

Production deployments use blue-green deployment. The new version is deployed alongside the current version in parallel ECS service revisions. Health checks confirm the new version is functional. Traffic is shifted gradually from the current version to the new version over several minutes, with continuous health monitoring. If health degrades during the shift, traffic is rolled back automatically. If the deployment completes successfully, the old version is drained and torn down.

Database migrations are designed to be backwards-compatible across at least one version. A migration that drops a column is split across multiple deployments: the application code that uses the column is removed first, the deployment is verified, then the migration to drop the column is applied. This discipline lets us deploy without downtime.

Hotfix deployments can bypass staging when the founder explicitly approves an urgent fix. Hotfixes are recorded with a documented justification.

## Configuration management

Configuration falls into three tiers, each with its own lifecycle and access controls.

**Code-level configuration** lives in the repository. Examples include the structure of Django settings (per-environment), the routing rules for the application, the schema migrations. Changes are reviewed and deployed through the normal pipeline.

**Infrastructure configuration** lives in Terraform modules. Examples include the AWS resources, IAM policies, network topology, RDS instance class. Changes are reviewed and applied through `terraform plan` and `terraform apply` with approval gates similar to code deployments.

**Operational configuration** lives in PostgreSQL and is editable from the super-admin console. Examples include plan parameters, feature flags, engine routing rules, customer-specific overrides. Changes are made by authorized staff and audit-logged. No code or infrastructure deployment is needed.

The boundary between these tiers is deliberate. Pricing changes do not require code deploys. New engines do not require infrastructure changes. New features can be enabled per customer through feature flags rather than code branches.

## Observability stack

The observability stack consists of three pillars.

**Structured logs** are emitted by every service in JSON format with consistent field naming. Logs include the request ID, the user ID, the tenant ID, the operation, the outcome, and any context relevant to debugging. Logs are shipped to AWS CloudWatch Logs in v1, with the option to upgrade to Datadog or a self-hosted OpenSearch stack as scale demands.

The structured log format includes severity (debug, info, warn, error, critical), a timestamp in ISO 8601, the service name, the environment, and the component. Sensitive fields (passwords, API keys, certificate material, full PII) are filtered before serialization through a centralized redaction allowlist.

Logs are retained for thirty days at full fidelity, then summarized for ninety days, then deleted. Critical logs (security events, audit-relevant events) are retained according to compliance retention rules separately from the operational log stream.

**Metrics** are emitted using the OpenTelemetry standard and shipped to AWS CloudWatch Metrics. Metrics include the standard system metrics (CPU, memory, disk, network) and application-specific metrics (request rate, request latency by endpoint, queue depth by Celery queue, extraction latency by engine, MyInvois submission success rate, payment success rate).

Custom dashboards are maintained for: the system health overview (top-level reliability metrics), the customer experience view (latency and error rates from the customer perspective), the LHDN integration health (submission success rate, polling latency, error code distribution), the engine registry view (per-engine cost, latency, and quality), and the billing health view (payment success rate, subscription state distribution).

**Distributed traces** are emitted using OpenTelemetry and exported to whichever tracing backend is current. Traces follow a customer request from edge through application, into Celery work, through external API calls, and back. When something is slow, the trace tells us where.

Trace sampling is adaptive: low-traffic endpoints are traced at 100%, high-traffic endpoints are traced at 1-10% with deterministic sampling so that all spans within a single request are kept together. Traces for failed requests are always kept.

## Service level objectives

ZeroKey commits to specific SLOs that are measured and reported.

The **availability SLO** for the customer-facing application is 99.9% measured monthly, equivalent to roughly 43 minutes of permitted downtime per month. SLO measurement excludes scheduled maintenance windows announced at least 48 hours in advance and excludes incidents caused by external dependencies (LHDN itself, AWS regional outages).

The **submission success SLO** for invoices that pass our pre-flight validation is 99.5% first-submission validation rate at LHDN, measured monthly, excluding LHDN platform outages. This is the most product-meaningful SLO; if we are letting invoices through pre-flight that LHDN rejects, our value proposition is broken.

The **API latency SLO** is that 95% of API calls complete within their target latency: 200ms for read operations, 800ms for synchronous writes, 2 seconds for write operations that include synchronous LHDN calls.

The **extraction latency SLO** is that 90% of extraction jobs complete within 60 seconds for native PDFs, within 120 seconds for scanned documents requiring OCR, and within 300 seconds for batch operations.

The **support response SLOs** vary by plan tier and are detailed in the customer's plan terms.

SLO violations are tracked. A monthly SLO compliance report is generated and reviewed. Sustained SLO violations trigger structured improvement work.

## Alerting and on-call

Alerts route to the on-call rotation when conditions cross defined thresholds. The alerting philosophy is high-signal: an alert means a human must look. Noisy alerts are systematically retired or downgraded to warnings (which are visible but not paging).

In the founding period, the on-call rotation is the founder. As the team grows, a proper rotation is established with handoff procedures and shared documentation.

Alerts are categorized by severity. Critical alerts (production down, data integrity issues, security incidents) page immediately at any hour. High alerts (significant degradation, sustained errors) page during business hours and notify by chat off-hours. Medium alerts notify by chat only. Low alerts go to the operations dashboard for review.

Each alert includes a runbook link. The runbook describes what the alert means, common causes, diagnostic steps, and remediation procedures. Runbooks live in the repository alongside the service code.

Specific critical alerts at launch include: production application unavailability, MyInvois submission failure rate above threshold, payment success rate degradation, signing service errors, audit log chain integrity verification failure, and any database replication lag beyond threshold.

## Runbooks

Several runbooks are maintained in the codebase under `docs/runbooks/`. The high-level catalog at launch includes the following.

**MyInvois disruption response** covers what to do when LHDN's MyInvois platform is down or degraded. The runbook includes confirming the disruption, updating the customer-facing status page, configuring the submission queue to hold rather than retry aggressively, communicating to customers, monitoring for recovery, and resuming submission with appropriate rate limiting once recovery is confirmed.

**Engine vendor outage response** covers what to do when an OCR or LLM vendor experiences sustained outage. The runbook includes confirming the outage, ensuring routing fallback is engaging correctly, monitoring fallback engine quality, communicating to customers if customer-visible impact occurs, and updating routing rules if a sustained vendor change is needed.

**Database failure response** covers RDS primary failure, replica lag, connection exhaustion, and other database incidents. The runbook includes failover procedures, the diagnostic queries to run, the criteria for declaring a database incident, and the communication path.

**Payment processor outage response** covers Stripe outages or payment processing degradation. The runbook includes how to communicate with affected customers, how to handle in-flight transactions, and how to reconcile after recovery.

**Security incident response** covers suspected unauthorized access, credential leakage, customer-reported security issues, and active attacks. The runbook is detailed and includes containment, investigation, customer notification, regulatory notification (PDPA), and post-incident review.

**Customer data deletion incident** covers what to do if a customer's deletion was mistakenly initiated, partially completed, or accidentally affected the wrong tenant. Given the irreversibility of deletion, this runbook is invoked rarely but with extreme care.

**Audit chain integrity failure** covers what to do if the nightly chain verification fails. The runbook includes immediate isolation, forensic preservation of state, escalation to founder, and communication procedures. This is among the most serious classes of incident.

**Certificate expiration** covers customer signing certificate expiration scenarios, both proactive (reminding customers) and reactive (when a customer's certificate has actually expired). The runbook includes the customer communication and the temporary suspension of submissions for affected customers until renewed.

**Subscription billing dispute** covers chargebacks, payment disputes, and customer-initiated refund requests outside the standard money-back guarantee window. The runbook includes the response procedure, the documentation gathered, and the resolution approach.

Runbooks are reviewed and updated after every relevant incident. Stale runbooks are themselves an operational risk.

## Incident response procedure

When a production incident occurs, the response follows a defined procedure.

**Detection** happens through alerting (most common), customer report (occasional but important), or internal observation (rare but should not be discouraged). Any path is valid.

**Triage** assesses severity. The severity scale is: critical (production down, customer data integrity at risk, security incident in progress), high (significant degradation affecting many customers), medium (degradation affecting specific functions or specific customers), low (a problem that should be fixed but is not customer-impacting now).

**Initial response** for any non-low incident includes acknowledging the alert, assembling the response (in the founding period, the founder; later, the on-call plus any subject-matter experts), and creating a tracking record (an incident channel, a tracking ticket).

**Customer communication** happens early. For critical and high incidents, the public status page is updated as soon as the incident is confirmed, even before the cause is understood. The status page is the source of truth; we do not surprise customers via support tickets that say something different.

**Investigation and remediation** follow the relevant runbook or, if no runbook applies, established debugging practice. Investigation findings and remediation steps are recorded in the incident channel.

**Resolution** is declared when the impact has stopped and the system is stable. The status page is updated.

**Post-incident review** happens within five business days for critical and high incidents. The review includes the timeline of events, the root cause, the immediate fix, the systemic improvements identified, and assigned actions with owners and deadlines. For customer-impacting incidents, a public post-mortem is published if the impact warranted it.

## Change management

Operations involves not just incidents but also changes. Every production change goes through change management.

**Standard changes** are routine, low-risk changes that follow established procedures. Examples: a regular code deployment, a routine RDS patch, a credential rotation that follows the rotation procedure. These do not require additional approval beyond the normal pipeline.

**Normal changes** are non-routine but planned. Examples: introducing a new engine, modifying engine routing rules, adjusting feature flag defaults. These require approval from the founder (in the founding period) or from the change advisory function (later) and are recorded.

**Emergency changes** are unplanned changes made during incidents. Examples: scaling up a cluster to absorb a traffic spike, disabling a problematic feature flag during an outage. Emergency changes are made under incident authority, documented in the incident timeline, and reviewed in the post-incident review.

All changes are audit-logged. The change record includes who made the change, when, what was changed, why, and what was done to verify the change.

## Backup and recovery

Backups are continuous for the database and periodic for object storage.

**PostgreSQL backups** use RDS automated continuous backups with point-in-time recovery for the past 35 days. Daily snapshots are retained for one year. Manual snapshots are taken before any major change and retained until verified stable.

**S3 backups** use cross-region replication to `ap-southeast-1` and bucket versioning to protect against accidental deletion. Lifecycle policies move older versions to less expensive storage classes.

**Redis backups** use ElastiCache snapshots daily, retained for seven days. Redis is treated as recoverable from PostgreSQL state for sessions and Celery state; we do not depend on Redis backups for any business data.

**Configuration backups** are implicit in the version-controlled Terraform and code repositories.

Recovery procedures are tested periodically through disaster recovery exercises. Detailed recovery procedures are in `DISASTER_RECOVERY.md`.

## Capacity planning

Capacity is monitored continuously and reviewed monthly.

**Compute capacity** at the application tier scales automatically based on CPU and request rate. The auto-scaling configuration is reviewed monthly to ensure thresholds remain appropriate.

**Work tier capacity** scales automatically based on Celery queue depth. Different queue priorities scale independently.

**Database capacity** is monitored for CPU, memory, connections, IOPS, and storage. Vertical scaling decisions (upsizing the RDS instance) are made proactively based on trend lines, not reactively after exhaustion. Horizontal partitioning (read replicas, sharding) is reserved for scale where vertical scaling is exhausted, which we do not expect to hit in v1.

**Storage capacity** is monitored for S3 across all customer-facing buckets. S3 itself does not have meaningful capacity limits at our scale, but cost trajectories are monitored.

**External rate limits** (LHDN, Stripe, AI engines) are monitored and surfaced to capacity planning. If we are approaching a vendor's rate limit, we either negotiate a higher limit, route to alternate engines, or queue more aggressively.

## Cost management

Operational cost is monitored monthly.

The largest cost categories are AWS infrastructure (compute, storage, database), AI engine API calls, and third-party services (Stripe processing fees, observability tools, communication services).

Cost per customer is computed by attributing variable costs to the originating customer's invoices and amortizing fixed costs across active customers. This produces a cost-per-customer metric that informs pricing decisions.

Cost anomalies (sudden spikes in any category) trigger investigation. The anomaly may be legitimate (a customer onboarded a large batch) or may indicate a bug (a runaway retry loop, a misconfigured engine route). Investigation is prompt.

## Security operations

Security operations is integrated into general operations rather than being a separate stream.

The security incident response runbook is one of the runbooks above. Security alerts integrate into the same alerting infrastructure.

**Vulnerability scanning** runs automatically against dependencies, container images, and infrastructure configuration. Findings are triaged with severity-appropriate timelines.

**Access reviews** happen quarterly. Every staff member's access to production systems and customer data is reviewed against their current role.

**Incident drills** rehearse the security incident response procedure at least quarterly. Scenarios include credential leakage, customer data exposure, ransomware, and insider threat.

**Penetration testing** is conducted at least annually by an external firm once we have customers. Findings are remediated promptly and verified.

Security operations work is logged in the audit infrastructure with appropriate sensitivity controls.

## Customer support operations

Customer support is part of operations because the product cannot be operationally healthy without operational support quality.

Support intake is through email, chat (for higher tiers), and the in-product help interface. Tickets are tracked in a support system with response time targets per tier.

Support staff have access to customer data through the impersonation flow with full audit logging. They do not have direct database access.

Common support patterns are documented in the support knowledge base. As patterns emerge, the help center is updated, the product surface is improved to prevent the issue, or both.

Escalation from support to engineering follows a defined path. Engineering investigates, fixes, and updates the support team. The customer is updated with progress.

## How this document evolves

When a runbook is added or significantly updated, this document references it. When an SLO is added, redefined, or retired, this document is updated. When an environment is added or changed, this document is updated.

When operational practice diverges from this document, the divergence is investigated. Either the document is updated (if the new practice is correct) or the practice is brought back into alignment (if the divergence was accidental).

When a new team member or AI collaborator joins the operations function, this document plus the runbooks form the mental model they need to be productive. A team member who has read this document and the runbooks should be able to handle any standard incident class without supervision.
