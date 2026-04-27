# LANDING PAGE — ZeroKey

> The marketing site that converts cold traffic into trials and demos. This document specifies the structure, the section-by-section purpose and copy direction, the conversion funnel, the SEO and analytics architecture, the multilingual approach, and the technical implementation. The landing page is one of the highest-leverage assets in the whole launch; this document treats it accordingly.

## Why the landing page matters

The Q4 2026 LHDN enforcement-deadline window is the most important commercial period in ZeroKey's first two years. Phase 4 SMEs (RM 1M–5M turnover) became mandatory on 1 January 2026 with penalty enforcement from 1 January 2027 at RM 200 to RM 20,000 per non-compliant invoice. The market will actively shop for solutions in October, November, and December 2026. The landing page is the surface that converts that shopping traffic into pipeline.

A landing page that converts at 4% rather than 1% means four times the customers from the same traffic spend. At expected acquisition costs and customer lifetime values, this is the difference between a comfortable launch and a strained one. The landing page is therefore not a marketing afterthought; it is critical product infrastructure.

Three audiences arrive at the landing page through different paths.

The **SME owner** (Aisyah persona) arrives anxious and time-constrained. She has heard about LHDN enforcement from her accountant or her business network. She has thirty seconds of patience before deciding whether ZeroKey is worth more attention. The page must answer her unstated question — "is this for me, can I afford it, will it work?" — within the first scroll.

The **finance manager** (Wei Lun persona) arrives in evaluation mode. He has read about a few options and is comparing them. He has more patience but higher standards. The page must give him enough technical and operational substance to mark ZeroKey as a credible candidate for deeper evaluation.

The **enterprise / BFSI buyer** (Hafiz persona) arrives in research mode for a longer evaluation cycle. The page must give him the credibility signals (Symprio parent, security posture, audit story) that justify continuing the conversation, and must offer a path to a demo with a real human rather than a self-serve trial.

The page serves all three without being incoherent. The discipline is to lead with the SME owner's needs (because she is the largest segment by count and the most time-sensitive), surface the finance manager's depth in scannable form for those who scroll, and offer a clear sales-assisted path for the enterprise buyer.

## Conversion strategy

The landing page has two primary conversion goals operating simultaneously.

The **primary CTA** is **Start Free Trial**. This is the dominant call to action throughout the page, present in the hero, in the pricing section, and in a sticky footer or persistent header. The trial is fourteen days with twenty invoices, no credit card required to start. This low-friction self-serve path captures the SME segment and lets evaluation traffic convert without sales involvement.

The **secondary CTA** is **Book a Demo**. This is positioned as the path for "larger teams" or "complex deployments" and links to a calendar booking. The demo path captures the enterprise segment that requires a human conversation before signing.

Both CTAs are visible from the hero. The visual hierarchy makes the trial CTA more prominent (larger, brighter, more contrast) while the demo CTA is clearly available for visitors who self-identify as enterprise.

A third path — **Talk to Sales** — is a soft CTA in the footer and on the pricing page next to the Custom tier. It links to an email form rather than a calendar to set the expectation that the response is human-paced rather than instant.

The conversion funnel is instrumented at every step: page view, scroll depth, CTA click, signup form view, signup form submit, trial activation, certificate upload, first invoice submission. Drop-off at each step is monitored, and the steps with the largest drop-off receive the most optimization attention.

## Page structure

The landing page is a single long-form scrolling page with the following sections in order. Each section has a specific purpose; sections that fail their purpose are revised, not deleted, until they succeed.

### Section 1: Navigation header

A persistent navigation bar at the top of every page on the marketing site. It is sticky on scroll so the CTA is always reachable.

The header contains: the ZeroKey wordmark on the left (linking to home), four primary navigation items (Product, Pricing, Customers, Resources), a language switcher in the upper right, and the dual CTAs (Sign In as a text link, Start Free Trial as a primary button).

On mobile the navigation collapses into a hamburger menu, but the Start Free Trial button remains visible.

The header uses the brand colors from `VISUAL_IDENTITY.md` with the dark navy background and the light cream foreground. The lime accent is reserved for the primary CTA button.

### Section 2: Hero

The hero is the first screen the visitor sees and carries the heaviest conversion weight. It must communicate what ZeroKey is, who it is for, why it matters, and what to do next — within five seconds of scanning.

