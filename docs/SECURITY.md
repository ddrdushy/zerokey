# SECURITY — ZeroKey

> The security posture, controls, and discipline that let us be trusted with regulated invoice data and customer signing keys. This document is the authoritative reference for how we protect customer data, what we hold and what we do not, and the institutional practices that keep our security posture honest over time.

## Security philosophy

ZeroKey is built to BFSI standards from the first commit, even though the launch customer is an SME owner. This is not over-engineering; it is strategic discipline. Retrofitting security into a system that was not built for it is a multi-year project that often fails. Building it in from day one is comparatively cheap, and the resulting posture lets us serve enterprise customers from year two onward without rebuilding.

Five principles govern every security decision.

The first principle is **least data**. We hold only what we need, only as long as we need it, and only in the form we need it. Every field we collect from a customer is justified against this principle. Every retention period we set respects it.

The second principle is **least privilege**. Every person, every service, every credential has only the access required for its specific function. No service has database superuser privileges. No staff member has access to all customer data by default. No API key carries permissions beyond its declared scope.

The third principle is **defense in depth**. No single control is treated as sufficient. Application-layer permission checks plus database-layer Row-Level Security. Network-layer isolation plus encryption in transit. Edge-layer WAF plus application-layer input validation. When a single layer fails, others catch the failure.

The fourth principle is **the customer's keys are not our keys**. Customer signing certificates live in hardware-backed key management infrastructure with isolated access. We are custodians, not owners. This is a structural commitment baked into the architecture, not a policy we hope to follow.

The fifth principle is **honesty about what we do**. Our security posture is what we publish in our security documentation. If we do not yet have ISO 27001 certification, we say so. If a control is in implementation but not yet operational, we say so. The cost of a discovered exaggeration is far higher than the cost of an honest gap.

## Threat model

The threats we design against, in approximate order of likelihood and severity.

**Unauthorized access to customer data through cross-tenant leakage** is the foundational threat. A bug in application logic that fails to filter by tenant could expose one customer's invoices to another. Defense: PostgreSQL Row-Level Security enforces tenant isolation at the database layer, independent of application logic. Application bugs cannot leak data the database refuses to return.

**Compromise of customer signing certificates** would let an attacker forge LHDN-validated invoices on behalf of customers. Defense: certificates are stored as envelope-encrypted blobs in S3 with KMS-backed envelope keys. Decryption requires KMS access, which is logged. The signing service that uses certificates is isolated from the rest of the application. Compromise of any non-signing component does not yield certificate access.

**Credential leakage through source code** is a common SaaS failure mode (a credential committed to a public repo, an API key in a Docker image layer). Defense: secrets are never in source code. They are stored in AWS Secrets Manager and retrieved at runtime. Pre-commit hooks scan for accidental commits of secret-shaped strings. Periodic audits of source for leaked credentials.

**Credential leakage through logs** is another common failure: logging a request that includes an Authorization header, logging a database query that includes a password. Defense: structured logging with explicit field-level redaction. Sensitive field names are configured in a central allowlist, and the logging framework refuses to log values for those fields without explicit `redact=False` (which requires code review).

**API abuse and credential stuffing** against authentication endpoints. Defense: edge-layer rate limiting through Cloudflare, application-layer rate limiting per-IP and per-user, exponential backoff on failed authentication attempts, mandatory two-factor authentication option, account lockout after sustained failures, monitoring for anomalous login patterns.

**Phishing of customers leading to account compromise**. Defense: mandatory two-factor authentication (optional for users, but configurable as required at the Organization level for higher-tier customers), magic-link login as an alternative to password, security alerts for logins from new devices or unusual locations, customer-facing security dashboard showing active sessions and recent security-relevant events.

**Internal staff abuse of access** is the threat that often goes unaddressed. Defense: every staff access to customer data is audit-logged with the staff identity, the customer affected, the reason given, and the actions taken. Staff access requires reason codes for sensitive operations. Customer-impersonation requires explicit configuration with scope limits. Periodic audits of staff access patterns. The principle is that staff convenience is subordinated to customer trust; access is a privilege that is logged and reviewable.

**Compromised AI engine vendors** is a newer threat shape. If an OCR or LLM vendor were compromised, attackers could potentially see invoice data sent to them. Defense: minimum-data prompts (we send what is needed for extraction, not the full document where text-only would suffice), engine routing diversification (no single vendor sees all our traffic), contractual data-handling commitments from each engine vendor, and the engine registry's ability to remove a compromised vendor on short notice.

**Supply chain compromise** through a malicious dependency in our own software stack. Defense: dependency pinning with hash verification, automated vulnerability scanning, regular dependency review, minimization of transitive dependencies, code review of any new top-level dependency.

