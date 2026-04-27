# CLAUDE CODE GUIDE — ZeroKey

> How to work effectively with Claude Code on this codebase. ZeroKey is being built by a solo founder with Claude Code as the primary engineering collaborator. This document captures the practices that make that collaboration produce coherent, high-quality output session after session.

## Why this document exists

A solo build accelerated by AI engineering is a new category of software development. The patterns from team engineering apply partially. The patterns from solo engineering apply partially. The combined practice has its own discipline that is still being figured out.

This document captures what we know works for ZeroKey specifically. It is not generic Claude Code advice; it is the operating manual for this codebase, this domain, and this collaboration style.

It is written primarily for the founder (the human side of the collaboration) but is intended to be read by Claude Code at the start of every session so the AI side internalizes the conventions too.

## The foundational pattern

Every session with Claude Code on this codebase follows the same opening pattern.

The session begins with Claude Code reading `START_HERE.md` and `PRODUCT_VISION.md` from the documentation. These two files establish the unmovable foundation: what ZeroKey is, who it serves, and what it stands for. No subsequent decision should contradict these documents.

Based on the task at hand, Claude Code then reads the relevant subset of additional documents per the loading patterns described in `START_HERE.md`. Working on authentication? Read `SECURITY.md`. Working on LHDN integration? Read `LHDN_INTEGRATION.md`. Working on UI? Read `UX_PRINCIPLES.md` and `BRAND_KIT.md`. The loading is targeted; not every session needs every document.

This loading discipline is the difference between coherent compounded work and a series of disconnected sessions. Without it, every session re-derives architectural decisions from scratch and they drift in different directions. With it, every session inherits the same foundation.

## The conventions Claude Code follows

Several conventions apply across the codebase. These conventions exist so that any session can build on any other session without resolving conflicts about style or pattern.

### Code style

Python code follows the Black formatting style with a line length of 100 characters. Linting is via Ruff with a strict configuration. Type hints are required on all public functions and recommended on all internal functions. Mypy is run as part of CI in strict mode.

JavaScript and TypeScript code follows the Prettier formatting style. ESLint is configured with a strict rule set. TypeScript strict mode is enabled. The Next.js application uses TypeScript exclusively.

SQL embedded in Python code uses the Django ORM by default. Raw SQL is allowed only when ORM expression is impractical and is reviewed for parameterization correctness.

### Naming

Entity names use the singular form (Invoice, not Invoices) consistent with `DATA_MODEL.md`. Service classes are named `<Domain>Service` (`InvoiceService`, `BillingService`). Function names start with verbs that describe what the function does, not where it is called from. Variable names are descriptive even when verbose; `customer_master_record` is preferred to `cmr`.

Test names follow the convention `test_<function_under_test>_<scenario>_<expected_outcome>`. A failing test name should communicate what was expected and what scenario was being tested.

API endpoint paths follow REST conventions per `API_DESIGN.md`. Internal helper endpoints are clearly distinguished from the public API.

### File organization

Files are organized by domain, not by technical layer. The `invoices` app contains everything related to invoices: models, services, serializers, views, tasks, tests. The `billing` app contains billing concerns. This domain-based organization makes it easier to reason about a feature end-to-end.

Within an app, there is a consistent file structure: `models.py` for data, `services.py` for business logic, `serializers.py` for API shapes, `views.py` for the controller layer, `tasks.py` for Celery work, `tests/` for tests.

### Error handling

Errors are first-class. Every error has a stable code defined in a central error-codes module. Errors raised internally include enough context for debugging without leaking sensitive data into logs. Errors returned to API clients follow the structured format from `API_DESIGN.md`.

Exception handling is purposeful. Bare `except:` clauses are forbidden. Catching general `Exception` is allowed only at the outermost layer of a request or task, where it logs the unexpected error and returns a structured 500 response.

### Testing

New code requires tests. The test discipline is described in detail in the dedicated section below.

### Commits and pull requests

Every commit is small and self-contained. A commit that mixes unrelated changes is rebased into multiple commits before merge. The commit message is a clear sentence stating what changed and why; it is not a summary of the diff.

Pull requests are small. A pull request that touches more than 500 lines is reviewed for whether it could be split. The review discipline (described below) applies even though the team is small.

## How Claude Code is asked for work

The way the human partner formulates requests significantly shapes the output quality.

A productive session typically starts with a clear problem statement, the relevant context references (which documentation to consult), and the criteria for done. For example: "Implement the password reset flow per Journey 1 in `USER_JOURNEYS.md`. The flow should follow the magic-link pattern from `SECURITY.md`. The done criteria are: user can request a reset, receives an email with a magic link, clicks the link to set a new password, and the audit log captures every step."

