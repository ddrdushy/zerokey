# COMPLIANCE — ZeroKey

> The legal and regulatory obligations ZeroKey operates under, the controls that satisfy them, and the customer rights we honor. Compliance is treated as a product feature, not as a checkbox exercise. This document is the authoritative reference for what we are obligated to do, what we have committed to do beyond obligation, and how we operationalize each commitment.

## Why compliance is a product feature

ZeroKey handles three categories of regulated data simultaneously. We process tax-relevant invoice data subject to LHDN's regulatory framework. We process personal data subject to Malaysia's Personal Data Protection Act 2010 (PDPA). We hold cryptographic signing material that has legal effect when applied to invoices. Each category brings its own obligations, and the combination puts us in a more regulated position than most SaaS products serving SMEs.

This is a feature, not a burden. Our customers are themselves regulated entities. They want to work with vendors who treat compliance seriously, not vendors who treat it as someone else's problem. A meticulous compliance posture is a moat against less serious competitors and a credibility asset when we sell into BFSI and government.

The disciplines in this document are not aspirational. They are the live operational practices ZeroKey runs every day.

## Regulatory frameworks we operate under

### Personal Data Protection Act 2010 (Malaysia)

The PDPA is the primary privacy law governing personal data processing in Malaysia. It establishes obligations around consent, notice, security, retention, and subject rights. We are subject to PDPA both as a data user (for our own customer relationships) and as a processor (when handling personal data on behalf of customer Organizations).

### LHDN regulatory framework

The Inland Revenue Board of Malaysia governs e-invoicing through MyInvois. The framework includes registration requirements for software intermediaries, data handling rules for tax-relevant information, retention requirements (seven years for tax records), and audit support obligations. We operate as a registered software intermediary.

### Other Malaysian frameworks

Bank Negara Malaysia regulations apply if we ever serve regulated financial institutions (which we plan to). The Cyber Security Act framework, when fully enacted, will establish baseline cybersecurity requirements for designated critical infrastructure. The Anti-Money Laundering, Anti-Terrorism Financing and Proceeds of Unlawful Activities Act applies if we ever facilitate financial transactions (we do not, by design).

### International frameworks (forward-looking)

Customers expanding regionally may bring additional requirements. The European General Data Protection Regulation applies if we serve EU-resident customers. Singapore's Personal Data Protection Act, Indonesia's Personal Data Protection Law, and the Philippines' Data Privacy Act each impose obligations relevant to potential regional expansion. We do not actively serve these jurisdictions in v1, but our controls are designed to be extensible.

## PDPA obligations and how we satisfy them

### Notice and consent

Every customer onboarding flow includes a clear privacy notice describing what personal data we collect, why we collect it, who we share it with, how long we retain it, and what rights the data subject has. The notice is presented before account creation, in the customer's preferred language. Acceptance is recorded with timestamp.

Updates to the notice are communicated to active customers via email with a defined notice period before the changes take effect. Material changes that would affect the customer's consent are accompanied by a re-consent flow.

### Data minimization

We collect only personal data necessary for the purposes we have stated. The customer Organization profile collects company information; individual user profiles collect name and email; invoice processing collects buyer and supplier information from the invoices themselves.

We do not collect data we do not need. We do not run analytics tracking that captures personal browsing behavior beyond what is essential for the product to function. We do not enrich customer data from external sources without explicit consent.

### Purpose limitation

Personal data collected for one purpose is not repurposed for another without consent. The data we collect for invoice processing is used for invoice processing; it is not mined for marketing, repurposed for product development beyond aggregate analysis, or sold to anyone.

The exception is anonymized aggregate analytics: counts of invoices processed, distributions of file types, error rates by category. These are derived from production data but contain no identifiers and cannot be reverse-engineered to specific customers.

### Storage and security

Personal data is encrypted at rest using KMS-backed keys, encrypted in transit using TLS 1.3, and protected by the access controls described in `SECURITY.md`. Field-level encryption applies to particularly sensitive fields like email addresses and phone numbers.

The technical and organizational measures we implement go beyond the PDPA's minimum requirements. We hold ourselves to ISO 27001-aligned controls from launch and pursue formal certification.

### Retention

Personal data is retained only as long as required for the stated purposes or as required by law. Tax-relevant invoice data is retained for the legally required seven years (under Malaysian tax law). Other personal data is retained for the duration of the customer relationship plus a defined period afterward (typically sixty days for read-only access plus full deletion thereafter).