**Insider threat from compromised developer machines** that could push malicious code. Defense: branch protection on main branch, required code review on all changes, signed commits, principle of least privilege on developer credentials, separation of development credentials from production credentials.

**Physical infrastructure compromise** of AWS data centers. Defense: this is largely AWS's responsibility, addressed through AWS's published security certifications. We rely on AWS's controls for physical security, hardware integrity, and infrastructure availability.

**Regulatory data demands** from authorities seeking customer data. Defense: clear policies on response to lawful requests, customer notification where legally permitted, minimum-necessary disclosure, and retention only of data we are required to retain.

## Identity, authentication, and access control

### User authentication

Customer users authenticate via one of three paths. Email and password authentication uses bcrypt for password hashing with a configurable work factor (currently 12). Passwords are never stored in plaintext, never logged, and never returned by any API endpoint. Magic-link authentication generates a short-lived token, sends it via email, and accepts the token in lieu of a password. SSO authentication uses SAML 2.0 or OpenID Connect against the Organization's configured identity provider, available on Pro tier and above.

Two-factor authentication is supported via TOTP (compatible with Google Authenticator, Authy, 1Password, and similar apps) and is offered to all users. Higher-tier customers can configure 2FA as required for their Organization, blocking login without it.

Sessions are managed through Django's session framework with sessions stored in Redis. Session cookies are httpOnly, Secure, and SameSite=Lax. Session inactivity timeouts are configurable per Organization with a default of 24 hours.

Failed login attempts trigger progressive delays and eventual account lockout. The lockout is automatic and includes notification to the user with a reset path.

Device tracking records the IP address, user agent, and approximate location of each session. Logins from new devices trigger an email notification. Users can review and revoke active sessions from their security settings.

### API key authentication

API keys are first-class credentials with their own scopes. Detailed in `API_DESIGN.md`. From a security standpoint: keys are never retrievable after creation (only a hash is stored), keys are scoped to subsets of permissions, keys are rotatable and revocable, and key usage is audit-logged.

Keys for Custom-tier customers can be IP-allowlisted: requests from outside the configured IP range are rejected at the edge.

### Authorization

Role-based access control with permissions enforced at the service layer. Detailed in `DATA_MODEL.md`. From a security standpoint: every protected operation declares its required permission, the permission check is centralized in middleware that cannot be bypassed by individual endpoint code, and permissions are checked against the actual session identity (or API key scope), not against any header or parameter the client could spoof.

### Multi-tenant isolation

PostgreSQL Row-Level Security is the foundation. Every customer-scoped table has an RLS policy that filters rows by a session-set tenant variable. The Django middleware sets this variable at the start of each request based on the authenticated session's organization context. A bug in application code that constructs an unfiltered query still cannot return another customer's rows; the database refuses.

Application-layer checks complement the database layer. Service functions verify that the current tenant matches the requested resource. The two layers are independent.

Cross-tenant operations (such as platform-wide analytics) require explicit super-admin context, set through a different mechanism with full audit logging.

## Cryptographic key management

### Customer signing certificates

The most sensitive material in the system. Certificates are issued to customers by LHDN as part of their MyInvois registration. Customers upload the certificate file once during onboarding.

On upload, the certificate file is encrypted using a customer-specific data encryption key (DEK). The DEK is itself encrypted using a customer-specific key encryption key (KEK) managed by AWS KMS. The encrypted certificate blob is stored in S3 with object-level encryption layered on top using the bucket's KMS encryption.

When a signing operation is needed, the signing service retrieves the encrypted blob from S3, calls KMS to decrypt the DEK, decrypts the certificate, applies the signature, and immediately discards the decrypted certificate from process memory. The decrypted form never persists outside the signing service's runtime context.

KMS access is logged through CloudTrail. Every decrypt operation is recorded with the requesting service identity, the timestamp, and the key reference. Anomalous patterns (decrypt operations outside expected hours, decrypts from unexpected service identities) trigger alerts.

The signing service's IAM role grants only `kms:Decrypt` on the customer certificate KEKs and read-only S3 access to the customer-certificates prefix. It does not have database access. It does not have internet access except to KMS. The blast radius of a compromise is bounded.

### Field-level PII encryption

Personally identifiable information stored at rest in PostgreSQL is encrypted at the field level using KMS-backed keys. This includes email addresses, phone numbers, and full physical addresses. The encryption is application-managed; PostgreSQL sees ciphertext.

The KEK for field-level encryption is rotated periodically. Rotation is a deliberate operation that re-encrypts existing data with the new key in a background job; old keys are kept long enough for in-flight data to be decryptable.

