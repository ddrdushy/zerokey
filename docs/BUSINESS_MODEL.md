# BUSINESS MODEL — ZeroKey

## How ZeroKey makes money

ZeroKey operates as a software-as-a-service business with subscription pricing tied to invoice volume. Customers pay a monthly fee that includes a baseline invoice quota, with predictable per-invoice overage charges if they exceed it. This pricing model aligns our revenue with our customers' usage, scales naturally as their business grows, and is straightforward enough for an SME owner to understand without a sales call.

Layered on top of the core subscription, additional revenue streams emerge over time as the product matures. These include premium feature add-ons, accountant and bookkeeper white-label arrangements, enterprise deployment licenses, and integration revenue from accounting software partnerships. The core subscription is the foundation; everything else is expansion.

## Pricing is configurable, not hardcoded

A foundational architectural principle of ZeroKey is that **pricing, plan limits, feature gating, overage rates, trial parameters, and discount rules are all administered through a super-admin configuration interface, not embedded in source code.** This is non-negotiable and flows through to the data model, the API design, and the admin UI.

The reasoning is strategic. Pricing in a brand-new market category is a hypothesis, not a fact. The numbers in this document are our launch hypothesis based on competitive analysis, value calculation, and target unit economics. They are very likely wrong in some dimension. We will need to adjust them — perhaps multiple times — as we learn what customers actually pay, what tiers they actually pick, what features they actually use, and where competitors actually price. A founder making a pricing change should not require an engineering pull request, a deployment, and a customer service campaign explaining why prices changed mid-billing-cycle. They should log into the super-admin console, define a new plan version, set effective dates, and let the billing engine handle the rest.

Concretely, this means the system must support: multiple Plan entities with versioning, where each plan carries a name, monthly base price, included invoice quota, overage rate, set of enabled features, billing cadence options, trial duration, and effective date range. Existing customers continue on their grandfathered plan version unless they actively migrate or their plan is sunsetted with notice. Promotional pricing, percentage discounts, partner pricing, and custom enterprise quotes are all defined as plan variants or override entities, not as code branches. Feature flags exposed to the application logic always read from the customer's active plan rather than from constants. Every plan change is logged to the immutable audit log with the admin user who made it, the previous values, and the new values.

The launch tiers below are therefore the **initial seed configuration** the super-admin console will be loaded with. Treat them as starting values that the admin can edit, not as truths the codebase enforces.

## Initial pricing tiers

The Free Trial exists to remove the barrier to first use. New customers get fourteen days of full Growth-tier functionality and up to twenty submitted e-invoices, whichever comes first. No credit card required to start. The goal is to get the customer to their first successful submission within ten minutes and let the product sell itself from there.

The Starter tier is initially priced at RM 99 per month and includes one hundred submitted e-invoices monthly. It targets the smallest mandated SMEs, especially sole proprietorships and family-owned businesses at the bottom of the Phase 4 range. Includes one user account, all ingestion channels except API and database connectors, basic customer master and item master with auto-suggest, full LHDN submission, and email support during business hours.

The Growth tier is initially priced at RM 299 per month and includes five hundred submitted e-invoices monthly. This is the expected default for most customers. Adds up to five user accounts, role-based permissions, the WhatsApp ingestion channel, the email forwarding channel with custom address, full audit log access, basic approval workflows, and priority email support.

The Scale tier is initially priced at RM 799 per month and includes two thousand submitted e-invoices monthly. Targets larger SMEs and small mid-market customers. Adds unlimited user accounts, the API ingestion channel, database connectors for SQL Account, AutoCount and Sage UBS, advanced approval workflows with multi-step approval chains, custom validation rules, webhook notifications, and chat support during business hours.

The Pro tier is initially priced at RM 1,999 per month and includes six thousand submitted e-invoices monthly. Targets larger mid-market customers, accounting firms managing many client entities, and high-volume retail or wholesale businesses. Adds multi-entity dashboard with consolidated reporting, single sign-on integration, custom retention policies, advanced analytics on invoice data, sandbox environment for testing integrations, and chat support with extended hours.

The Custom tier covers anything above Pro, including BFSI deployments, government-linked companies, and enterprise customers requiring data residency guarantees, dedicated infrastructure, custom SLAs, or special compliance arrangements. Pricing starts at RM 5,000 per month minimum and is negotiated based on volume, deployment shape, and integration requirements. Includes everything in Pro plus IP allowlisting, dedicated customer success manager, contractual SLAs with service credits, quarterly business reviews, and access to Symprio consulting hours for custom integration work.