This framing gives Claude Code three things: a specific task, the documents to consult for any decisions, and the test of completion. With these, the output is coherent with the rest of the codebase.

A less productive framing — "build password reset" — leaves too many decisions implicit. Claude Code may reach a reasonable answer, but the answer may differ subtly from the conventions established in the documentation. Multiple such sessions accumulate drift.

The discipline for the founder is therefore to formulate requests with intentional context. The investment in the request pays off in the coherence of the output.

## How Claude Code's output is reviewed

Even though there is no traditional team code review, output is still reviewed. The reviewer is the founder, possibly with another instance of Claude Code as a second perspective.

The review checks whether the change matches the documentation, whether tests are present and meaningful, whether error handling is appropriate, whether the change has appropriate logging and observability, whether security implications have been considered (using the threat model from `SECURITY.md`), and whether any conventions have been violated.

The review is not a rubber stamp. Disagreements are surfaced explicitly. If the documentation is wrong (it sometimes is, as the codebase evolves), the documentation is updated before the code change is finalized.

A second instance of Claude Code reviewing the first instance's output is a useful pattern. The reviewer instance is given the same documentation context but framed as a critic: "Here is the change. Identify any issues, drift from documentation, missed cases, or improvements." This second-pass reading often catches subtleties.

## Testing discipline

Testing is taken seriously because a regulated SaaS product cannot have undetected bugs in compliance-relevant paths.

### Test categories

**Unit tests** cover individual functions and classes in isolation. They are fast (the full unit test suite runs in seconds), deterministic, and focused. Mocking is used for external dependencies. The unit test suite is the first line of defense.

**Integration tests** cover the interaction between multiple components. They use a real PostgreSQL test database (with the same RLS policies as production), a real Redis instance, and stubbed external services for AI engines and LHDN. Integration tests are slower (the full suite runs in a few minutes) but catch issues unit tests miss.

**End-to-end tests** cover full user journeys through the API. They start a real Django server and Next.js frontend, exercise the full stack, and verify the user-visible behavior. They are slow (several minutes per run) and run on a more limited cadence — every PR for the critical paths, every nightly build for the full suite.

**LHDN sandbox tests** are integration tests that hit LHDN's actual sandbox. They run nightly rather than per-commit because LHDN's sandbox has rate limits and we should not exhaust them. These tests are the final gate for any change touching the submission path.

**Audit verification tests** run the audit chain integrity verification against a generated test workload. These ensure the audit log infrastructure remains correct as it evolves.

### Test data

Test data uses synthetic Malaysian invoices generated by a fixture-building utility. The fixtures cover the major variations: native PDFs, scanned PDFs, images, multi-language documents, edge cases (very long line items, unusual formatting, edge of the LHDN field constraints).

The test corpus grows over time as we encounter customer invoice formats that revealed gaps. Adding to the corpus is part of bug-fix workflow: when a customer's invoice failed extraction, an anonymized version of the invoice is added to the test set so the regression cannot recur.

Real customer data never enters the test environment. Anonymization is applied carefully: names, addresses, and identifying numbers are replaced with synthetic equivalents that preserve the structural properties of the original.

### Test coverage targets

We do not enforce a percentage coverage target. Coverage percentage is a poor proxy for test quality; chasing high coverage often produces shallow tests. Instead, we evaluate test coverage qualitatively: is every meaningful branch tested? Are the error paths tested? Are the security-relevant paths thoroughly tested?

Code review explicitly checks whether tests are meaningful. A pull request with high test coverage but trivial tests is sent back.

## Working on specific domains

Different domains in the codebase have their own gotchas. This section captures the most important ones.

### Working on authentication and identity

The authentication code is high-stakes. Mistakes here can compromise customer data. Several specific disciplines apply.

Never log credentials, even hashed ones. The logging filter has a redaction allowlist for this; verify any new logging in this area respects it.