Retention periods are configurable per customer Plan. Custom-tier customers may request specific retention configurations to match their own regulatory or contractual obligations.

### Cross-border transfers

By default, customer data is stored in Malaysia (`ap-southeast-5`) with disaster-recovery replication to Singapore (`ap-southeast-1`). The Singapore replica is not actively accessed and exists only for failover.

Cross-border transfers happen in two operational paths. First, certain AI engine vendors are not headquartered in Malaysia, so prompts containing invoice data may transit through their infrastructure. We minimize the data sent to these vendors and have contractual data-handling commitments from each. Second, our payments processor (Stripe) is headquartered in the United States, so payment metadata transits there.

These transfers are disclosed in the privacy notice. Customers who require Malaysia-only processing can request Custom-tier deployment with engine routing constrained to Malaysia-hosted models and an alternative payments arrangement.

### Data subject rights

PDPA grants individuals specific rights regarding their personal data. We honor all of them through self-serve mechanisms where possible and through a defined support process where not.

The **right of access** is honored through the data export feature. Any user can download their full account data set at any time from their security settings. The export includes everything we hold about them in machine-readable form.

The **right of correction** is honored through the standard product surface. Users can update their profile, their organization details, their preferences. Corrections are logged in the audit trail.

The **right to withdraw consent** is honored through the cancellation flow. Withdrawing consent stops processing within thirty days; full data deletion follows the retention schedule.

The **right to limit processing** is honored on request through support. Specific processing categories (such as marketing communications) can be opted out of in the user's settings. Limitations on essential processing (such as not processing the user's email for service notifications) are not possible while the user has an active account, because the service depends on it; we explain this clearly.

The **right to data portability** is honored through the data export feature in machine-readable formats (JSON and CSV).

The **right not to be subject to automated decision-making** is relevant in our context because some of our processing is automated (extraction confidence scoring affects routing). We disclose this in the privacy notice and provide a path to human review of any automated decision.

### Notification of breaches

PDPA does not yet have a hard breach notification deadline, but our internal commitment is to notify affected customers within 72 hours of confirming a breach that could affect their personal data. The notification includes what happened, what data was affected, what we are doing about it, and what the customer should do.

Notification to the relevant authority is made if the breach meets the regulatory threshold under the prevailing PDPA framework at the time.

The detailed breach response procedure is documented in `OPERATIONS.md`.

## LHDN regulatory compliance

### Software intermediary registration

ZeroKey is registered as a software intermediary with LHDN, authorized to submit e-invoices to MyInvois on behalf of registered taxpayers. The registration is held by Symprio Sdn Bhd as the operating entity for the ZeroKey product.

Registration includes ongoing obligations: keeping our integration current with the published specification, responding to LHDN queries about our customers' submissions when asked, and notifying LHDN of significant operational events that could affect our customers.

### Customer registration verification

Before any customer can submit invoices through ZeroKey, we verify they are themselves registered with LHDN and have a valid digital certificate. The verification includes TIN validation against LHDN's verification API and certificate validation against the LHDN-issued certificate authority.

Customers who are not yet registered with MyInvois are guided through the registration process before they can use ZeroKey for production submissions; the trial environment lets them evaluate the product without LHDN registration.

### Audit support

LHDN may audit any taxpayer's e-invoice submissions. When a customer is audited, ZeroKey provides the audit support specified in `USER_JOURNEYS.md` Journey 8. The customer can self-serve generate an audit package containing every invoice, the original documents, the signed XML, the validation timestamps, and the tamper-evident audit log.

If LHDN directly contacts ZeroKey about a customer's submissions, our response is governed by the customer's underlying authorization. We do not disclose customer data to LHDN beyond what the customer has authorized us to submit on their behalf, except where compelled by lawful order. In the latter case, we notify the customer where legally permitted.

### Data retention

Tax-relevant invoice data is retained for seven years from the invoice date, the period required under Malaysian tax law. The retention applies to the structured invoice data, the original source document, the signed XML, the LHDN UUID and validation timestamp, and the related audit log entries.

After seven years, invoices may be deleted unless the customer's plan specifies a longer retention. Custom-tier customers often configure indefinite retention.

The seven-year retention overrides general PDPA-driven retention for the affected fields. Personal data within an invoice (buyer name, address, contact information) is retained as long as the invoice is retained because deleting it would damage the integrity of the tax record.

## Tax obligations of ZeroKey itself

A meta-loop worth acknowledging: ZeroKey is itself a Malaysian business subject to LHDN e-invoicing obligations for its own customer-facing invoices. We use our own product to generate compliant e-invoices for every subscription fee and overage charge we bill. This is both operationally appropriate and a source of dogfooding — we feel any pain our customers feel.

