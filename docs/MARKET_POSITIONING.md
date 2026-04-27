# MARKET POSITIONING — ZeroKey

## The market we are entering

The Malaysian e-invoicing market exists because of a regulatory mandate, not because customers want it. This is the most important thing to understand about our market. Every customer we serve is a forced buyer. The question they ask is not "do I need this?" but "which solution will hurt least?"

This shapes everything about how we go to market. We do not need to educate customers about why they should care. The penalty regime educates them for us. We need to be the obvious answer when they search. We need to convert quickly when they land on our page. We need to deliver on day one because they are buying out of urgency, not enthusiasm.

The total addressable market in Malaysia consists of every business with annual revenue above RM1 million. Estimates put this at well over two hundred thousand businesses. The serviceable addressable market for ZeroKey, focusing on businesses without sophisticated existing ERP integrations, is somewhere between one hundred fifty thousand and one hundred eighty thousand entities. Even capturing one percent of that at our entry pricing represents a meaningful business; capturing five percent represents a category-defining one.

The market timing is unusually favorable. Phase 4, covering businesses from RM1 million to RM5 million, became mandatory in January 2026, with full penalty enforcement beginning January 2027. As of April 2026, most businesses in this cohort have not yet adopted a solution. They are in the panic window. We have approximately eight months before penalties create maximum urgency, then a sustained tail of laggards rushing in throughout 2027. This is a once-per-decade buying event, and we are entering it at the right moment.

## How customers currently solve the problem

The first option customers consider is the LHDN MyInvois Portal itself, the free government-provided web interface. It allows manual entry of e-invoices but is functionally a data entry form with no intelligence. An SME issuing fifty invoices a month would need to spend several hours weekly typing each one in field by field. The portal is also notoriously unfriendly: error messages reference XML schema violations, and the interface assumes the user already understands LHDN terminology. Most SMEs who try this option give up and look for an alternative within days.

The second option is the e-invoicing module bundled with their existing accounting software. SQL Account, AutoCount, and Sage UBS — the dominant Malaysian SME accounting platforms — have all released e-invoicing modules. These work reasonably well for customers whose entire invoice workflow lives inside the accounting software. They work poorly for customers whose invoices arrive as PDFs from suppliers, photos from sales staff, or rows in a shared spreadsheet. The core limitation is that these modules require the invoice to already be in the accounting system; they do not solve the ingestion problem.

The third option is a heavy enterprise middleware solution, typically sold by tax technology vendors like ClearTax, Avalara, or local players such as IRIS, Storecove, or Tickstar. These products are excellent for large corporations with internal IT teams and integration budgets in the tens of thousands of ringgit. They are completely inaccessible to the SME segment we serve. The implementation timeline alone, often three to six months, disqualifies them for panic-buying SMEs in 2026.

The fourth option, increasingly common, is to outsource the work entirely to an accounting firm or bookkeeper, who in turn uses one of the above tools. This shifts the problem rather than solving it. The accounting firm becomes the bottleneck, and the SME pays a recurring service fee on top of the underlying tool cost.

## Where ZeroKey fits

ZeroKey occupies an unoccupied position in the market: enterprise-grade infrastructure with consumer-grade simplicity, sold directly to the SME at a price point they can absorb on their own card.

The closest analogy is the position Stripe occupied in payments before its rise. Before Stripe, you either used a clunky enterprise gateway with a multi-week integration or you used PayPal with poor branding and high friction. Stripe gave developers a clean, modern interface with enterprise-grade reliability behind it. We are not Stripe — our customers are not developers — but the strategic position is analogous. We are the modern, clean, fast option in a market currently choosing between clunky enterprise tools and bolted-on legacy modules.

## What we do that nothing else does

ZeroKey accepts invoices in any format the customer can produce. Drag-and-drop accepts PDFs, images, screenshots, Excel and CSV files, and zipped batches. A unique email forwarding address per customer captures email-attached invoices. A WhatsApp number lets owners snap a photo and send. This omnivorous ingestion is the single biggest differentiator. Our competitors require the invoice to be in their system or in a connected accounting platform. We meet the customer where they actually are.

ZeroKey extracts and structures the invoice intelligently using a routed pipeline of OCR engines and language models. The customer never types fifty-five fields. They drop a file and review what we extracted. This is not a marginal speedup; it is a different category of work. Where competitors offer faster data entry, we offer the elimination of data entry.

ZeroKey learns from every correction. The customer master and item master accumulate intelligence on each customer's specific suppliers, buyers, and product catalog. By the fiftieth invoice, the system feels nearly autonomous. This compounds over time and creates real switching cost.

ZeroKey treats security as a first-class product feature. Customer signing certificates live in hardware-backed key management infrastructure, not in our application database. We are honest about what we hold and what we do not. This matters today for the careful SME and matters massively tomorrow when we sell into BFSI.

ZeroKey is built on a pluggable engine architecture from day one. As OCR and language models improve and prices drop, we route automatically to the best engine for each invoice. Competitors locked into a single vendor cannot match this. Over time, this becomes both a cost advantage and a quality advantage.

ZeroKey carries the credibility of Symprio behind it. When an enterprise procurement officer asks who built this product, the answer is a consulting firm with offices in four countries, established client relationships, and Microsoft, Oracle, and UiPath partnerships. Most pure SaaS competitors in this market do not have this answer. The dual brand structure — ZeroKey for product simplicity, Symprio for enterprise credibility — lets us punch above our weight in larger deals while staying clean and modern in the SME market.

## Who we compete with directly

Among local Malaysian players, our most direct competitors are the accounting software incumbents that have launched e-invoicing modules. SQL Account, AutoCount, and Sage UBS each have native MyInvois capability. They win on existing customer relationships and on workflow continuity for users already in their platforms. They lose on ingestion flexibility, on AI-powered extraction, and on UX modernity. We do not try to displace them. We complement them by ingesting from anywhere, including from their systems via read-only connectors.