Initial per-invoice overage charges above plan limits are: RM 1.00 per additional invoice on Starter, RM 0.70 per additional invoice on Growth, RM 0.50 per additional invoice on Scale, RM 0.35 per additional invoice on Pro. These prices are deliberately set to make tier upgrades the better economic choice for customers approaching their limit, while not feeling punitive for occasional spikes.

Annual billing receives a fifteen percent discount, paid in advance. This improves cash flow significantly and reduces churn, since customers committed for a year are far less likely to leave on impulse.

All of the above values — base prices, quotas, overage rates, discount percentage, trial length, trial invoice limit — are stored as configurable parameters on Plan entities. The super-admin can edit any of them, version the change, and set an effective date.

## What the admin can configure

The super-admin console exposes the following levers for pricing and packaging adjustments. None of these require a code deployment.

Plan-level configuration includes: plan name and display name in multiple languages, monthly base price in MYR with optional per-tier currency override for international expansion, billed monthly or annual price points with discount percentage between them, included invoice quota per billing period, per-invoice overage rate, included number of user seats with extra-seat pricing, supported ingestion channels, enabled feature flags, support tier (email, priority email, chat, dedicated success manager), retention period for invoices and audit logs, sandbox environment access toggle, API rate limit ceilings, and webhook concurrency caps.

Trial configuration includes: trial duration in days, included invoice cap during trial, plan tier the trial mirrors, whether credit card capture is required at trial start (default off), whether auto-conversion to paid happens at trial end or requires manual upgrade.

Promotional configuration includes: percentage discount or fixed-amount discount, applicable plans, applicable durations (first month, first three months, lifetime), eligible customer segments (new only, referrals, partner channel), promo code activation rules, and stacking rules with annual billing.

Partner and white-label configuration includes: per-partner discount tiers, per-partner branding overrides, per-partner billing terms, revenue share percentages with automated payout calculation, and per-partner client volume thresholds.

Custom enterprise quotes are modeled as one-off plan variants with a customer-specific Plan record, allowing arbitrary base price, quota, and feature set without polluting the standard plan catalog.

## What is not metered

We deliberately do not meter several things that competitors sometimes charge for. Drafted invoices that fail validation and are corrected do not count toward the quota; only submitted-and-validated invoices count. Document storage is unmetered up to reasonable limits per tier, where the limit itself is a configurable plan parameter. API requests for read operations such as status checks and customer master lookups are unmetered. Webhook deliveries are unmetered. The reasoning is simple: we want customers to use the product fully without watching meters for non-core actions. Counting only the things that matter to LHDN keeps the pricing honest and easy to predict.

These non-metering rules are themselves configurable. If at some point we discover that storage is being abused or that API read operations are degrading service for paying customers, the admin can introduce metering on those dimensions without engineering work.

## Money-back guarantee

Every paying customer is covered by a thirty-day unconditional money-back guarantee. If a customer is unhappy for any reason within thirty days of their first paid invoice, we refund the full amount with no questions asked. The duration of this guarantee window is itself a configurable parameter on the global billing settings, defaulting to thirty days. The guarantee exists for two reasons. First, it removes the perceived risk of switching from a competitor or from manual MyInvois Portal use. Second, it forces us internally to ensure the first thirty days of customer experience are genuinely excellent. A high refund rate is a product problem, not a guarantee problem.

## Unit economics

Our cost to serve a single invoice depends on the extraction path the routed pipeline chooses. Native PDFs go through pure text extraction and a single small language model call, costing approximately one cent per invoice. Scanned PDFs and images go through optical character recognition followed by language model structuring, costing approximately three to five cents per invoice. Excel and CSV files cost less than half a cent per invoice. Email forwards inherit the cost of whatever attachments they contain.

For a typical Growth-tier customer submitting four hundred invoices monthly, our blended cost of extraction is approximately RM 6 to RM 12. Add infrastructure costs of approximately RM 4 per active customer covering compute, storage, bandwidth, and observability. Add payment processing fees of RM 9, roughly three percent of RM 299. Add customer support amortization of RM 15. Total cost to serve approximates RM 34 to RM 40 per Growth customer per month. At RM 299 revenue, gross margin sits at approximately eighty-seven percent.

