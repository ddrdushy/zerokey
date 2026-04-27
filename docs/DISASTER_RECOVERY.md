# DISASTER RECOVERY — ZeroKey

> The plan for surviving catastrophic failure. This document specifies the recovery objectives, the backup and replication architecture, the failover procedures, and the testing discipline that keeps us prepared for the worst-case scenarios that have not happened yet.

## Disaster recovery philosophy

A regulated SaaS product handling tax-relevant data and customer signing certificates cannot afford to lose data. It cannot afford extended downtime during regional infrastructure failures. It cannot afford to discover during a crisis that its backups were not actually working.

This document is therefore not aspirational. The procedures below are tested. The recovery objectives below are measured. The dependencies below are documented and understood.

Three principles govern every disaster recovery decision.

The first principle is **assume failure will happen**. AWS regions go down. Database clusters fail. Power grids fail. Cables get cut. Configuration changes go wrong. We design for these scenarios as inevitable, not as remote possibilities.

The second principle is **untested backups do not exist**. A backup that has never been restored is a hope, not a backup. Recovery procedures are tested on a defined schedule. A successful test is the only evidence the backup actually works.

The third principle is **graceful degradation under extreme failure**. When recovery takes hours, customers should still know what is happening, when service will return, and what they can do in the meantime. Silence during disaster is the worst possible posture.

## Recovery objectives

Two metrics define our recovery commitments.

The **Recovery Time Objective (RTO)** is the maximum acceptable time between a disaster occurring and the service being restored. Our RTO at launch is **four hours** for a complete regional disaster requiring failover to the disaster recovery region. For lesser failures (single instance failure, single availability zone failure), the RTO is much shorter — typically under 15 minutes — because automated recovery handles them.

The **Recovery Point Objective (RPO)** is the maximum acceptable amount of data loss measured in time. Our RPO at launch is **one hour** in the worst case (regional disaster requiring failover with the most recent replication lag). For most failure modes, RPO is effectively zero because synchronous replication captures every committed transaction in the standby database.

These objectives are deliberate trade-offs. Tighter RTO and RPO would require more expensive infrastructure (active-active multi-region deployment, more aggressive replication). Looser RTO and RPO would be unacceptable for a regulated product. The four-hour, one-hour pair is the right balance for our launch scale and customer commitments.

As the customer base grows and Custom-tier deployments mature, customers may negotiate tighter RTO and RPO commitments through contractual SLAs. Those commitments are then operationalized through enhanced infrastructure.

## Failure scenarios we plan for

We plan for an explicit set of failure scenarios. The plan exists for each.

**Single application instance failure** is handled automatically by ECS. The failed task is detected, terminated, and replaced. RTO is measured in seconds. RPO is zero (the failed instance was stateless).

**Single availability zone failure** is handled automatically by the multi-AZ architecture. The application tier and work tier run across multiple AZs; the load balancer routes around the failed AZ. RDS PostgreSQL fails over to the standby in another AZ. ElastiCache fails over similarly. RTO is measured in minutes. RPO is effectively zero for synchronous replication.

**Regional service disruption** (a single AWS service in our region experiencing an outage while others remain functional) is handled differently per service. If RDS is impacted, we may degrade gracefully (delaying writes to a queue while reads continue from the standby in another AZ); if S3 is impacted, certain operations queue until recovery; if KMS is impacted, signing and field-level decryption pause and customers see a clear status banner. The plan for each service-specific outage is in `OPERATIONS.md` runbooks.

**Full regional disaster** (the entire `ap-southeast-5` region unavailable) triggers the failover procedure to `ap-southeast-1`. This is the worst-case scenario the four-hour RTO covers. Detail below.

**Database corruption** (a software bug or human error that corrupts production data) is handled through point-in-time recovery from the continuous backup. Detail below.

**Accidental deletion** (a deployment error, a misconfigured cleanup job, an operator mistake) is similarly handled through point-in-time recovery, S3 versioning, or the Trash retention configured on customer data.

**Compromise** (a security incident requiring data integrity verification or restoration from a known-good state) involves isolation, forensic preservation, and recovery procedures detailed in `OPERATIONS.md` and `SECURITY.md` runbooks.

**Vendor failure** (a critical external dependency unavailable for an extended period) is handled through engine fallbacks (for AI engines), payment retry windows (for Stripe), submission queueing (for LHDN), and customer communication.

## Backup architecture

The backup architecture is structured around the three data tiers (PostgreSQL, S3, Redis).

### PostgreSQL backups

RDS provides automated continuous backups via WAL streaming, enabling point-in-time recovery to any moment within the past 35 days. This is the primary recovery mechanism for the database.

In addition, RDS performs daily snapshot backups, retained for 35 days through automation. Beyond 35 days, weekly snapshots are exported to S3 in an encrypted, region-replicated bucket and retained for one year. After one year, monthly snapshots are retained indefinitely for any compliance-relevant historical recovery needs.

Manual snapshots are taken before any major schema migration and before any operationally significant change. These manual snapshots are explicitly named and retained until the change is verified stable in production.