Among middleware players, the closest competitors are JomeInvoice, BigSeller's e-invoice module, and the local arms of international tax tech vendors like ClearTax. JomeInvoice is the most relevant for direct SME competition; it is locally focused and SME-priced. We win on UX simplicity and AI-powered extraction. They win, today, on first-mover brand recognition. Our path is not to outshout them but to out-deliver on the actual user experience, which we believe is genuinely a generation ahead.

Among enterprise vendors, we do not compete directly today. Avalara, IRIS, Storecove, and Tickstar serve a different buyer with a different sales motion. We may eventually meet them in the mid-market, where ZeroKey's enterprise-grade backend lets us scale up while their enterprise tools struggle to scale down.

## Who we are not competing with but should learn from

The platforms that have nailed the SME-friendly compliance experience in adjacent categories are our best teachers. Wave Accounting and FreshBooks demonstrated that small businesses will adopt cloud accounting if the UX is simple enough. Calendly demonstrated that a single-purpose tool that does one thing exceptionally well can become category-defining. Notion demonstrated that even technical infrastructure products can be marketed with consumer-grade emotional appeal. We study these companies for product and growth lessons, not because we compete with them.

## Our ideal customer profile

The ideal ZeroKey customer is a Malaysian sole proprietorship or private limited company with annual revenue between RM1 million and RM10 million. They issue between fifty and five hundred invoices per month. They use SQL Account, AutoCount, or no accounting software at all, often relying on Excel and Google Sheets supplemented by paper or PDF invoices. The decision-maker is the owner, the finance manager, or a senior bookkeeper. They are aware of the LHDN mandate, have not yet implemented a solution, and are increasingly anxious about it. They are technically literate enough to use a smartphone and a web browser comfortably but would not describe themselves as technical. They prefer to solve problems themselves rather than hire consultants. They will pay between RM 100 and RM 800 per month for a solution that genuinely works on day one.

Concentrated industry sectors that match this profile especially well include trading and distribution businesses, professional services firms (legal, accounting, marketing), F&B suppliers, construction subcontractors, retail wholesalers, and small manufacturers. We do not exclude any sector but expect early traction to concentrate here.

## Our anti-personas

The customer who needs ZeroKey to integrate with seventeen custom-built internal systems and provide six months of free implementation support is not our customer. Symprio's consulting arm exists to serve this profile. ZeroKey is the productized product, not a custom integration vehicle.

The customer who wants the cheapest possible solution and refuses to pay anything that recurs monthly is not our customer. The market includes free or near-free options that match their budget, and we cannot serve them sustainably at our cost structure.

The customer who is below the LHDN mandate threshold and is buying out of confusion or fear of the mandate is not our customer. We will be honest with them, explain that they are exempt, and not take their money. This stance protects our reputation and concentrates our resources on customers who actually need us.

## Our pricing philosophy

Our pricing is anchored in the value we deliver, not in our cost structure. The value calculation for an SME is simple: what would it cost them to comply otherwise? Hiring a part-time clerk to type invoices into MyInvois Portal costs at least RM 2,500 per month. Buying enterprise middleware costs tens of thousands upfront plus monthly fees. Outsourcing to an accounting firm typically costs RM 500 to RM 2,000 monthly on top of the underlying tool cost. Against these alternatives, our pricing tiers are designed to be obvious yes decisions for the customer.

Our entry tier exists to make the trial-to-paid conversion frictionless and to capture the very small SME at the bottom of the mandated range. Our middle tier is the expected default for most customers and is priced to feel like an obvious upgrade as soon as the customer experiences the limit of the entry tier. Our scale tier is designed for growing customers who want headroom and additional features. Per-invoice overage charges apply above plan limits, but we deliberately price these to feel reasonable rather than punitive — we want growing customers to upgrade tiers, not feel gouged on overage.

Pricing details and tier definitions live in `BUSINESS_MODEL.md`.

## Our positioning statement

For the Malaysian small or medium business that needs to comply with LHDN e-invoicing without hiring consultants, learning XML schemas, or restructuring their workflow, ZeroKey is the e-invoicing platform that lets them simply drop their invoice in any format and have everything else handled automatically. Unlike accounting software modules that require invoices to already be in the accounting system, and unlike enterprise middleware that requires months of integration, ZeroKey works from day one with whatever the customer already has — and is built on enterprise-grade infrastructure that scales from solo entrepreneur to BFSI institution.

## Our messaging framework

The headline message we lead with for SMEs is the tagline: **Drop the PDF. Drop the Keys.** Below the headline, we promise: e-invoicing on autopilot, ten-minute setup, no consultants required. The supporting proofs we surface are: works with any invoice format, auto-extracts every field, signs and submits to LHDN, learns from every correction.

The headline message we lead with for accountants and bookkeepers is: ZeroKey lets you handle e-invoicing for all your clients from one dashboard, in a fraction of the time, with full audit trails for each.

The headline message we lead with for enterprise procurement is: ZeroKey delivers the same compliance engine that handles thousands of Malaysian SMEs daily, deployed with enterprise security controls, built by Symprio.

We adapt our voice and proof points to the audience but never the underlying truth of what the product does.

## Where we go from here

This document defines our position in the Malaysian e-invoicing market in 2026. As the market evolves — as Phase 5 cancellation settles, as competitors respond, as adjacent compliance mandates emerge — this document will be revisited. For now, the strategic position is clear: omnivorous ingestion, AI-powered extraction, enterprise-grade backend, SME-grade UX, dual brand structure with Symprio for credibility. We win by being the only product in the market that combines all of these.