The hero contains a tight headline (one line, eight to twelve words), the tagline as a stylized secondary line, a subhead (one sentence, twenty to thirty words) explaining the LHDN compliance pain, the dual CTAs (Start Free Trial primary, Book a Demo secondary), a trust strip immediately below the CTAs, and a hero visual on the right or below.

The headline direction: lead with the customer's outcome, not our technology. Examples in the right shape: "LHDN e-invoicing without the headaches." or "Your invoices, signed and submitted, automatically." The headline is the most-edited element on the page; it is rewritten and tested repeatedly until it converts at the target rate.

The tagline appears in a stylized treatment per `BRAND_KIT.md`. The italicization pattern from Symprio's brand DNA is honored: "Drop the PDF. *Drop the Keys.*" with the second phrase in italic to draw the eye.

The subhead grounds the headline in concrete pain. Example: "Malaysian SMEs face penalties up to RM 20,000 per non-compliant invoice from January 2027. ZeroKey handles every invoice from upload to LHDN — accurate, audited, and fast." This subhead names the pain (penalties), names the audience (Malaysian SMEs), names the timing (January 2027), and names what we do (everything from upload to LHDN). It is precise without being long.

The trust strip immediately below the CTAs lists three to five credibility anchors in a single horizontal row: Symprio parent attribution ("A product of Symprio Sdn Bhd"), the MDEC accreditation, the LHDN registered software intermediary status, and partnerships logos (UiPath, Microsoft, Anthropic, Oracle, Google, Meta as inherited from Symprio's positioning). Logos are subtle, monochrome, and small — the trust signal is "we are credible and connected" not "we are bragging."

The hero visual on the right is a clean product screenshot showing the dashboard with a recently submitted invoice and its LHDN UUID and QR code visible. The visual reinforces what the headline promises: we make this easy. Avoid stock illustrations; use real product imagery.

### Section 3: The problem

This section grounds the visitor in the pain that brought them here. It must be specific, factual, and brief — three or four short paragraphs at most.

The section opens with the timing: from 1 January 2027, LHDN begins enforcing penalties on Phase 4 taxpayers (RM 1M–5M annual turnover) for invoices that fail to meet MyInvois requirements. Penalties are RM 200 to RM 20,000 per non-compliant invoice.

The section then names the practical problem: most accounting systems were not built for MyInvois, the technical specification is detailed, the field requirements are exacting, the validation rules reject invoices for subtle reasons, and the cancellation window is only seventy-two hours. Doing this manually is feasible for one or two invoices a month; doing it for fifty or two hundred a month is not.

The section closes with the choice that visitors are facing: build it yourself (developer cost, distraction from your real business), wait for your accounting system to catch up (timing risk, you may not make the deadline), or use a tool built specifically for this (the implicit lead-in to ZeroKey).

The section should not lecture. The visitor already knows there is a problem; that is why they are reading. The section's job is to confirm their understanding and demonstrate that we understand it too.

### Section 4: How it works

This section shows the product, not just describes it. It is a four-step visual flow representing the customer's journey from invoice to LHDN submission.

Step one: drop your invoice. Show the four ingestion channels — web upload, email forward, WhatsApp, API — with a small icon for each and one line of explanation. The message: it does not matter what format your suppliers or your team uses; ZeroKey accepts it.

Step two: we extract and validate. Show a brief animated transformation from a raw PDF to structured fields, with confidence indicators. The message: AI handles the extraction, you do not type anything, and we catch errors before LHDN does.

Step three: review and approve. Show the review interface with the original document side-by-side with the extracted fields. The message: you stay in control, every field is editable, every change is logged.

Step four: submitted to LHDN. Show the confirmation screen with the LHDN UUID, the validated status, and the QR code. The message: it is done, it is compliant, you have proof.

Each step gets a short caption and a screenshot or animation. The total section is scannable in twenty seconds. The visitor who reads only the captions still understands what we do.

### Section 5: Why ZeroKey

This section explains positioning without naming competitors. It frames the alternatives honestly and shows where ZeroKey fits.

The section uses a comparative frame structured around the three alternatives the visitor is implicitly considering. Each alternative gets a short paragraph acknowledging its merits and naming its trade-off, followed by ZeroKey's position.

"Building it yourself" — fast for one company, but the calendar cost is significant and the resulting tool requires ongoing maintenance as LHDN evolves. ZeroKey's position: we maintain the LHDN integration so you can focus on your business.

"Waiting for your accounting system" — your accounting vendor may add e-invoicing eventually, but the deadline is fixed and the timing is theirs not yours. ZeroKey's position: we connect to your existing accounting system (SQL Account, AutoCount, Sage UBS) so you do not have to switch or wait.

"Generic e-invoicing tools from outside Malaysia" — these exist but were not built for MyInvois. The Malaysian field requirements, the MSIC codes, the seventy-two-hour cancellation window, the regional language needs — these need a Malaysia-shaped tool. ZeroKey's position: built in Malaysia for the Malaysian regulatory framework, with English, Bahasa Malaysia, Mandarin, and Tamil first-class.

The section closes with three or four ZeroKey-specific differentiators stated as outcomes: fastest extraction in the market for Malaysian invoice formats, every action audit-logged with cryptographic verifiability, customer signing keys never held in our database, and a Malaysian support team that understands your accountant.

### Section 6: Built for Malaysian businesses

This section emphasizes regional fit through a few concrete proof points. It is short — one or two paragraphs and a few visual elements.

Mention the four supported languages with the language switcher visible. Mention specific Malaysian regulatory facts (the MSIC code library, the Bank Negara reference rates for multi-currency invoices, the FPX payment integration for subscription billing). Mention specific accounting system integrations (SQL Account, AutoCount, Sage UBS) with their logos.

The message is structural: ZeroKey is not an international product translated into a Malaysian context. It is Malaysian.

### Section 7: Trust and security

This section addresses the credibility concerns of finance and IT buyers without sounding like a security marketing brochure. The tone is calm and specific.

Three or four trust pillars are presented with one paragraph each.

The first pillar: **your signing keys are not our keys**. Customer signing certificates live in hardware-backed key management infrastructure. We are custodians, not owners. Even our highest-privileged staff cannot extract a customer's private key. This is a structural commitment, not a policy.

The second pillar: **every action is auditable**. The immutable hash-chained audit log captures every invoice action, every authentication event, every settings change, every staff access. Customers can export the log as a tamper-evident bundle and verify integrity independently. When an auditor asks "can you prove what happened?", the answer is yes.

The third pillar: **Malaysia-hosted, Malaysia-residency**. Customer data lives in AWS Asia Pacific Malaysia (`ap-southeast-5`). Disaster recovery replication to Singapore (`ap-southeast-1`). No customer data leaves the region without explicit consent.

The fourth pillar: **certifications in flight**. PDPA-compliant from launch. ISO 27001 certification in progress (target Q2 2027). SOC 2 Type II following. Honest about current state; not claiming what we do not yet have.

The section closes with a link to the public security and compliance documentation for visitors who want depth.

### Section 8: Pricing

The pricing section presents the plan tiers from `BUSINESS_MODEL.md` in a clear comparative grid. The section is built for scanning: a visitor should understand the pricing within ten seconds of arriving at this section.

The grid columns are the plan tiers in order: Free Trial (highlighted as a starting point, not a permanent plan), Starter, Growth, Scale, Pro, Custom (without explicit pricing, "Talk to Sales" CTA).

The grid rows show the key differentiators: monthly base price in MYR, included invoice volume per month, overage rate, included user seats, support tier, and a few headline features unique to higher tiers.

A toggle above the grid switches between monthly and annual pricing, applying the 15% annual discount to annual prices and showing the savings. Annual is selected by default to anchor the lower price.

Below the grid, a callout for the 30-day money-back guarantee builds confidence.

A trust line near the pricing notes that pricing is in Malaysian Ringgit, that all plans include LHDN MyInvois submission, that Free Trial requires no credit card, and that customers can change plans any time.

The Custom column is positioned distinctly. Instead of a price, it says "From RM 5,000/month" with a brief feature summary (custom integrations, dedicated support, on-premise deployment options) and a "Talk to Sales" CTA linking to the demo booking flow.

### Section 9: Customer voices

This section is empty at launch and grows over time. At launch, in lieu of customer testimonials, we use a different angle.

Option A is to use beta customer quotes (with permission, anonymized appropriately) once Phase 6 of the roadmap completes. By GA, several beta customers have used the product and a few will agree to be quoted.

Option B is to use a "from our team" angle: a short paragraph from the founder explaining why ZeroKey exists, the customer problem he saw, and what he wanted to build. This is honest about being founder-driven and pre-customer-testimonial without weakening the page.

Option C is to skip customer voices entirely at launch and add them as they accumulate. The risk of fake or weak testimonials at launch is higher than the cost of the empty space.

The recommended approach for the launch page is Option B with a placeholder for Option A as soon as beta customers can speak. Option C is the fallback if Option B feels like founder-vanity to anyone reviewing the page.

### Section 10: Personas

Three persona cards in a row, each addressing a different audience. The card structure is consistent: a short headline, a one-paragraph description, two or three bullet points of what they get, and a CTA leading to either the trial or demo.

**Card 1: For SME owners who just want this handled.** The Aisyah card. Description: focused on running your business, not on tax technology, your accountant manages the books, you need this to not be your problem. Bullets: works with email forward and WhatsApp (no new system to learn), pricing that fits your invoice volume, support in your language. CTA: Start Free Trial.

**Card 2: For finance and operations managers leading the rollout.** The Wei Lun card. Description: you are responsible for compliance, your team handles dozens of invoices weekly, you need a tool the team can adopt without disruption. Bullets: connects to your existing accounting system, audit-grade record keeping, multi-user with role-based permissions. CTA: Start Free Trial or Book a Demo.

**Card 3: For technical teams integrating into existing systems.** The Ravi card. Description: you are integrating ZeroKey into a larger workflow, you care about API quality and operational reliability. Bullets: REST API with OpenAPI spec, sandbox environment for development, webhooks for asynchronous integration. CTA: View API Docs or Book a Demo.

A fourth card appears for enterprise visitors:

**Card 4: For BFSI and large enterprise compliance teams.** The Hafiz card. Description: regulatory compliance is your responsibility, you require enterprise security posture and dedicated support. Bullets: SSO and audit log integration, custom retention and data residency, dedicated technical contact. CTA: Talk to Sales.

The persona section is positioned mid-page rather than at the top because cold traffic does not yet self-identify cleanly. The section helps warmer visitors find their place after the introductory sections have done their work.

### Section 11: Frequently asked questions

The FAQ section addresses the questions that real prospects ask. The list grows over time as we learn what visitors actually want to know. At launch, the FAQ includes:

- "Do I need to be registered with LHDN before signing up?"
- "How do I get a digital certificate from LHDN?"
- "Can I switch from another e-invoicing tool to ZeroKey?"
- "What happens to my data if I cancel?"
- "Is my data stored in Malaysia?"
- "Do you support self-billed invoices?"
- "How does ZeroKey handle the seventy-two-hour cancellation window?"
- "Which accounting systems do you integrate with?"
- "Can my accountant access my account?"
- "What languages does ZeroKey support?"
- "How does pricing work if I have an unusually high invoice month?"
- "Is there a setup fee or onboarding fee?"
- "What if I have more than one entity?"
- "How does ZeroKey compare to building it ourselves?"
- "What happens if LHDN's MyInvois system is down?"

Each answer is two to four sentences. The tone is direct and helpful. Long answers signal that the topic deserves a dedicated article and link out to the help center.

The FAQ is structured as an accordion (collapsible) so the section is not visually overwhelming but every answer is reachable.

### Section 12: Final CTA section

A final conversion section before the footer. It restates the value proposition in a tighter form and presents the dual CTAs again.

The section is a short headline (something like "Stop dreading e-invoicing season."), a one-sentence subhead, and the two buttons.

The section uses a strong visual treatment — likely the dark navy background with the lime accent on the primary CTA — to make it visually distinct from preceding sections and to draw the eye for visitors who scroll past intermediate sections.

A small reminder near the buttons addresses last-minute friction: "Free 14-day trial. No credit card. Cancel anytime."

### Section 13: Footer

The footer contains the secondary navigation, legal links, and contact information.

Footer columns include: Product (link to features, pricing, integrations, security, changelog), Resources (link to documentation, blog, help center, status page, API reference), Company (link to About / Symprio, careers, contact, privacy notice, terms of service), Legal (link to PDPA notice, cookies policy, acceptable use, DPA template).

Below the columns, a final row contains the language switcher (English / Bahasa Malaysia / 中文 / தமிழ்), social links (LinkedIn primarily; the founder's professional presence is the primary social channel), the Symprio parent attribution ("A product of Symprio Sdn Bhd"), and the copyright line.

The footer is on every page on the marketing site, not just the landing page.

## Multilingual approach

The landing page is built in four languages: English (default), Bahasa Malaysia, Mandarin, and Tamil. The translations are first-class and not afterthoughts.

English is the master copy. Translations into the other three languages are produced by qualified human translators (not raw machine translation), reviewed by native speakers familiar with business language in Malaysia, and updated alongside English when the master copy changes.

The language switcher is in the header and the footer. Selecting a language switches the entire page and persists the preference in a cookie. The URL structure includes the language code (`/en/`, `/ms/`, `/zh/`, `/ta/`) so that direct sharing and SEO work correctly per language.

Currency, dates, and numbers are localized to Malaysian conventions across all languages.

The Tamil language support is a deliberate brand commitment from `BRAND_KIT.md` — Tamil is the founder's heritage language and a marker of authenticity for the Tamil-speaking SME segment. The Tamil version is treated with the same care as the others, not as a token gesture.

For cold traffic, the language detected from the browser is offered as a suggestion banner ("View in Bahasa Malaysia?") on the English page rather than auto-redirecting. Auto-redirect annoys visitors who expected English; suggestion respects their choice.

## SEO architecture

The landing page is built for organic discovery in addition to paid traffic.

**Page-level metadata** for each language version includes title tags optimized for the primary search intent ("LHDN e-invoicing software for Malaysian SMEs" and variants), meta descriptions of 150 to 160 characters that are compelling rather than just descriptive, Open Graph tags for social sharing previews, Twitter Card metadata, and canonical URLs to prevent duplicate-content issues across language versions.

**Structured data** in JSON-LD format includes Organization schema (with the Symprio parent and the ZeroKey product relationships), Product schema (with pricing and rating data once we have customer reviews), FAQPage schema for the FAQ section (which can earn rich snippets in search results), and BreadcrumbList schema for navigation hierarchy.

**hreflang tags** declare the relationship between the four language versions so search engines serve the right version to users in each language and region.

**XML sitemap** is generated automatically and submitted to search engines. The sitemap includes all marketing site pages with their last-updated timestamps. Frequency hints are realistic (the landing page itself updates monthly; the blog updates weekly during active publishing).

**Robots.txt** disallows crawling of the application surface (`app.zerokey.symprio.com` if that is the chosen subdomain) and the API. Marketing site is fully crawlable.

**Page performance** is treated as an SEO signal. Target metrics from Lighthouse and Core Web Vitals: Largest Contentful Paint under 2.5 seconds on 4G, First Input Delay under 100 milliseconds, Cumulative Layout Shift under 0.1. The page is built to be fast first, beautiful second.

**Content depth** comes from the surrounding marketing site, not just the landing page. A blog covering Malaysian e-invoicing topics, customer-facing help center articles answering specific compliance questions, and case studies (once we have customers) build the topic authority that earns ranking.

The primary keyword targets at launch include "LHDN e-invoicing", "MyInvois software", "Malaysia e-invoicing for SME", "Phase 4 e-invoicing", "LHDN compliance Malaysia", and the same keywords in the other three languages with appropriate localization. Long-tail keywords ("e-invoicing for SQL Account users", "MyInvois for accounting firms") are targeted through dedicated blog articles.

## Analytics and conversion tracking

Analytics is set up with the discipline of measuring what matters and not what is easy.

The primary analytics platform is **Plausible** or a privacy-respecting equivalent for default page tracking. We avoid Google Analytics as the primary because of its data-handling implications and PDPA-friction, though Google Analytics is added as a secondary tool for the integrations that depend on it (Google Ads conversion tracking, Google Search Console linking).

**Goal tracking** is configured for each step of the conversion funnel: page views by section, scroll depth at 25 / 50 / 75 / 100%, CTA clicks (with separate tracking for primary and secondary CTAs), signup form views, signup form submissions, trial activations (verified through the application), certificate uploads, and first invoice submissions.

**Attribution** captures the source of every conversion: paid search, organic search, direct, referral (with referring domain), and social. Specific UTM parameters are used for marketing campaigns so that campaign performance can be measured.

**Heatmap and session recording** are available on a tool like Hotjar or PostHog for qualitative analysis. Recording is opt-in (via cookie consent) and excludes any PII fields automatically.

**A/B testing** infrastructure is in place from launch but not aggressively used in the first weeks. Testing comes after we have enough traffic to draw meaningful conclusions, typically a few weeks after launch.

**Cookie consent** is implemented to respect PDPA preferences. Visitors can reject non-essential cookies and the analytics still tracks their visit (anonymously). The consent banner is unobtrusive but clear.

## Technical implementation

The landing page is built in **Next.js with TypeScript** for consistency with the application stack. This choice has benefits: shared design tokens with the application, easy reuse of component patterns, fast static generation for SEO and performance, and unified deployment pipeline.

The marketing site is a separate Next.js project deployed independently from the application. The site is statically generated where possible (most marketing pages do not need server-side rendering) with revalidation on content updates.

**Styling** uses the same Tailwind CSS configuration as the application, with the design tokens from `VISUAL_IDENTITY.md`. The component library is a subset of the application's shadcn/ui components, themed for marketing context.

**Hosting** uses Vercel or AWS CloudFront with S3 — both work; the choice depends on operational preferences. The CDN edge caches static content globally for performance.

**Content management** is via MDX files in the repository for v1. This is sufficient for the founder-managed phase. As content grows, a headless CMS (Sanity or similar) is introduced for non-developer content updates.

**Forms** (signup and demo booking) are handled through serverless functions that integrate with the application backend. The signup form creates a trial account directly via the application API. The demo booking form integrates with a calendar system (Calendly or Cal.com) and notifies the founder via email and WhatsApp.

**Performance** is a conscious priority. Images are served as next-gen formats (WebP, AVIF) with appropriate sizing. JavaScript is minimized; the page works without JavaScript for most features. Fonts are loaded with `font-display: swap` to prevent invisible text. Critical CSS is inlined.

**Accessibility** is non-negotiable. Every interactive element has accessible labels. Color contrast meets WCAG AA. Keyboard navigation works through the entire page. Screen reader testing is part of the launch checklist.

## Mobile experience

The Malaysian market is heavily mobile. The landing page is mobile-first in design and implementation, not desktop-first with a mobile fallback.

The mobile experience preserves the full content but with reorganized layout: the hero stacks vertically, the navigation collapses to a hamburger, the comparison grids become scrollable cards or vertical stacks, and the persona cards stack rather than sitting in a row.

The persistent CTA on mobile is a sticky bottom bar with the Start Free Trial button, ensuring conversion is always one tap away regardless of scroll position.

Mobile performance is tested specifically: page weight, time to interactive, and form usability are validated on mid-range Android devices on 4G connections, which is closer to the real Malaysian SME experience than testing only on flagship devices.

## Launch and ongoing optimization

The landing page launches alongside the GA announcement in late September 2026. The launch version is the best the founder and any contracted help can produce within the available time, not perfect.

**Post-launch optimization** is iterative based on data. The first weeks of data show which sections convert, which sections lose visitors, and which CTAs perform. Optimization priorities are derived from data, not from opinion.

**Headline testing** begins once traffic is sufficient. Different headline variants are tested through A/B infrastructure. Winners are kept; losers are replaced. This is one of the highest-leverage optimization activities.

**Content additions** based on customer questions: when prospects repeatedly ask the same question that the page does not answer, the page is updated to address it (either inline or via a linked help article).

**Conversion rate goals**: the launch target is 2% on the trial CTA from cold traffic. As we learn the audience, the target rises to 4% by year-end. The demo CTA target is 0.5% to 1% of qualified enterprise visitors.

**Customer testimonials** are added as they accumulate. Each testimonial is reviewed for honesty (we do not embellish), specificity (vague testimonials do not convert), and consent (every testimonial is approved by the customer).

## Brand discipline

The landing page inherits the full brand identity from `BRAND_KIT.md` and `VISUAL_IDENTITY.md`. Specific disciplines:

The voice is calm, confident, and warm. Not breathless or salesy. Not corporate-stiff. The text reads like a knowledgeable colleague explaining what we do, not a marketing department selling.

The visuals are restrained. Whitespace is generous. The lime accent is reserved for the primary CTA and is rarely used elsewhere. The italicized phrase pattern from Symprio's brand DNA is honored in a few places for emphasis, not overused.

The Symprio relationship is acknowledged but not the lead. ZeroKey is the wordmark; "by Symprio" appears in the trust strip and in attributions but does not crowd the product identity.

The four languages are presented with equal weight. The English version is not visually privileged; all four versions get the same care.

## How this document evolves

When the page structure changes (a section is added, removed, or significantly reordered), this document is updated. When the conversion strategy changes (the primary CTA shifts, the funnel definition shifts), this document is updated. When the technical implementation changes meaningfully (the framework changes, the hosting changes), this document is updated.

When the live page and this document diverge, one is wrong. Either the document is updated (if the page is correct) or the page is brought back into alignment (if the document captures the intended state).

When the founder or any future team member asks "what does our landing page look like and why does each section exist?", the answer comes from this document combined with the live page. The document explains the strategy; the live page demonstrates the execution.