This control is layered on top of disk-level encryption (RDS-managed encryption at rest, S3 bucket encryption). The field-level layer protects against threats that could see the database content but not access KMS.

### TLS everywhere

All traffic is encrypted in transit. Edge to client uses TLS 1.3 with strong cipher suites configured in Cloudflare. Cloudflare to load balancer uses TLS 1.3 over a private connection. Load balancer to application uses TLS within the VPC. Application to database, Redis, and other internal services uses TLS where the underlying service supports it.

Certificate management for our public domains is handled through Cloudflare for edge certificates and through AWS Certificate Manager for internal certificates.

### Secret rotation

Secrets in AWS Secrets Manager are rotated according to defined schedules. Rotation is automated where the underlying service supports it (database passwords, IAM credentials). Where rotation requires coordination (third-party API keys, SSO certificates), the rotation is a documented procedure with overlap windows so production traffic is never affected.

## Network security

### Edge layer

Cloudflare is the only public-facing surface. All inbound traffic flows through Cloudflare's WAF, which applies the OWASP Core Rule Set plus ZeroKey-specific rules.

Rate limiting at the edge applies per-IP and per-API-key limits. Authentication endpoints have tighter limits than read endpoints.

Bot management at the edge identifies and challenges known bot patterns. CAPTCHAs are presented to suspicious traffic without affecting legitimate user flows.

DDoS protection is built into Cloudflare's standard offering. Our origin is protected against direct attack because the origin is not publicly addressable; only Cloudflare can reach it.

### VPC architecture

Our AWS infrastructure runs in a dedicated VPC with strict network segmentation. Public subnets hold only the load balancer; nothing else is publicly addressable. Private subnets hold the application tier, the work tier, and the data tier, each with security groups limiting traffic to only what is required.

The database, Redis, and Qdrant are reachable only from the application and work tiers. The signing service runs in its own subnet with even tighter security group rules. Outbound internet access from private subnets is mediated through NAT gateways with logging enabled.

VPC flow logs are enabled and retained for forensic capability.

### Service-to-service authentication

Within the VPC, services authenticate to each other using IAM roles where the AWS resource model supports it (S3, KMS, Secrets Manager) or short-lived service tokens otherwise. No long-lived credentials are baked into containers.

## Application security

### Input validation

Every API endpoint validates inputs strictly. Type mismatches, malformed JSON, missing required fields, and oversized payloads are rejected with structured error responses.

Validation uses a library-based approach (Django REST Framework serializers, with additional schema validation where needed) so that the validation logic is centralized and consistent. Hand-written validation in individual endpoint code is forbidden.

### Output encoding

Every output that could be displayed in a browser is HTML-encoded by default. The Next.js frontend uses React's automatic escaping for any string interpolation; bypassing this requires explicit `dangerouslySetInnerHTML`, which is reviewed in code review.

Email content is rendered through templates that escape user-supplied values. Subject lines are bounded to prevent header injection.

### CSRF protection

All state-changing operations from the browser require a CSRF token. The token is bound to the session and verified server-side. The token is delivered through a cookie and submitted in a header, following the double-submit cookie pattern.

API endpoints authenticated with API keys are not vulnerable to CSRF (API keys are not automatically sent by browsers) but the authentication path itself is verified to ensure session-based and key-based auth do not inadvertently mix in dangerous ways.

### SQL injection

The Django ORM handles parameterization for all database queries. Raw SQL is forbidden by code review unless absolutely necessary, in which case parameterization is verified.

### File upload safety

Uploaded files are virus-scanned (using ClamAV or a managed equivalent) before processing. Files are stored in S3, never on application servers. Filenames are not used directly; uploaded files get system-assigned identifiers and the original filename is stored as metadata.

PDF and image processing libraries are kept current with security updates. Known PDF parsing vulnerabilities are tracked, and our processing pipeline runs in isolated worker containers that limit blast radius if a malicious file triggers a parser exploit.

### Session security

Sessions are httpOnly, Secure, SameSite=Lax cookies. Session IDs are cryptographically random, sufficiently long, and rotated on privilege escalation (such as 2FA completion).

Sessions can be revoked by the user (from the security settings) or by the system (on password change, on detected anomaly, on staff override).

## Compliance certifications

ZeroKey's compliance posture is intentional and progressive.

**PDPA Malaysia compliance** is required from day one. Detailed in `COMPLIANCE.md`. We have appointed a designated PDPA contact, published a privacy notice, established data subject access procedures, and built the data deletion pipelines required for the right-to-erasure.