Sales and Service Tax (SST) applies to our services where applicable. The applicable rate and treatment are configured in our billing system and reflected on customer invoices.

Corporate income tax obligations are handled through our normal financial operations under the Symprio entity.

## Anti-money laundering and counter-terrorism financing

ZeroKey is not a financial institution and does not move money on behalf of customers. The AML/CFT framework applies to a limited extent regarding our customer onboarding (we should know who our customers are) and regarding suspicious activity (we should report patterns that suggest money laundering or terrorism financing).

Our customer onboarding includes verification of the customer's TIN against LHDN's records, which serves as a baseline know-your-customer check. Suspicious patterns we would escalate include attempts to use ZeroKey for activities outside legitimate Malaysian business operations, attempts to obscure the relationship between buyer and supplier, and unusual transaction patterns inconsistent with the customer's stated business.

We do not actively run AML monitoring beyond this baseline because our role does not place us in the financial transaction flow. Our customers' compliance with their own AML obligations is their responsibility, not ours.

## Customer-facing compliance commitments

In addition to regulatory obligations, we make several voluntary commitments to customers.

We commit to notifying customers of material policy changes (privacy, terms of service, security) at least thirty days before the changes take effect, except where shorter notice is legally required.

We commit to supporting customers' own compliance obligations through audit-grade record keeping, machine-readable exports, and prompt response to legitimate audit requests.

We commit to honesty about our compliance posture. We do not claim certifications we do not hold, and our public security and compliance pages reflect current state accurately.

We commit to giving customers a clean exit. Cancellation is three clicks, data export is self-serve and complete, and full deletion follows a defined timeline that is public.

We commit to not selling, sharing, or commercially exploiting customer data beyond what is necessary to operate the service. Aggregated, fully-anonymized statistics may be used for product development, security research, and marketing illustrations (such as "average customer first-submission validation rate"), but raw customer data is not a product input for any third party.

## Compliance management discipline

Several disciplines keep our compliance posture honest over time.

**A designated PDPA contact** is appointed within the company. The contact handles data subject inquiries, breach notification decisions, and regulatory engagement. The contact is publicly listed in our privacy notice.

**An annual compliance review** evaluates our posture against the prevailing regulatory framework and our own commitments. The review identifies gaps, drives remediation work, and is summarized in an internal report.

**Vendor compliance reviews** evaluate every external integration listed in `INTEGRATION_CATALOG.md` against our compliance requirements. New vendors are reviewed before onboarding; existing vendors are reviewed annually.

**Compliance training** for all staff annually covers PDPA obligations, breach reporting, customer data handling, and the boundary between staff convenience and customer trust.

**Customer compliance support** through documentation and direct support helps customers meet their own obligations using ZeroKey. Help center articles cover the audit support flow, the data export flow, the deletion flow, and how to respond if a customer's auditor asks specific questions about our integration.

## How regulatory changes are absorbed

Malaysian tax and privacy frameworks evolve. LHDN publishes specification updates, the PDPA framework is being modernized, and new sectoral regulations periodically emerge.

When a regulatory change is published, the impact is assessed within two weeks. The assessment identifies what new obligations apply, what existing controls need to change, and what timeline applies to compliance. The plan is documented and tracked through completion.

Customer-facing communication accompanies any regulatory change that affects them. We do not expect customers to track regulatory changes themselves; that is part of the value we provide.

## What this document is and is not

This document is the operational compliance reference for ZeroKey. It describes what we do and why. It is not legal advice. It is not a substitute for customers' own compliance obligations. It is not a guarantee that our controls are perfect.

When customers, prospects, or regulators ask compliance questions, the answers come from this document combined with `SECURITY.md` and `DATA_MODEL.md`. Our public compliance page summarizes this document at a high level; the full document is shareable with serious enterprise prospects under NDA.

When a question arises that this document does not answer, the answer is not invented; it is researched, the document is updated, and the customer is given the now-accurate answer. Compliance is not a place to improvise.

## How this document evolves

When a regulation changes, this document is updated. When our controls change, this document is updated. When a customer asks a question that reveals a gap in this document, the gap is filled.

When this document and our actual practice diverge, the divergence is treated as a serious finding. Either the document is updated to reflect the new practice (if the change was deliberate) or the practice is brought back into alignment (if the divergence was accidental). Compliance documentation drift is itself a compliance issue.