Backups are encrypted using KMS keys. The KMS keys for backup encryption exist in both the production region and the disaster recovery region; the disaster recovery region has its own KMS key reference for encrypted snapshot copies, ensuring the encrypted backups can be decrypted in the failover region.

Backup integrity is verified continuously. The latest snapshot is restored to a temporary RDS instance weekly and validated by running a test query suite against it. Verification failures are critical incidents.

### S3 backups

The S3 buckets storing customer data have versioning enabled, providing recovery from accidental deletion or modification. Versions are retained for 90 days for routine versioning, with longer retention for buckets holding compliance-relevant data.

Cross-region replication is configured for all customer-data buckets, replicating asynchronously to the disaster recovery region. The lag between source and destination is monitored; sustained lag beyond 15 minutes triggers an alert.

S3 Object Lock is configured on buckets holding the audit log archive bundles, providing legal-hold-grade retention that even our highest-privileged staff cannot override.

Bucket-level lifecycle policies move older objects to cheaper storage classes (S3 Infrequent Access, then Glacier Deep Archive) according to defined schedules, balancing cost and recoverability. The lifecycle policies do not delete objects within retention windows.

### Redis backups

ElastiCache produces snapshots daily, retained for seven days. As noted in `ARCHITECTURE.md`, Redis is treated as recoverable from PostgreSQL state; sessions get reset on Redis loss, Celery in-flight jobs get re-enqueued from PostgreSQL state, and cached data is recomputed.

Redis is therefore not a critical recovery target. The backups exist as a convenience to avoid full session reset on minor failures, not as a primary protection.

### Configuration and code backups

Application code and infrastructure configuration are version-controlled in GitHub. The repository itself is replicated by GitHub. Local clones exist on developer machines.

Operational configuration (Plans, FeatureFlags, EngineRoutingRules) is in PostgreSQL and is therefore backed up with the database. Periodic exports of operational configuration are taken and stored separately for additional safety.

Secrets are in AWS Secrets Manager, with cross-region replication enabled.

## Disaster recovery region

The disaster recovery region is `ap-southeast-1` (AWS Asia Pacific Singapore). The choice of Singapore is deliberate: it is the nearest AWS region to Malaysia outside `ap-southeast-5`, providing low-latency replication and regional proximity for any customers who need to be informed of the failover.

In normal operation, the disaster recovery region holds:

- A continuously updated RDS read replica receiving streaming replication from the production primary. The replica is sized at 80% of production capacity (lower cost, can be scaled up during failover).
- Replicated S3 buckets with replication lag under 15 minutes typical.
- Replicated KMS key references allowing encrypted backups and replicas to be decrypted in this region.
- Standby ECS service definitions with task counts set to zero, ready to scale up on failover.
- Standby ElastiCache cluster, sized smaller than production, ready to scale.
- Standby Cloudflare configuration with the failover endpoints predefined.

In active operation during failover, the disaster recovery region scales to full capacity, the database replica is promoted to primary, the application tier scales up, and traffic is routed by Cloudflare.

## Failover procedure

The failover procedure to the disaster recovery region is documented as an explicit runbook with the following high-level steps.

**Step 1: Confirm the failure** is real and not a transient issue. The criteria for declaring a regional disaster requiring failover are: production region appears unreachable for more than 30 minutes despite multiple validation paths, AWS Service Health Dashboard confirms a regional event affecting our critical services, our internal monitoring shows sustained complete failure across multiple subsystems. The decision to failover is made by the founder (in the founding period) or the on-call lead following the runbook (later).

**Step 2: Communicate to customers** that we are failing over. The status page is updated. An email is sent to all active customers explaining what is happening, the expected timeline, and what they should do (typically: wait, do not attempt to retry, we will resume processing automatically). Customer communication happens before technical recovery is complete because customers should know what is going on.

**Step 3: Promote the database replica** in the disaster recovery region to primary. The promotion is a defined RDS operation that takes minutes. After promotion, the database is writable in the disaster recovery region.

**Step 4: Scale up the application and work tiers** in the disaster recovery region. ECS services that were standby with zero tasks are scaled to production task counts. Health checks confirm services are operational. This takes around 10-20 minutes from initiation to ready.

**Step 5: Update Cloudflare routing** to direct traffic to the disaster recovery region. Cloudflare changes are near-instantaneous globally. Customer requests start landing in the disaster recovery region.

**Step 6: Verify operations**. Spot-check critical functions: a test invoice submission, a test payment confirmation, a test login, a test API call. Confirm metrics and logs are flowing. Confirm the audit log chain integrity verification passes.

**Step 7: Resume customer-facing operations** with a status page update confirming recovery. Customer email follows confirming service is restored, with an explanation of what happened and what to expect (some queued work will catch up over the next few hours).

**Step 8: Begin the return-to-primary planning** once `ap-southeast-5` is functional again. Returning to the primary region is a deliberate operation with its own runbook, typically scheduled outside peak hours and with full customer notification.

The total elapsed time from failure declaration to operational recovery is targeted at under 4 hours. Drills demonstrate that the procedure can complete in under 2 hours when rehearsed; the 4-hour RTO includes margin for unexpected complications during a real incident.

## Point-in-time recovery procedure