This is a healthy SaaS margin. It improves as customers move to higher tiers — Scale margin is approximately ninety-two percent, Pro margin is approximately ninety-four percent — and as we scale and amortize fixed costs. It improves further as language model prices continue their steady downward trajectory. It degrades if a customer uploads predominantly photo invoices that require expensive vision processing. The pluggable engine architecture lets us route around margin-destroying customers by selecting cheaper engines for cost-sensitive tiers. The admin can also configure per-plan engine selection rules, restricting expensive vision pipelines to higher tiers if cost dynamics shift.

The customer acquisition cost target for the SME segment is below RM 600. With Growth-tier annual contract value of RM 3,588 and target gross margin of eighty-seven percent, the contribution margin per customer per year is approximately RM 3,120. Payback period at our target acquisition cost is under three months. Lifetime value, assuming average customer tenure of three years, is approximately RM 9,400. The LTV-to-CAC ratio is comfortably above the three-to-one threshold that defines a healthy SaaS business.

## Cost structure

Our primary variable costs are language model and OCR engine fees, infrastructure compute and storage, payment processing, and per-customer support amortization. These scale with usage and customer count.

Our primary fixed costs in the early phase are infrastructure baseline (whether or not we have customers, we run staging environments, monitoring, and minimum production capacity), software tooling (observability, CI/CD, design tools), and legal and compliance fees (Malaysian counsel for templates, eventual ISO certification audit costs).

Engineering cost is largely absorbed by the founder plus Claude Code, which means in the early phase the labor cost line is essentially the founder's opportunity cost. As the team grows post-revenue, this becomes the largest cost line.

Customer success and support are deliberately kept lean. The product is designed to self-serve. Investment in documentation, in-product help, and excellent error messages substitutes for headcount. Where human support is required, it is provided through ticket and chat for higher tiers, with response time SLAs scaled by tier (and the SLA targets themselves are configurable plan parameters, not hardcoded values).

## Expansion paths

The first expansion path is volume growth within an existing customer. As an SME grows, their invoice volume grows, and they naturally move from Starter to Growth to Scale to Pro. This is captured by the tier structure and requires no sales effort.

The second expansion path is feature add-ons. Premium features that do not fit cleanly into a tier are sold as add-ons. The most likely first add-ons include consolidated B2C invoice automation for retail SMEs, multi-entity dashboard for accounting firms when sold separately to lower-tier customers, advanced analytics on invoice data, and dedicated WhatsApp number on lower tiers. Pricing typically ranges from RM 50 to RM 200 per add-on per month. Add-ons are modeled as separate billable entities attached to a customer subscription and are themselves configurable in the admin console.

The third expansion path is the accountant and bookkeeper white-label channel. External accountants who manage compliance for many SME clients receive a discounted multi-tenant version of ZeroKey, branded as their own service or co-branded. Their pricing is per-client per-month with volume discounts. This channel could become significant: a single accountant managing fifty clients generates the equivalent of a Pro-tier customer plus expansion. Partner-specific pricing and revenue share rules are configured per partner in the admin console.

The fourth expansion path is enterprise deployment, including BFSI and government customers. These are negotiated annual contracts with substantially higher value, custom integration work that hands off to Symprio consulting, and ongoing support. Each enterprise deployment is worth several hundred thousand ringgit annually but requires significantly longer sales cycles. Enterprise quotes are modeled as customer-specific Plan variants.

The fifth expansion path is adjacent compliance products. Once ZeroKey is established as the trusted Malaysian compliance infrastructure, adjacent products such as HR compliance automation, SST returns, and audit data preparation become natural extensions. Each one is launched as a separate ZeroKey product line under the Symprio umbrella, sold to the existing customer base first.

## Customer acquisition strategy

In the first phase, we acquire customers through three primary channels.

The first channel is content-led inbound. We publish authoritative Malaysian e-invoicing guides, decoder articles for LHDN error codes, comparison content versus alternatives, and walkthroughs for common compliance scenarios. This content ranks in search and converts the panic-buying SME who is researching their options. The content is honest and useful even for readers who do not become customers; this builds brand trust. Investment is in writing and search optimization, not in paid ads.

The second channel is the accountant and bookkeeper community. Malaysian SMEs trust their accountants for technology recommendations more than any other source. We build relationships with the accounting community through participation in CTIM events, sponsored content in MIA publications, and a dedicated partner program with revenue share. An accountant who recommends ZeroKey to thirty clients is more valuable than thirty individual marketing efforts.