**ISO 27001 certification** is targeted for completion in year two. The information security management system is designed from day one to satisfy the standard, with formal certification undertaken once the operational track record is sufficient. This is the most important certification for enterprise sales and for BFSI procurement.

**SOC 2 Type II** is targeted for completion in year two or three, after ISO 27001. SOC 2 is more US-market relevant; ISO 27001 is more globally relevant. Both are pursued because Custom-tier customers may require either or both.

**LHDN's software intermediary registration** is the basic regulatory registration required to submit to MyInvois on customers' behalf. Held from before launch.

We do not claim certifications we do not have. Our public security page lists current state honestly: "ISO 27001 in progress, target completion Q2 2027" rather than implying we are already certified.

## Vulnerability management

We maintain a vulnerability management program with the following components.

Automated dependency scanning on every build. Critical and high-severity findings block the build. Medium findings are tracked with a remediation timeline.

Automated container image scanning. Images are scanned at build time and continuously while in production registries. Findings flow into the same triage system.

Quarterly external penetration testing once we have customers. The report is confidential but the executive summary is shareable on request to enterprise prospects under NDA.

A public security disclosure policy and a bug bounty program. We commit to acknowledging reports within one business day, providing a substantive response within five business days, and rewarding qualifying researchers fairly. Detailed in our public security.txt.

A documented incident response procedure with defined roles, communication paths, and post-incident review. Detailed in `OPERATIONS.md` under "Security incident response."

## Audit logging

Every action that affects customer data is recorded to the immutable hash-chained audit log. This is the foundation of our auditability story for ourselves, our customers, and any regulator who asks.

Detailed specification of the audit log is in `AUDIT_LOG_SPEC.md`. From a security standpoint: the log is append-only at the database level (RLS prevents UPDATE and DELETE for any tenant role), the chain integrity is cryptographically verifiable, and exports are tamper-evident.

Customer access to their own audit log is full and self-serve. Staff access to a customer's data is itself audit-logged. Aggregate access patterns are monitored for anomalies.

## Data residency

All customer data is stored in the AWS Asia Pacific (Malaysia) region (`ap-southeast-5`). Backups are replicated to the AWS Asia Pacific (Singapore) region (`ap-southeast-1`) for disaster recovery. Backups are encrypted with KMS keys that exist in the destination region.

Cross-region data movement is documented and limited to disaster-recovery scenarios. Customers on Custom tier can request region-specific contracts that further constrain data location.

We do not move data to other regions for cost optimization or operational convenience. Data residency is a customer commitment, not a flexible parameter.

## Customer-facing security features

Several controls are exposed directly to customers.

**Active session review** lets a user see all sessions currently logged into their account with device, location, and last activity. Any session can be revoked.

**Login history** shows recent authentication events with success or failure, source IP, and user agent.

**Security alerts** notify the user via their preferred channel when a login from a new device occurs, a password is changed, an API key is created or revoked, or a 2FA setting changes.

**API key audit** lets the customer see all active API keys, their scopes, their creation timestamps, their last-used timestamps, and revocation history.

**Data export** lets the customer download their full data set at any time. This is also the right-to-portability response under PDPA.

**Account deletion** lets the customer trigger the full deletion pipeline. Deletion is sequenced and confirmed; the customer is notified at each milestone.

## Internal security disciplines

The team disciplines that keep our security posture honest.

**Security review** is required for any new feature that introduces new authentication paths, new credential storage, new external integrations, or new data sharing. The review is documented in the pull request.

**Code review** is required on every change. Reviewers check for common security issues using a checklist that has evolved over time.

**Dependency review** is required when adding any new top-level dependency. The reviewer confirms the dependency's maintenance status, license, and security record.

**Periodic access review** of staff and service permissions. Quarterly, every staff member's access is reviewed against their current role and unnecessary permissions are removed.

**Incident reviews** after every security-relevant incident. The review identifies the root cause, the immediate fix, the systemic improvement, and any process gap that allowed the incident to occur.

**Annual security training** for all staff covering social engineering recognition, secure coding practices, incident reporting, and PDPA obligations.

**Tabletop exercises** quarterly to rehearse incident response. Scenarios include credential leakage, customer data exposure, ransomware, and insider threat.

## How this document evolves

When a new security control is implemented, this document is updated to describe it. When a control is changed or replaced, this document is updated. When a threat is identified that we did not previously consider, the threat model section is expanded.

When this document and the actual security state diverge, one is wrong. Either the document is updated to reflect the new state, or the state is brought back into alignment with the document. Drift in security documentation is itself a security finding.

When customers, prospects, or auditors ask security questions, the answers come from this document. Our public security page summarizes this document at a high level; the full document is shared with serious enterprise prospects under NDA.
