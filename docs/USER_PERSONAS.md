# USER PERSONAS — ZeroKey

> Six personas. The first four are external customers. The fifth is a partner archetype. The sixth is internal. Each persona is a real shape of a real human we are designing for, not a marketing fiction. When a design decision is contested, we ask: which persona benefits, which is harmed, and is that the right trade?

## How to use these personas

Personas are not customer segments and they are not market sizing. They are the human anchors we hold in our heads while we design. A single Malaysian SME owner, a single bookkeeper in Klang, a single procurement officer at a BFSI institution — these are the people whose lives are made better or worse by every decision we make.

Each persona below has a name (used internally as shorthand only — do not invent quotes from these names in marketing materials), a context, the jobs they need to do, the pains they currently live with, the pleasures that would delight them, the channels they prefer, and the explicit pitfalls we must avoid when designing for them.

The personas are ranked by the order in which we acquire them as customers. Aisyah and Wei Lun are the first wave. Priya, Hafiz, and Ravi follow. Sarah is the internal team. We design for Aisyah first, ensure Wei Lun is well-served, accommodate the others, and explicitly do not design for personas not on this list.

## Persona 1 — Aisyah, the SME owner

Aisyah is forty-three and runs a trading and distribution business out of Shah Alam with eight employees and approximately RM 4.5 million in annual revenue. She founded the company twelve years ago, took it through the pandemic, and is now navigating the LHDN e-invoicing mandate that her business fell into when Phase 4 began in January 2026. She speaks English and Bahasa Malaysia comfortably, with some Mandarin from school. She runs her business off a Lenovo laptop, an iPhone, and SQL Account that her bookkeeper installed seven years ago. Her business issues approximately one hundred and twenty invoices a month to a mix of Malaysian wholesale customers and a few Singapore-based buyers.

The jobs Aisyah needs done are practical and bounded. She needs to comply with the LHDN mandate without incurring any penalties. She needs to spend less than thirty minutes a day on invoice administration, including everything from extraction to submission to review. She needs to know that if LHDN ever audits her, she has clean records. She needs to respond to her customers when they ask for an e-invoice for a particular order, ideally within hours rather than days. She needs to understand what her bookkeeper is doing on her behalf without becoming an expert in MyInvois herself.

Aisyah's current pains are real and often unspoken. She is anxious about the penalty regime kicking in January 2027 — anxious enough that she has lost sleep about it twice in the last three months, but not anxious enough to have actually made a decision yet. She has tried the LHDN MyInvois Portal once and gave up after the third validation error she could not understand. She has heard about JomeInvoice from a friend in her business network and is considering it but has not signed up. She is suspicious of any tool that requires her to learn new technology, especially anything that calls itself "AI". She does not want to be sold to and reacts negatively to high-pressure marketing.