The third channel is community and ecosystem leverage through Symprio's existing network. The Isai Alai community provides organic reach into the Tamil Malaysian SME community. The UiPath Malaysia chapter network provides reach into the broader RPA-curious enterprise IT community. Symprio's existing client relationships in BFSI provide a natural enterprise pipeline. These warm channels convert dramatically better than cold outreach.

In later phases, paid acquisition becomes viable as we have a proven payback period and a known customer acquisition cost. We expect to add Google Ads targeting LHDN-related keywords, Facebook and Instagram ads targeting the Malaysian SME demographic, and LinkedIn for enterprise outreach. These are layered on top of the inbound foundation, never as a replacement.

## Retention strategy

Retention in this market is structurally favorable. Customers cannot stop using e-invoicing without going out of business, so the only churn risk is competitive switching. Our retention strategy focuses on making switching painful and continued use delightful.

The customer master and item master accumulate per-customer learning over time. After a year of use, a customer's data set inside ZeroKey represents real intelligence that takes months to recreate elsewhere. This is the deepest moat.

The audit log and historical invoice archive create regulatory switching cost. Customers under audit need access to historical e-invoices with their LHDN identifiers and validation timestamps. Migrating this elsewhere is risky and slow.

Continuous product improvement keeps the experience fresh. Customers who feel the product is getting better every month do not look elsewhere. We commit to a public changelog with monthly improvements, even if small.

Proactive customer success outreach for higher tiers catches dissatisfaction before it becomes churn. A monthly check-in for Pro and Custom customers, surfacing usage anomalies and upcoming feature releases, prevents the slow drift toward switching. Outreach cadence and trigger thresholds are configurable per plan tier.

## Revenue targets

In year one, the realistic target is to reach two hundred paying customers across all tiers, weighted toward Growth, by month twelve. This generates approximately RM 50,000 to RM 60,000 in monthly recurring revenue. The goal is not maximum revenue in year one but rather product-market fit demonstrated through high retention, strong NPS, and organic word of mouth.

In year two, with product-market fit demonstrated, the target is to reach one thousand paying customers and approximately RM 250,000 in monthly recurring revenue. This is the year when paid acquisition gets layered on top of inbound, and the accountant channel begins to scale.

In year three, with multiple expansion paths active, the target is approximately RM 1 million in monthly recurring revenue, including the first significant enterprise deployments contributing to the mix.

These are reasonable targets for a solo-founder build with disciplined execution. They are not the maximum theoretical opportunity. The Malaysian e-invoicing market is large enough that a more aggressive build could capture multiples of these numbers. The targets here reflect what is achievable while maintaining product quality, customer trust, and personal sustainability for the founder.

## When to consider raising capital

ZeroKey is designed to be capital-efficient and potentially fundable but not capital-dependent. The cost structure of a solo build with AI engineering assistance means we can reach significant revenue without external funding.

Capital might be considered at three triggers. First, if early growth significantly exceeds plan and the constraint becomes execution capacity rather than product or market. Second, if a competitor raises a meaningful round and threatens to outspend us in customer acquisition. Third, if a strategic adjacency emerges (such as a regional expansion opportunity to Singapore or Indonesia) that requires capital for legal and infrastructure setup.

If we raise, the preferred shape is a small seed round (USD 1 to 2 million) from a single regional investor with deep Malaysian SME or fintech expertise, structured to extend runway and accelerate, not to grow at any cost. We do not pursue capital for vanity, growth-at-all-costs, or to chase a unicorn outcome at the expense of business quality.

## Exit possibilities

We do not optimize for an exit, but several paths exist if circumstances make one appropriate. A strategic acquisition by an accounting software incumbent (SQL Account, AutoCount, Sage) would extend their compliance offering with our AI-powered extraction. A strategic acquisition by a regional fintech expanding into Malaysia would offer them a beachhead. A strategic acquisition by a global tax technology player such as Avalara or ClearTax would consolidate the Malaysian market. A management buyout or staying private indefinitely as a profitable business is also a fine outcome.

The point of acknowledging exit possibilities is to make decisions today that preserve all options. Clean cap table, clean financials, clean code, clean compliance posture, transferable customer relationships. We do not lock ourselves into a path; we keep optionality.