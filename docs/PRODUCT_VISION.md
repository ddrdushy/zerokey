# PRODUCT VISION — ZeroKey

## The one-line vision

ZeroKey makes Malaysian e-invoicing disappear into the background of business so completely that an SME owner can run their company without ever thinking about LHDN compliance again.

## The problem we exist to solve

In 2024, the Malaysian government began the largest forced digitization of business operations in the country's modern history: mandatory e-invoicing through the LHDN MyInvois system. By January 2026, businesses earning between RM1 million and RM5 million annually were brought into the mandate, with penalty enforcement beginning January 2027. Penalties run from RM200 to RM20,000 per non-compliant invoice. Hundreds of thousands of Malaysian small and medium enterprises now face a compliance obligation they are neither equipped nor trained to handle.

The technical reality of MyInvois compliance is brutal for SMEs. Every invoice must be transformed into structured XML or JSON containing fifty-five mandatory data fields, digitally signed using a certificate issued by the Inland Revenue Board, transmitted to the MyInvois platform for real-time validation, and retrieved with a unique identifier and QR code before it can be issued to the buyer. Failed validations return cryptic technical errors. Customer master data must be enriched with verified Tax Identification Numbers and Malaysia Standard Industrial Classification codes. Special rules apply for transactions over RM10,000, foreign suppliers, self-billed scenarios, and consolidated B2C invoices.

The existing market response to this problem falls into two unsatisfying categories. Heavy enterprise middleware solutions exist for large corporations, but they require months of integration work, cost tens of thousands of ringgit, and assume an internal IT team. On the other end, accounting software vendors have bolted on basic e-invoicing modules that work only if the customer is already using their accounting platform and willing to manually enter every invoice into yet another screen. Neither serves the SME who runs their business out of WhatsApp, email attachments, and an aging desktop accounting installation.

ZeroKey exists to occupy the gap between these two failures. We deliver enterprise-grade compliance infrastructure with consumer-grade simplicity. The SME drops their invoice into ZeroKey by any means available — a PDF in an email, a photo of a printed invoice, a row in an Excel sheet, a forwarded supplier message in WhatsApp — and ZeroKey takes care of everything that follows.

## The product in one sentence

ZeroKey is the e-invoicing platform that turns "I have to comply with LHDN" into "I dropped a file and it was done."

## Mission

Our mission is to remove the operational burden of tax compliance from Malaysian businesses, starting with e-invoicing, so that owners and finance teams can spend their time growing their company instead of fighting bureaucratic systems.

## Vision

Within three years, when a Malaysian business owner thinks about taxes, invoices, or any government compliance touchpoint, the next thought should be ZeroKey. We want to become the default infrastructure layer between Malaysian SMEs and the regulatory state, expanding from e-invoicing into adjacent compliance areas as the government continues digitizing.

## Who we serve

Our primary customer is the Malaysian small and medium enterprise with annual revenue between RM1 million and RM25 million. This includes traditional businesses operating in Phase 4 and Phase 3 of the LHDN rollout. Within that broad category, our most acute target is the SME that has not yet implemented an e-invoicing solution and faces penalty enforcement starting January 2027. These are panic buyers in 2026 who need a solution that works on day one without consultants.

Beyond the SME owner, ZeroKey serves the people in their orbit. The internal finance manager or bookkeeper who would otherwise spend hours manually entering invoices into the MyInvois portal. The external accountant or tax agent who manages compliance for dozens of SME clients and needs a way to do it efficiently across all of them. The enterprise procurement officer at a larger company who wants to extend e-invoice capability to their long tail of small suppliers without forcing each of them to buy enterprise software.

We also serve the future enterprise customer — the BFSI institution, the multinational subsidiary, the government-linked company — who needs the same engine but with their own deployment posture, compliance certifications, and integration requirements. We build for SMEs first, but everything we build also passes enterprise procurement on day one. This dual posture is intentional and strategic.

## Who we deliberately do not serve

We do not serve businesses below RM1 million in annual revenue. They are exempt from the mandate and have no commercial reason to buy. Acquiring them would dilute our positioning and waste resources.

We do not serve the do-it-yourself customer who wants to integrate the LHDN API directly into their own systems and treat ZeroKey as a low-level toolkit. Our pricing, packaging, and product surface are built around the customer who wants the work done for them. We may offer API access to advanced customers, but we will not pretend to be an SDK company.

