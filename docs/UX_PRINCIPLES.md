# UX PRINCIPLES — ZeroKey

> Fifteen principles that govern every interaction in ZeroKey. When a design question is ambiguous, these principles resolve it. When a feature seems to need an exception, the exception is questioned harder than the rule.

## Why principles, not patterns

Pattern libraries describe what we have already built. Principles describe what we believe. Patterns are useful for consistency; principles are necessary for new decisions where no pattern exists yet. ZeroKey will face thousands of small interaction-design decisions in its first year, most of which will be made by a single person (or a single AI engineer) at speed. Without principles, those decisions drift toward the path of least resistance, which is usually whatever the underlying framework defaults to. With principles, every decision is anchored to the same north star.

These principles are ranked by precedence. When two principles conflict, the lower-numbered one wins. This explicit ranking is itself a principle: hierarchy beats handwaving.

---

## Principle 1: The user's job comes before everything else

Every screen exists because a user is trying to accomplish something. We identify the job to be done before we design the screen. We measure success by whether the user accomplished the job, not by how the screen looked while they tried.

The job to be done on the dashboard is "see whether my e-invoicing is healthy and identify what needs my attention". It is not "showcase ZeroKey's feature breadth" or "drive engagement metrics". The job to be done on the upload screen is "submit my invoice as fast as possible". It is not "educate the user about our intelligent extraction pipeline".

When the design begins to drift toward the product team's goals (educating the user, increasing engagement, surfacing features) and away from the user's goals, we redesign. This sounds obvious; in practice it is the most violated principle in the SaaS industry, and we will have to enforce it actively.

## Principle 2: One primary action per screen

Every screen has exactly one primary action — the thing the user is most likely there to do. The visual hierarchy makes that action unmistakable. Secondary actions exist but are visually subordinate. Tertiary actions are tucked into menus or hidden behind affordances.

On the dashboard, the primary action is "drop a new invoice". On the invoice review screen, the primary action is "approve and submit". On the customer master screen, the primary action is "find a customer". These are the actions where ZeroKey Signal accent appears. Every other action on the screen takes a quieter visual treatment.

The exception is the empty state, where the primary action is contextual to onboarding. We discuss empty states in their own principle below.

## Principle 3: Every action returns a confirmation

When a user does something, they need to know it happened. Every successful submit, save, delete, edit, upload, and export results in a confirmation that is unmistakable but not disruptive. The default form is an inline confirmation that appears at the action point: a brief animation on the button, a subtle slide of the affected row, a calm toast notification at the bottom of the screen.

We do not use modal alert dialogs to confirm successful actions. We use them only when an action requires a deliberate second confirmation (such as deleting a customer record that has invoices attached, or canceling a subscription).

We never show success toasts that linger longer than four seconds. We never queue multiple toasts that fight for attention. We never show a confirmation message in a place the user is not looking.

## Principle 4: Errors are explained, not announced

When something goes wrong, the user gets a complete answer: what happened, why it happened, what to do next, and a way to do it from where they are. No error message is allowed to be a dead end.

LHDN's MyInvois platform returns errors with codes like "DS302" or "BR-CL-21". These codes are useless to an SME. ZeroKey translates every LHDN error code into plain-language explanation in the user's preferred language, with a one-click suggestion to fix it. The original LHDN code is shown in a "technical details" section the user can expand if they want to share with their accountant.

Errors that come from our own system follow the same pattern. "We could not connect to MyInvois right now" is a useful error. "Service unavailable (502)" is not.

When the user is on the wrong path entirely (such as trying to issue a B2B invoice with a missing TIN), we do not just block the action; we explain why and offer the route forward. "This invoice is missing the buyer's TIN. We need it to submit to LHDN. Get the TIN from your buyer, or check our customer master."

## Principle 5: Defaults reflect reality

Every form field, every dropdown, every configuration option starts with the value the typical user will most likely choose. Defaults are not random; they are evidence-based decisions about what most users want most of the time.

The default invoice currency is MYR. The default tax type is SST. The default language at first run follows the browser locale, falling back to English. The default date format is DD/MM/YYYY. The default invoice prefix is the customer's company name slugged. The default approval workflow is single-step (the submitter is the approver).