Always use the centralized password hashing (Django's built-in) rather than rolling new hashing logic. Never compare passwords with anything other than the constant-time comparison Django provides.

Two-factor authentication code paths are subtle. Test that 2FA cannot be bypassed by reusing pre-2FA session state. Test that account lockout interacts correctly with 2FA.

Sessions are sensitive. Test session revocation. Test that privilege changes (such as completing 2FA) result in session ID rotation.

### Working on LHDN integration

LHDN integration is high-stakes for a different reason: a bug here means our customers cannot meet their compliance obligations. Several disciplines apply.

Read `LHDN_INTEGRATION.md` carefully before any work on this path. The specification is detailed and the edge cases are subtle.

The schema validation rules are stable but not eternal. When LHDN updates the specification, the validation logic is updated and the change is captured in `ValidationRuleVersion` so historical invoices can be audited against their original validation context.

The submission path must be idempotent. A retry due to a network failure must not produce a duplicate submission to LHDN. The idempotency key handling in the submission queue is the mechanism; verify it works after any change to the submission code.

The seventy-two-hour cancellation window is a specific LHDN rule. Cancellation logic must respect it; testing must verify both within-window and after-window cases.

### Working on the engine registry

The engine registry is where vendor risk concentrates. Several disciplines apply.

New engine adapters must implement the capability interface fully, including error handling for the vendor-specific failure modes. Read the existing adapters as templates.

Engine routing rule changes affect production traffic. Test changes in shadow mode (running the new rule alongside the old, comparing outputs without affecting customers) before promotion.

Engine call logs are the source of truth for cost and quality analysis. Ensure new engine adapters emit logs in the standard shape.

### Working on the audit log

The audit log is the most sensitive subsystem. Mistakes here can break the integrity guarantee that we sell to customers as foundational. Several disciplines apply.

Never modify or delete an existing audit event from application code. The RLS policies prevent it at the database level, but application code should also not attempt it.

When adding a new audit event type, define the canonical payload schema explicitly. Include the schema version so future evolution is possible.

When changing the canonical serialization, treat it as a chain version transition with all the implications described in `AUDIT_LOG_SPEC.md`.

The signing key is held in KMS. Application code never sees it. Signature production happens through KMS API calls. If you ever find yourself wanting direct access to the signing key, stop and reconsider.

### Working on multi-tenancy

The Row-Level Security policies are the substrate of multi-tenant isolation. Several disciplines apply.

Every new customer-scoped table requires an RLS policy. Migrations that add such tables without policies are rejected at code review.

Application-layer queries should always filter by tenant explicitly even though RLS would do it. Defense in depth.

Cross-tenant operations (such as platform analytics) require explicit super-admin context. Never use a `bypass-RLS` shortcut except in the well-defined places that need it.

Multi-tenant tests should verify isolation explicitly: create data in one tenant, attempt to read it from another tenant context, confirm zero rows returned.

### Working on the frontend

The frontend has its own conventions described in `VISUAL_IDENTITY.md`. Several additional conventions apply.

The frontend is built in Next.js with TypeScript. Components use shadcn/ui as the design system. Tailwind CSS provides utilities. Custom CSS is rare and reviewed.

State management is local where possible (component state, URL state, server state via React Query). Global client state is minimized. We do not use Redux or similar large state libraries.

Accessibility is not optional. Every interactive element has accessible labels. Color contrast meets WCAG AA. Keyboard navigation works. Screen reader testing is part of the QA pass on customer-visible features.

Internationalization is built in from the start. Strings are externalized into the i18n system. The four languages (English, Bahasa Malaysia, Mandarin, Tamil) are first-class.

## Anti-patterns to avoid

Several patterns are tempting in solo+AI development and should be avoided.

**Implementing without reading the docs first.** The temptation to "just write the code" skips the most important step. Without the documentation context, the output drifts.

**Deferring tests to "later".** Later does not arrive in solo development. Tests written immediately catch bugs and protect against regressions; tests written eventually never get written.

**Letting documentation drift from reality.** Documentation that no longer matches the code is worse than no documentation, because it actively misleads. When code changes, the relevant documentation changes in the same pull request.

**Single-purpose helper functions that proliferate.** A new helper for every slightly different need leads to a sprawling utility module. Look for existing helpers before adding new ones; consolidate when patterns emerge.

**Premature optimization.** Optimizing code that is not yet on the critical path wastes effort. Profile, identify the actual hotspots, optimize those.

**Premature generalization.** Building extension points for needs that have not yet emerged usually produces the wrong abstractions. Build the specific case; refactor when the second similar case appears.

**Configuration sprawl.** Adding config options for every conceivable variation makes the system complicated to operate. Add configuration only when there is real evidence of needing the variation; otherwise, hardcode the sensible default.

**Mixing concerns across layers.** A view that does database queries directly, a service function that constructs HTTP responses — these mix the layers and make the code hard to reason about. Keep concerns where they belong.

## How this document evolves

When a new convention is established, this document is updated. When an anti-pattern is discovered (often through a bug it caused), this document captures it.

When the founder's working pattern with Claude Code shifts, this document captures the new pattern. Solo+AI development is a new practice and we are learning what works as we go.

When this document and actual practice diverge, the divergence is investigated. Either the document captures a pattern we have outgrown (update it) or the practice has drifted (correct it).

This document is read at the start of every Claude Code session along with `START_HERE.md`. The combined orientation takes a few minutes and saves hours of drift over the course of the session.