We do not serve highly customized enterprise integrations on a per-project basis. Symprio's consulting arm exists to handle bespoke integration projects. ZeroKey is the productized product. The boundary is deliberate: ZeroKey is what scales; Symprio consulting is what customizes.

## What ZeroKey does

ZeroKey ingests business invoices through any channel a customer can throw at us. The drag-and-drop web upload accepts PDFs, images, screenshots, Excel and CSV files, and zipped batches. A unique email forwarding address per customer turns email-attached invoices into ZeroKey jobs. A WhatsApp number lets owners snap photos of supplier invoices and send them in. Database connectors read directly from the most common Malaysian accounting platforms. A REST API and webhook receiver give technical customers programmatic access. An optional browser extension lets users send invoices from any web page with one click.

Once an invoice is in ZeroKey, our routed extraction pipeline takes over. The system automatically classifies the file type and selects the right extraction strategy. Native PDFs go through fast text extraction. Scanned documents and photos go through optical character recognition followed by language model structuring. Excel and CSV files go through structured parsing with column mapping. Each extracted field receives a confidence score. High-confidence fields auto-populate. Low-confidence fields surface to the user for one-click review.

ZeroKey then enriches the invoice. Our customer master remembers every buyer the SME has ever invoiced and auto-suggests their TIN, address, and classification on subsequent invoices. Our item master suggests the right MSIC code based on item descriptions, learning from every correction the user makes. The system live-checks TINs against LHDN's validation API. It detects foreign supplier scenarios that require self-billed invoices. It flags transactions over RM10,000 that cannot be consolidated.

Validation runs against all fifty-five LHDN-mandatory fields before submission. Pre-flight checks catch errors that would otherwise be rejected by the MyInvois platform, with plain-language explanations of what is wrong and one-click suggestions to fix it. When validation passes, ZeroKey signs the invoice using the customer's digital certificate — held securely in a hardware-backed key management system, never in our application database — and submits it to MyInvois. The system polls for validation status, retrieves the unique identifier and QR code on success, and notifies the customer through their preferred channel.

Throughout, the customer sees a single clean dashboard showing every invoice's status, an exception inbox for items needing attention, real-time compliance posture metrics, and a usage meter showing how many invoices remain in their plan. Behind the scenes, every action is recorded to an immutable audit log that the customer can inspect or export for their auditors.

## What success looks like

Success in year one means ZeroKey is the obvious choice for any Malaysian SME that asks "how should I handle e-invoicing?" Recognition comes from accountant and bookkeeper recommendations, organic word of mouth from satisfied SME owners, and a reputation for being the easiest path to compliance in the market.

Success in year two means ZeroKey has expanded from drag-and-drop into accounting system connectors and API ingestion, capturing the SME that started with us and grew, plus the mid-market customer who wants the same UX with deeper integration. Multi-entity support lets accounting firms manage all their clients from one dashboard. The customer master and item master have accumulated enough learning per customer that the system feels nearly autonomous.

Success in year three means ZeroKey has expanded beyond e-invoicing into adjacent Malaysian compliance touchpoints, with new product lines under the same Symprio house brand. The platform has earned ISO 27001 certification, has been deployed inside at least one BFSI institution, and is the de facto Malaysian SME compliance infrastructure.

We measure success by the percentage of customers who complete their first e-invoice submission within ten minutes of signup, by the percentage of invoices that pass LHDN validation on first submission, by net revenue retention, and by a Net Promoter Score above sixty. Vanity metrics like signup count or page views do not appear on our dashboards.

## What ZeroKey will never become

ZeroKey will not become a general-purpose accounting platform. We connect to accounting systems; we do not replace them. The SME's existing accounting software stays.

ZeroKey will not become a tax filing platform. Filing income tax, GST, or other returns is a separate domain with separate regulatory complexity. We may partner with players in that space, but we will not build it ourselves.

ZeroKey will not become a payments processor. We work with payment data; we do not move money. The invoice is the boundary of our scope.

ZeroKey will not become a vehicle for unsolicited marketing of unrelated services to our customer base. The trust we build by handling sensitive financial data is too valuable to monetize through advertising or upsell of unrelated products. We expand by deepening compliance value, not by widening into adjacent revenue streams that compromise the trust relationship.

## The constitution

This document is the constitutional layer of ZeroKey. When any other document, decision, or feature request appears to contradict this vision, the contradiction is resolved in favor of this document, or this document is updated through deliberate review. No silent drift is permitted.