When we have data showing what users actually choose, the defaults adjust to reflect that data. A default that is wrong half the time is a bug. A default that is wrong a quarter of the time is a feature request to make the default smarter.

## Principle 6: The first ten minutes determine retention

A new user's first ten minutes with ZeroKey set their long-term opinion of the product. We design those ten minutes with extreme care. The goal is for the user to have submitted their first real e-invoice within ten minutes of signing up. Every friction in that path is treated as a serious bug, not a minor polish item.

The first-run experience does not hide important features behind a tour. We do not insert a multi-step modal walkthrough between the user and their first action. We use empty states, helpful inline copy, and just-in-time tooltips that appear at the moment of relevance, then disappear.

The first invoice submission is the goal. The signup confirmation email celebrates the user's account. The dashboard empty state guides them directly to the upload action. The upload result screen, after their first successful submission, is the first moment we briefly highlight what just happened: "Your first invoice was extracted, signed, and submitted to LHDN in 47 seconds. Welcome to ZeroKey."

## Principle 7: Empty states do real work

An empty state is not a placeholder until the screen has data. It is one of our highest-value real-estate moments. The user is here for a reason — they navigated to this screen — and the empty state must respect that intent.

Every empty state answers three questions: what is this screen for, what should I do here first, and what will it look like when it is full. The dashboard empty state shows a friendly drop zone, three suggested ingestion channels, and a sample invoice the user can preview to understand what processed invoices look like. The customer master empty state explains that customers will appear here as the user submits invoices, and offers a one-click action to import existing customers from a spreadsheet.

Empty states never use the word "empty", "nothing", or any framing that suggests the user has done something wrong. They speak in opportunity, not absence.

## Principle 8: Progressive disclosure beats progressive overload

Showing the user everything they might possibly need is hostile design. Showing them what they need now, with quiet pathways to the rest, is respectful design.

The invoice review screen shows the eight most important fields up front. The remaining forty-seven fields are visible but visually subordinate, organized into expandable groups. Advanced settings (custom validation rules, webhook configurations, special tax treatments) live in a dedicated settings area, not in the main flow.

This applies to the marketing site too. The homepage shows the headline, the proof, and the trial CTA. Detailed feature lists, technical architecture, security certifications, and pricing tier comparisons are linked from there but not crammed into the homepage.

## Principle 9: Speed is a feature

Every interaction should feel instant. The internal benchmarks are: any click should produce visible feedback within 100ms, any data fetch should produce a result within 800ms, any background processing should expose progress so the user knows the system is working.

Where we cannot meet these benchmarks (an OCR pass on a complex scanned PDF takes several seconds, a batch submission to MyInvois may take a minute), we use optimistic UI updates and granular progress indicators. The user sees that something is happening; they are not staring at a spinner.

The application is offline-tolerant where it can be. Filling out an invoice form does not require a live server connection; the data is held locally and submitted when ready. Upload progress is shown as the file uploads, not after.

The marketing site is held to even stricter performance budgets. Initial paint under 1 second on a typical Malaysian mobile connection. Cumulative layout shift below 0.1. Interaction to next paint under 200ms. These are non-negotiable.

## Principle 10: The mobile experience is not a degradation

Half of our users will use ZeroKey primarily on a mobile phone. The mobile experience is designed first and adapted up to desktop, not the other way around. Every primary user flow — submitting an invoice, reviewing an exception, checking status — is fully completable on a phone screen.

The WhatsApp ingestion channel exists because mobile is the natural entry point for many of our users. They snap a photo of a printed supplier invoice, send it to ZeroKey's WhatsApp number, and ZeroKey processes it in the background. The user only opens the web or mobile app when they want to review or approve.

Mobile does not mean stripped down. It means rethought for thumb-driven navigation, single-column layouts, larger tap targets, and shorter text passages. Every feature available on desktop is available on mobile, even if the interaction shape is different.

## Principle 11: Confirmation is required only for the irreversible

We do not interrupt the user with "Are you sure?" dialogs for actions that can be undone. We provide undo. We do not show confirmation modals for actions that have no consequence. We just do the action.