Point-in-time recovery is used for database corruption, accidental data loss, or any scenario where rolling back to a specific moment is needed.

**Step 1: Identify the target time** for recovery. This is typically the moment immediately before the corrupting event.

**Step 2: Initiate RDS point-in-time recovery** to a new RDS instance. The recovered instance is created alongside production, not replacing it, so that production remains available during the recovery process.

**Step 3: Validate the recovered instance** by running test queries to confirm the data state matches expectations.

**Step 4: Plan the cutover** depending on the scenario. For a full database recovery, the recovered instance replaces production. For a partial recovery (specific tables, specific rows), data is exported from the recovered instance and merged into production through controlled SQL operations. The latter is far more common.

**Step 5: Execute the cutover** during a maintenance window if possible, with appropriate customer communication.

**Step 6: Decommission the recovery instance** after the recovery is complete and verified stable.

The full procedure has an associated runbook with detailed steps, contingencies, and validation queries.

## Customer-initiated data recovery

Customers occasionally need to recover specific data they accidentally deleted or modified. Our response varies by scenario.

For invoices that were cancelled, the cancellation is reversible within the LHDN seventy-two-hour window through the standard credit note flow. Beyond that window, the cancellation is irreversible at LHDN; we explain this clearly.

For customer master or item master records that were deleted, the soft-delete pattern means the records are still in the database with a deleted flag. Restoration is straightforward through support intervention, audit-logged.

For settings or configuration that was changed unintentionally, the audit log captures the previous values. Reverting requires support intervention but is straightforward.

For account-level deletions that progressed past the read-only retention period, recovery is not possible. We document this clearly in the deletion flow so customers do not initiate deletion expecting it to be undoable.

## Testing discipline

Disaster recovery procedures are tested on a defined schedule.

**Backup integrity verification** runs continuously through the weekly snapshot restore to a test instance.

**Failover drills** are conducted quarterly. The drill simulates a regional disaster and runs the full failover procedure end-to-end against a non-production environment that mirrors production. The drill produces a report documenting the actual elapsed time for each step and any deviations from the runbook. Findings drive runbook updates.

**Restore drills** are conducted monthly for point-in-time recovery. A specific historical state is recovered to a test instance and validated.

**Tabletop exercises** are conducted quarterly with the broader team, walking through scenarios verbally to ensure everyone knows their role and the runbooks are clear.

Test failures are treated as serious findings. A backup that fails to restore is a deeper issue than the test surface suggests; it indicates that the actual recovery scenario would have failed. Such findings receive immediate priority.

## Dependencies and their disaster scenarios

Several external dependencies have their own disaster scenarios that affect ZeroKey's posture.

**LHDN MyInvois** could itself experience disaster. Our response is to queue submissions and continue customer-facing operations gracefully. We do not have control over LHDN's recovery. We monitor their status and resume submissions when they recover. Customers are kept informed.

**Stripe** could experience extended outage affecting our billing. We have processes for handling delayed payment posting and can extend customer service through the outage without billing pressure on them. After recovery, billing reconciliation catches up on any missed transactions.

**AI engine vendors** experiencing simultaneous outage is unlikely given our diversification, but possible. The local PaddleOCR fallback handles OCR; for language model fallback during a multi-vendor outage, we degrade to a simpler text-based extraction without LLM enrichment, which produces lower quality but functional output. Customers see a clear status banner.

**Cloudflare** outage would prevent traffic from reaching us. This is rare but has happened in the past. During such events, we cannot do much technically; we communicate via alternate channels (email, social media) and wait for Cloudflare recovery.

**AWS provider-level disaster** affecting both `ap-southeast-5` and `ap-southeast-1` would be a substantial event. Our backups in S3 are replicated cross-region but if both AWS regions are down, recovery to a different cloud provider is theoretically possible but not architected as a defined procedure for v1. Custom-tier customers with specific requirements may negotiate multi-cloud redundancy.

## Communication during disasters

The communication discipline during disasters is documented separately because it is one of the most important aspects of customer-facing recovery.

**Status page updates** happen at least every 30 minutes during an active incident, even when the update is "we are still working on this, no new information." Silence is worse than honest "we are still working."

**Customer email** is sent at incident declaration, at significant milestones (failover initiated, failover complete, full recovery confirmed), and at the post-mortem.

**In-product banners** appear on the dashboard for active customers during incidents, with the key information visible at a glance.

**Direct support outreach** to enterprise and Custom-tier customers happens via their dedicated support channels for any incident with significant impact.

**Post-incident communication** includes a public post-mortem when impact warranted it, a blog post explaining what happened and what we are changing, and individual follow-up to severely affected customers.

## How this document evolves

When the architecture changes, this document is updated to reflect the new disaster recovery posture. When a new failure scenario is identified (often through a near-miss or an industry incident), the scenario is added to the planning. When a recovery objective changes, this document captures the change with a date.

When a disaster recovery exercise reveals a gap, the gap is closed and this document is updated.

When customers ask "what happens if AWS goes down?" or "what is your RTO?" or "have you tested your backups?", the answers come from this document. We are honest about our posture; we do not claim recovery capabilities we have not tested.