What would delight Aisyah is feeling like she has solved a problem rather than acquired a tool. She would love to drag a single PDF onto a screen and have everything happen — including talking to LHDN — without her thinking about it again. She would appreciate a tool that handles her messy reality (some invoices in PDF from her Singapore buyer, some in Excel from her own staff, some scanned because her customer's purchasing department still works on paper) without asking her to standardize. She would love to genuinely understand her own compliance health at a glance without parsing a dashboard full of jargon.

Aisyah's preferred channels are WhatsApp first, email second, web browser third. She uses WhatsApp for almost everything in her business: customer communication, supplier coordination, internal team chat. She checks email maybe three times a day. She opens her laptop on demand for specific tasks rather than working out of it constantly. She is a smartphone-first user even when she is at her desk.

The pitfalls we must avoid for Aisyah are several. We must not require her to understand XML, UBL, schema validation, or any LHDN technical concept. We must not bury our pricing or make her email a sales rep to find out what we cost. We must not force a setup that takes more than ten minutes. We must not pretend her existing SQL Account installation does not exist; it does, and she trusts it more than she will ever trust us in the first month. We must not condescend to her about technology — she has run a successful business for twelve years and is not a beginner at anything that matters. We must not be loud, hyperbolic, or pretend our product is more revolutionary than it is.

When we design for Aisyah, we are designing for the median ZeroKey customer. If a feature does not serve her, we ask twice why we are building it.

## Persona 2 — Wei Lun, the finance manager

Wei Lun is thirty-two and works as the finance manager at a fifteen-person professional services firm in Kuala Lumpur. The firm provides marketing and creative services to mid-market Malaysian and Singapore brands, with annual revenue around RM 8 million. Wei Lun reports to the managing director, who founded the firm. He is responsible for everything finance: invoicing, accounts receivable, accounts payable, payroll, and now LHDN compliance. He is the only person in the firm with finance training (an ACCA qualification he earned in night classes). He speaks English and Mandarin fluently and is comfortable in Bahasa Malaysia for written communication.

The jobs Wei Lun needs done span both his own work and the work he does on behalf of his managing director. He needs to issue and submit between two hundred and three hundred e-invoices a month with high reliability. He needs to maintain audit-grade records that he can produce on demand if their auditor or LHDN asks. He needs to give his managing director real-time visibility into the firm's invoicing health without asking him to read a dashboard daily. He needs to onboard the firm's two junior staff who will eventually take over basic submission work without giving them access to sensitive client data they should not see. He needs to integrate with the firm's existing AutoCount installation rather than replace it.

Wei Lun's current pains are different from Aisyah's. He has the technical competence to use enterprise software but no patience for it. He has evaluated three e-invoicing tools in the last two months and found all of them painful — one required a six-week implementation, one was a glorified data-entry form, and one had pricing that surprised him a month after signup. He is annoyed by SaaS marketing pages that hide their actual capabilities behind "request a demo" buttons. He is responsible for compliance but does not want to become a personal expert on every LHDN error code; he wants the tool to handle the routine ninety percent and surface only the genuine exceptions.

What would delight Wei Lun is a tool that respects his time. He would appreciate a clear pricing page he can read in two minutes and a free trial he can complete without speaking to a sales rep. He would love an exception inbox that is short, clear, and shrinks visibly as he works through it. He would value role-based access that lets his junior staff create invoices but requires his approval before submission, with a clean audit trail of who did what. He would appreciate a webhook integration with his AutoCount setup so that submitted invoices flow back into the accounting system automatically.

Wei Lun's preferred channels are web browser first, email second, Slack third (his firm uses Slack internally). He works at a desk for most of the day and is comfortable with multi-window workflows. He uses his phone for email triage and quick approvals when he is out of the office.

The pitfalls we must avoid for Wei Lun are around respect for his expertise. We must not over-explain in the UI; he reads field labels quickly and does not need extensive hover tooltips for every input. We must not force him to wait for a sales rep to access pricing. We must not require him to call us for technical questions; documentation should be complete and accurate. We must not surprise him with overage charges, plan changes, or terms-of-service revisions buried in long emails. We must not treat him as a beginner; he is a competent professional and our product should match his level.

When we design for Wei Lun, we are designing for the customer who will champion ZeroKey internally and bring in three or four colleagues. He is high leverage.

## Persona 3 — Priya, the external bookkeeper

Priya is fifty-one and runs a small bookkeeping practice in Petaling Jaya with two assistants. She has thirty-two SME clients ranging from small medical clinics to family-owned manufacturing businesses. She has been doing the books for many of these clients for over a decade. She speaks English, Tamil, Bahasa Malaysia, and some Mandarin. She trained as an accountant in the 1990s and is comfortable with financial complexity; she is less comfortable with rapidly-changing software ecosystems and prefers tools that stay stable for years.

The jobs Priya needs done span her entire client portfolio. She needs to handle e-invoicing on behalf of clients who have hired her to manage their compliance. She needs to do this efficiently across thirty-plus clients without losing track of anyone. She needs to maintain clean separation between clients so that data does not cross-contaminate. She needs to invoice her clients for her services (separate from invoicing on their behalf) and have her own LHDN compliance squared. She needs a way to give specific clients visibility into their own status without giving them access to other clients' data.

Priya's current pains are operational. She has tried using the LHDN MyInvois Portal directly for her clients but cannot keep separate sessions cleanly. She has set up SQL Account integrations for some clients and finds the per-client setup tedious. Her two assistants need to help with submission work but she cannot easily give them the right level of access without exposing too much. Her clients sometimes ask for status updates, and she does not have a clean way to share read-only views with them. She is genuinely considering retiring rather than learning a new system, but she has six more years of work in her and would like to spend them serving clients she has known for decades.

What would delight Priya is a single dashboard showing all her clients with their respective compliance status. She would love to add a new client in five minutes and have them up and running. She would value a way to grant her clients read-only access to their own data with a single email invitation. She would appreciate clear branding that lets her tell her clients "I use ZeroKey" without it looking like she is reselling someone else's tool. She would deeply value the option to white-label or co-brand if her practice grows.

Priya's preferred channels are email first, phone second, web browser third. She works from a desktop computer she has had for six years and is wary of upgrading. She uses WhatsApp for client communication but considers it informal. She prefers written documentation over video tutorials.

The pitfalls we must avoid for Priya are around bait-and-switch and complexity. We must not advertise her as a "partner" if our partner program requires complex revenue share or training certifications she does not want. We must not change pricing on her without ample notice; she runs a low-margin practice and any cost increase eats into her bottom line. We must not require her to use the latest browser or the latest version of anything; her tooling is stable and she expects ours to match. We must not condescend to her based on her age — she has more financial expertise in her left hand than most of our team will accumulate in a career.

When we design for Priya, we unlock the accountant and bookkeeper channel. A single Priya brings in thirty clients. Twenty Priyas bring in six hundred customers without any direct marketing.

## Persona 4 — Hafiz, the enterprise procurement officer

Hafiz is thirty-eight and works in procurement at one of Malaysia's tier-two banks. His team is responsible for software vendor selection, contract negotiation, and ongoing vendor management. He has bought enterprise software before, including a multi-million-ringgit contract with an international tax technology vendor that took eleven months to implement. He speaks English and Bahasa Malaysia. His remit is broad: he is responsible for ensuring the bank's vendors meet security, regulatory, and operational standards, and that the contracts the bank signs are commercially sound and risk-managed.

The jobs Hafiz needs done are about institutional compliance, not personal ease. He needs to evaluate ZeroKey against the bank's vendor risk framework. He needs to verify our security posture (ISO 27001 alignment, SOC 2 reports if available, penetration test results, data residency, incident response posture). He needs to verify our compliance posture (PDPA compliance, LHDN registration, data retention policies, audit support). He needs to negotiate commercial terms (uptime SLAs with credits, data export rights, contract termination clauses, liability limits). He needs to ensure the bank's existing vendor management system can ingest our reporting, that our integration work fits within his team's capacity, and that the deployment can pass the bank's security review.

Hafiz's current pains are vendor-management pains. The international tax tech vendor he bought from previously has been slow to respond to his security questionnaire updates. The implementation took longer than promised, cost more than budgeted, and required ongoing escalation to senior management at the vendor. He is wary of any vendor that promises rapid deployment without explaining how. He is sensitive to vendors that try to skip his procurement process by going directly to business stakeholders. He needs the vendor to make his life easier, not harder.

What would delight Hafiz is professional handling of his procurement process. He would appreciate a complete security questionnaire response within a week of his request. He would value reference customers in similar BFSI institutions he can call directly. He would love a clear deployment plan with milestones and dependencies, not a generic implementation Gantt. He would appreciate a vendor who is honest about what they cannot do, rather than promising everything and delivering some of it. He would value the Symprio relationship behind ZeroKey because Symprio is a name his risk team already knows from prior engagements.

Hafiz's preferred channels are email first, scheduled video calls second, secure document portals third. He does not respond to LinkedIn outreach from vendors. He is reachable through warm introductions from existing Symprio relationships, through participation in industry working groups, or through his team's procurement portal. He moves slowly by design; that is his job.

The pitfalls we must avoid for Hafiz are several. We must not pitch ZeroKey to him with the same SME-friendly marketing language that works for Aisyah. We must not skip his procurement process, even if we have a champion at his bank. We must not under-resource his security questionnaire response; a sloppy or incomplete response is worse than a slow one. We must not promise enterprise capabilities we have not yet built; the cost of a discovered overpromise during procurement is years of brand damage in his network. We must not let Symprio and ZeroKey messaging contradict each other in his briefings; one story, one team.

When we design for Hafiz, we unlock the BFSI and government channel. Each Hafiz deal is worth several hundred thousand ringgit annually and requires a separate playbook from SME self-service. He is not the volume customer; he is the credibility customer.

## Persona 5 — Ravi, the technical integrator

Ravi is twenty-nine and works as a developer at a mid-sized Malaysian e-commerce platform that serves over four hundred merchant SMEs. The platform is considering integrating ZeroKey so that merchants can issue LHDN-compliant invoices directly from the platform without leaving it. Ravi is the engineer assigned to evaluate the integration. He speaks English and Tamil, with some Bahasa Malaysia, and is comfortable in any technical context.

The jobs Ravi needs done are integration jobs. He needs to evaluate ZeroKey's API documentation, run test integrations against a sandbox, understand error handling and rate limiting, and produce a feasibility recommendation to his platform's product team. He needs to validate that the integration will work for the platform's merchant volume (potentially thousands of invoices per day in aggregate). He needs to understand the customer-facing implications: what does each merchant need to do to onboard with ZeroKey, who handles which support questions, how does the billing work when the platform pays for the integration but the merchants own their accounts.

Ravi's current pains are common to integrators everywhere. APIs from local Malaysian software vendors are often poorly documented. Sandbox environments are often broken or out-of-date. Webhook delivery is often unreliable. Error responses are often unhelpful. Rate limits are often vague. He has spent multiple weeks fighting integrations that should have taken days.

What would delight Ravi is professional API tooling. Clear, complete documentation with runnable examples. A real sandbox environment with realistic test data. Webhooks with retries, dead-letter queues, and visible delivery logs. Errors with structured codes and human-readable messages. Versioning and deprecation policies that respect his time. A status page that reflects real outages.

Ravi's preferred channels are documentation first, GitHub or community second, email or chat to a developer-advocate role third. He does not want to talk to a sales rep. He wants to read, build, and ship.

The pitfalls we must avoid for Ravi are around treating the API as a second-class citizen. We must not let the API become a thin wrapper over the web app's backend with quirky behaviors and inconsistent naming. We must not break backwards compatibility without versioning and notice. We must not gate our documentation behind a signup wall. We must not require him to email us to get an API key for sandbox; sandbox should be self-serve. We must not over-promise on rate limits and then surprise him with throttling at scale.

When we design for Ravi, we unlock the platform integration channel — every integration with a multi-merchant platform brings in dozens or hundreds of indirect customers. He is the lever that turns ZeroKey from a direct-to-customer product into an infrastructure product.

## Persona 6 — Sarah, the internal super-admin

Sarah is the internal team member who operates ZeroKey day-to-day. In the founding period, Sarah is Dushy himself wearing the ops hat. As the team grows, Sarah becomes a customer success or operations lead. She is a designed persona because the internal surface — the super-admin console, the support tools, the ops dashboard — is a real product that needs the same care as the external surface.

The jobs Sarah needs done are operational and sensitive. She needs to manage plan and pricing configuration as the business evolves. She needs to investigate customer issues with appropriate access controls and full audit logging. She needs to manually retry stuck invoices, waive overage charges, issue refunds, and handle edge cases that the customer cannot self-serve. She needs to monitor system health and respond to incidents. She needs to manage feature flags as new capabilities roll out gradually. She needs to onboard partners and configure white-label arrangements.

Sarah's current pains, if she were a customer of any other internal SaaS admin tool, would be familiar. Most internal admin tools are built as afterthoughts, with poor UX, inconsistent navigation, and missing audit trails. Many require database access for routine operations because the UI does not expose them. Many lack proper role separation, so junior staff have either too much or too little access.

What would delight Sarah is an admin console that is genuinely as well-designed as the customer surface. Clear navigation. Proper audit logging that flows into the same hash-chained log as customer actions. Role-based access control with finely-grained permissions. Bulk operations that are safe by default and require explicit confirmation for irreversible actions. Excellent search across customers, invoices, and events.

Sarah's preferred channels are the admin console itself, supplemented by direct database access for very rare cases, and Slack or email for team coordination. She uses a desktop browser for most work; mobile access to the admin console is nice-to-have but not required.

The pitfalls we must avoid for Sarah are about institutional discipline. We must not let the admin console become a backdoor that bypasses normal access controls. Every action Sarah takes is audit-logged with the same rigor as customer actions. We must not let admin operations become lossy; if Sarah waives an overage charge, the waiver and the reason must be retrievable later. We must not let admin features substitute for product features; if customers need to do something often enough, we build it into the customer surface, not into Sarah's admin console.

When we design for Sarah, we are designing the operating system for the business. Her tools determine how well the rest of the team can serve all the other personas.

---

## Personas we explicitly do not design for

Naming who we serve is incomplete without naming who we do not serve.

We do not design for the curious tinkerer who wants to use ZeroKey API as a hobby project against the LHDN sandbox without becoming a customer. They are welcome to read our public documentation, but our trial flow is built for actual SME use, not for evaluation outside our intended customer profile.

We do not design for the price-only buyer who is comparing twenty options on a spreadsheet and will pick whichever costs five ringgit less per month. Our pricing is set against value delivered, not against the cheapest competitor. If they pick our cheapest competitor, we wish them well.

We do not design for the "I'll integrate everything myself" enterprise that wants ZeroKey as a low-level component in their own custom-built compliance stack. Symprio's consulting arm exists for this profile. ZeroKey is the productized product.

We do not design for businesses below the LHDN mandate threshold. They are exempt. Acquiring them would dilute our positioning and waste resources.

We do not design for users who want ZeroKey to do things outside its defined scope: generic accounting, payment processing, full ERP. We will say no, gracefully, and point to the appropriate adjacent solution.

---

## How personas interact with the rest of the documentation

These personas appear by name throughout the rest of the documentation. When `USER_JOURNEYS.md` describes a flow, the journey is anchored to a specific persona. When `UX_PRINCIPLES.md` is applied to a design decision, the test is whether the principle serves the right persona. When `PRODUCT_REQUIREMENTS.md` lists a feature, the persona who benefits is implicit in the feature's tier and scope.

When a new feature, surface, or decision is being considered, the test is: which persona benefits, by how much, and at what cost to the others. If a feature serves Hafiz at the cost of confusing Aisyah, we redesign or reject. If a feature serves Wei Lun in a way that helps everyone, we prioritize. If a feature serves no persona on this list, it is not a ZeroKey feature.