We confirm only when the action is irreversible: deleting a customer with attached invoices that cannot be reattached, canceling a subscription mid-cycle, exporting and deleting an audit log archive. In these cases, the confirmation is informative — it states what will happen and what will not be recoverable — and requires a deliberate second action.

Most actions provide undo for at least ten seconds via a toast that says "Customer deleted. Undo." This is faster, kinder, and more accurate than asking permission upfront.

## Principle 12: The system explains itself

Every non-obvious behavior in ZeroKey has an explanation visible in context. Why did this invoice fail validation? What does "low confidence" mean on this extracted field? What is the difference between "Submitted" and "Validated" status? Why is this customer's TIN highlighted in amber?

The explanation lives where the question would be asked. We do not expect the user to dig into the help center to understand what they are looking at. Inline help text, expandable "why?" tooltips, and contextual sidebars carry the explanations.

When the explanation gets longer than a sentence, it links out to the help center; the link goes to the specific article that answers this exact question, not to the help center homepage.

## Principle 13: Bilingual users switch languages mid-session

Many Malaysian users are comfortable in two or more languages and switch fluidly during their workday. ZeroKey supports this naturally. Language can be switched from any screen with one tap; the switch is global and persists across sessions but does not require reauthentication. Switching language does not lose any in-progress work.

Some content is fundamentally not translatable: customer names, invoice descriptions, item descriptions entered by users. These appear in the original language regardless of UI language. ZeroKey never translates user-entered data automatically.

The four languages — English, Bahasa Malaysia, Mandarin, and Tamil — are equally first-class. There is no "primary" language with translation overlays. Each language has its own native content reviewed by a native speaker.

## Principle 14: Accessibility is correctness

Accessibility requirements are treated as correctness requirements, not as a separate accommodation track. A button without a focus state is broken. A color combination that fails WCAG contrast is broken. An icon-only button without an accessible label is broken. A form field without a properly associated label is broken.

These bugs are not classified as "accessibility issues" and triaged separately from "real bugs". They are bugs. They block release.

Specific commitments: every interactive element is reachable by keyboard. Every interactive element has a visible focus state in ZeroKey Signal at 2px outline. Every form input has an associated label. Every image has alt text or is marked decorative. Every action communicated by color is also communicated by icon and text. Dynamic content changes are announced to screen readers via appropriate ARIA live regions. The product is fully usable at 200% browser zoom. Reduced-motion preferences are respected.

## Principle 15: Trust is earned through small honest moments

The largest brand-trust moments in ZeroKey are not the marketing pages or the security badges. They are the small honest moments where most products lie or hide. We do not lie or hide.

When LHDN's platform is down, we say so on the dashboard immediately and explain that submissions are queued. We do not let the user retry failed submissions thinking the failure is theirs.

When extraction confidence is low on a particular field, we show the confidence visibly and ask the user to confirm. We do not auto-fill with high apparent certainty when we are not certain.

When our system has a bug, we acknowledge it. The status page is real. The post-incident review is published when the impact warranted it.

When a customer is approaching their plan limit, we tell them with enough notice to upgrade comfortably. We do not let them hit the wall and surprise-charge overage.

When a customer wants to cancel, the cancellation flow takes three clicks. There is no retention dialogue, no special offer designed to confuse, no last-chance discount that requires calling a support line. They came to cancel; we let them.

These small moments compound. After a year, a ZeroKey customer trusts us with their compliance work because they have noticed, dozens of times, that we tell them the truth even when it would be more convenient not to. This trust is the deepest moat we will ever build.

---

## How these principles relate to design execution

These principles are upstream of every component, every page, and every flow. The component library implements them. The design tokens implement them. The Figma library implements them. When a design is reviewed, it is reviewed against these principles, not against subjective taste.

When a principle and a design choice conflict, the principle wins or the principle is updated. We do not let principles become aspirational decoration that we ignore in practice. We update them when we have learned something that genuinely changes our position. We enforce them when we have not.

When new product surfaces are designed (new screens, new flows, new product lines under the ZeroKey umbrella), this document is consulted before design work begins. When this document and the actual product diverge, one of them is wrong, and we resolve the divergence deliberately.