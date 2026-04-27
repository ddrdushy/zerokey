# VISUAL IDENTITY — ZeroKey

> ZeroKey's visual identity is the design DNA inherited from Symprio, recalibrated for a product brand. Where Symprio uses a confident enterprise dark-mode aesthetic with technical precision, ZeroKey uses the same foundation with a warmer, brighter, more product-forward expression. The two should feel related at first glance and distinct on closer inspection — like sibling brands that grew up in the same household.

## Design philosophy

The visual identity follows three principles that override every other consideration.

The first principle is **clarity over decoration**. Every element on every screen earns its place by serving the user's task. Decorative gradients, illustrative flourishes, and visual ornaments are used sparingly and only when they support comprehension or emotion. The default is restraint. White space is treated as a primary design material, not as the empty area between things.

The second principle is **calm over excitement**. The aesthetic is closer to Linear, Stripe, Vercel, and Notion than to consumer apps that compete for attention with bright colors and bold movement. Customers come to ZeroKey under regulatory pressure; the product should feel like a quiet office where the work gets done, not a marketing demo trying to wow them. This applies particularly during error states and edge cases, where many products lose their composure.

The third principle is **respect for the localized reader**. The product runs in four languages, each with its own typographic needs. Tamil and Mandarin are not afterthoughts to an English-first design system; they are first-class citizens whose typographic requirements influence baseline grid, line height, and weight selection from the start.

## The Symprio inheritance

ZeroKey's visual identity is calibrated to feel like part of the same family as Symprio without being identical. The shared inherited elements are: a modern sans-serif type stack with a slightly warmer humanist quality, italicization of key brand phrases as a typographic device (Symprio uses *italicized phrases* in headlines; ZeroKey adopts the same pattern), generous whitespace, numbered methodology and process sections with large numerals, partnership and trust-marker bands, large stat callouts in product surfaces, and a strong dark-surface aesthetic for marketing.

The differentiated elements that make ZeroKey distinctly itself are: a brighter, lighter primary product surface (because the working environment is daily SME use, not a marketing site), a distinctive accent color that is unmistakably ZeroKey's own, the recurring "drop" visual motif (representing both the file drop and the cryptographic key drop), softer rounded corners on UI components than Symprio uses, and warmer photographic and illustrative content focused on small Malaysian businesses rather than enterprise environments.

## Color system

The color system is designed to work in two contexts: marketing surfaces (where dark backgrounds and high-contrast typography read as premium and confident) and product surfaces (where light backgrounds reduce eye strain during long working sessions and feel approachable to non-technical users). Both contexts use the same palette; only the dominant surface color differs.

### Primary palette

The primary brand color is **ZeroKey Ink**, a near-black with subtle blue-violet undertone. Hex value is `#0A0E1A`. RGB is 10, 14, 26. This color is used for primary text on light backgrounds, for the dominant marketing-page background, for navigation, and for the wordmark itself. It reads as more thoughtful than pure black and as more grounded than a true blue-black. It pairs cleanly with both warm and cool accents.

The primary background color for product surfaces is **ZeroKey Paper**, a slightly warm off-white. Hex value is `#FAFAF7`. RGB is 250, 250, 247. This is the dominant surface color in the application UI. It is warmer than pure white, less stark on long sessions, and feels more inviting in a workspace context. It also reduces the cool-blue cast that pure white surfaces give photography and PDFs displayed inline.

### Signal accent

The single accent color that defines ZeroKey is **ZeroKey Signal**, a confident lime-green. Hex value is `#C7F284`. RGB is 199, 242, 132. This is used sparingly: on the primary call-to-action button, on the active state of the file drop zone, on the success indicator, on the validation passed badge, and as a minor highlight in marketing illustrations. It is never used as a large surface color. It must always meet WCAG AA contrast against ZeroKey Ink for any text use.

The reasoning for choosing lime over the more common SaaS blue: the category is saturated with blue (every accounting software, every tax tool, every government portal). Lime is energetic without being aggressive, optimistic without being childish, and unmistakably distinctive in the Malaysian fintech landscape. It also pairs naturally with ZeroKey Ink and ZeroKey Paper without competing for attention.

### Supporting neutrals

The neutral scale provides the working surfaces for product UI. These are warmer than typical gray scales to harmonize with ZeroKey Paper.

**Slate 50** at `#F4F4EE` is for subtle background fills, hover states on table rows, and inactive card surfaces.
**Slate 100** at `#E8E8E0` is for borders on light surfaces, divider lines, and disabled component backgrounds.
**Slate 200** at `#D1D1C5` is for stronger borders, input field outlines, and inactive button outlines.
**Slate 400** at `#8A8A7F` is for secondary text, placeholder text, and tertiary metadata.
**Slate 600** at `#4A4A42` is for body text on light backgrounds when ZeroKey Ink would feel too heavy.
**Slate 800** at `#1F1F1A` is for surfaces just slightly lighter than ZeroKey Ink, used in marketing for layered dark sections.

### Semantic colors

Semantic colors are used only for their semantic purpose, never for decoration. They are calibrated to be legible without screaming.

**Success** is `#3FA568`, a confident forest green. Used on validation passed states, successfully submitted invoices, paid status, and positive trend indicators.

**Warning** is `#E8A93A`, a warm amber. Used on attention-required states, low-confidence extraction warnings, approaching plan limit indicators, and reminder notifications.

**Error** is `#D4533F`, a muted brick red. Used on validation failures, LHDN rejections, payment failures, and destructive action confirmations. Never the saturated emergency red of consumer apps.

**Info** is `#4A6FB0`, a calm steel blue. Used on neutral notifications, in-progress states, and informational tooltips.

### Marketing-only accent

For marketing surfaces and storytelling, an additional warm accent **ZeroKey Glow** at `#F5E1A8` is permitted. This is a soft butter-yellow used in illustrations, hero gradients, and editorial photography color grading. It is not used in product UI.

### Color use rules

Two colors should dominate any single screen: ZeroKey Paper (or ZeroKey Ink, in marketing dark mode) and one neutral from the slate scale. ZeroKey Signal appears at most twice on a single screen. Semantic colors appear only when their semantic meaning is being communicated. Gradients are reserved for marketing hero sections and major landing surfaces; they do not appear in product UI.

## Typography

The typographic system is built around three faces, each with a clear and non-overlapping role.

### Primary typeface — Inter

**Inter** is the primary product UI typeface. It is used for body text, navigation, button labels, form fields, table contents, dashboard metrics, and every routine product surface. The choice reflects three considerations: Inter is a modern humanist sans-serif designed specifically for screen reading, which fits our daily-use product context; it has excellent multilingual coverage including the Malay diacritics that local user names require; and it is the de facto standard for modern SaaS products, which means our product reads as part of the family of tools our users recognize as quality.

Inter is used at weights 400 (regular), 500 (medium), 600 (semibold), and 700 (bold). The 500 weight is the default for product UI labels and small text where regular feels too thin against light backgrounds. The 600 weight is the default for headings and emphasis. The 700 weight is reserved for hero-level marketing typography and large numerical metrics.

### Display typeface — Geist

**Geist** is the display typeface for marketing surfaces, hero headlines, the wordmark, and major editorial moments. Designed by Vercel and released under SIL Open Font License, Geist carries a confident, slightly more geometric character than Inter and creates the sibling-but-distinct relationship with Symprio's own type stack. It is used at 600 (semibold) and 700 (bold) weights only.

Geist is the typeface of the wordmark itself. The ZeroKey wordmark is set in Geist Bold with custom kerning between the K and the next character to slightly tighten the visual mass.

### Monospace typeface — JetBrains Mono

**JetBrains Mono** is the monospace face used for code samples in developer documentation, for invoice IDs and TIN numbers in detail views (where character-level precision matters), and for any technical identifier that benefits from monospaced alignment. It is used only at 400 (regular) and 500 (medium) weights.

### Multilingual stack

For the three non-Latin language surfaces, a layered font stack is used. For Bahasa Malaysia content, Inter handles all needed glyphs natively. For Mandarin content, the stack is Inter, then **Noto Sans SC** (Simplified Chinese), then system fallback. For Tamil content, the stack is Inter, then **Noto Sans Tamil**, then system fallback. Both Noto faces are loaded only when the user's locale requests them, to avoid unnecessary font weight on the main bundle.

### Type scale

The product UI type scale uses a 1.25 modular scale anchored at 16px base. The resulting sizes are 12, 14, 16, 18, 20, 24, 30, 36, 48, and 60 pixels. These are not arbitrary; they correspond to specific roles in the interface.

**12px** is for tiny labels, badges, and metadata where information density matters more than reading comfort.
**14px** is for table cells, secondary metadata, form field hints, and small UI labels.
**16px** is the body text baseline. All long-form reading happens at this size.
**18px** is for slightly emphasized body text, summary statements, and important paragraphs.
**20px** is for small section headings within product UI.
**24px** is for card titles and major section headings within product UI.
**30px** is for page titles within product UI and small marketing headings.
**36px** is for major marketing section headings.
**48px** is for hero subheadings on marketing pages.
**60px** is reserved for marketing hero headlines.

Line height defaults to 1.5 for body text, 1.4 for medium headings, and 1.2 for display headings. Tamil and Mandarin surfaces use slightly more generous line heights (1.55 for body) to accommodate the visual mass of their glyphs.

### The italics device

Following the Symprio family pattern, italicized fragments within headlines are used as a typographic emphasis device. Where Symprio writes "Build Your AI-Powered *Digital Workforce*" with the key concept italicized, ZeroKey adopts the same pattern: "Drop the PDF. *We do the rest.*" or "Built for the Malaysian *small business*." This is a brand-level pattern, not a CSS suggestion. The italicized phrase always carries the conceptual emphasis.

## The wordmark

The ZeroKey wordmark is the primary brand artifact. It is set in Geist Bold, all letters in their correct case (capital Z, lowercase e, r, o, capital K, lowercase e, y), with custom letter-spacing that slightly tightens the gap between the joined "Zero" and "Key" components without removing the semantic separation.

The wordmark exists in three lockup variants. The standalone wordmark is the default, used on the product itself and most marketing surfaces. The "by Symprio" lockup positions a smaller "by Symprio" tag to the right of and below the wordmark, in a 60% reduced size and Slate 400 color, separated by a thin vertical rule. This lockup is used on enterprise materials, in legal documents, and in the footer of every marketing page. The third variant is the icon-only mark, a stylized representation derived from the wordmark, used as an app icon, favicon, social media avatar, and any constrained square format.

The icon-only mark is the letter "K" in Geist Bold, ZeroKey Ink color, on a ZeroKey Paper background, with a small ZeroKey Signal dot positioned at the upper-right corner of the K. The dot represents both the "key drop" gesture and the activation indicator. This icon mark is the only piece of identity that uses the Signal color in a non-interactive context, and the prominence is justified by its scale-down legibility.

The wordmark must always have clear space around it equal to half the height of the wordmark itself. It must never be placed on a background that reduces its contrast below WCAG AA standards. It must never be stretched, skewed, recolored beyond ZeroKey Ink and ZeroKey Paper, embellished with stroke or shadow, or set in any typeface other than Geist Bold.

## The drop motif

ZeroKey has a recurring visual element: the **drop**. This represents both the user gesture (dropping a file) and the security gesture (dropping the keys to KMS). It is a single geometric primitive — a softly rounded square approximately at a 4:5 aspect ratio with a slightly more rounded top — used throughout the visual system as both a graphic element and an interaction target.

In product UI, the drop appears as the file upload zone shape, as the empty-state illustration center, and as the iconography frame for ingestion channel icons. In marketing surfaces, it appears as the primary illustrative motif for hero sections, as the visual anchor for major feature explanations, and as a subtle background element in long-form content layouts.

The drop is never used as decorative wallpaper. It always carries meaning: an action target, a content container, or a brand signature.

## Iconography

ZeroKey uses a custom but lightly-customized icon system based on **Lucide** (the open-source icon library used by Vercel, Linear, and many modern SaaS products). Lucide's geometric clarity and consistent stroke weight match our brand voice. We use Lucide directly without modification for ninety percent of our icon needs.

Where Lucide does not provide an icon for a Malaysia-specific concept (such as the MyInvois logo treatment, the LHDN status indicator, or the SQL Account connector), we commission custom icons drawn in the same geometric style: 24px artboard, 1.5px stroke weight, rounded line caps, no fills except where semantically required. All custom icons are created and stored centrally; one-off icon creation in product code is forbidden.

Icons are sized at 16px, 20px, 24px, or 32px in product UI; sizes outside this set require explicit justification. Icon color follows the surrounding text color or the semantic state color, never an arbitrary brand accent.

## Motion

Motion is purposeful and restrained. Three principles guide it.

The first principle is **physics-based, not decorative**. Movement uses easing curves that mimic real-world acceleration and deceleration. The default ease is a custom curve approximating `cubic-bezier(0.16, 1, 0.3, 1)`, which feels present and responsive without being playful. Linear easing is used only for indeterminate progress indicators. Bounce, elastic, and other showy easings are not used.

The second principle is **scaled to the action**. Tiny acknowledgments — a button hover, a checkbox toggle — happen in 100–150ms. Page transitions and panel slides happen in 200–250ms. Larger contextual changes — opening a detail drawer, switching between major dashboard sections — happen in 300–400ms. Nothing exceeds 500ms, ever.

The third principle is **respect for reduced-motion preferences**. Users who have set their operating system to reduce motion get a near-instant version of every transition: opacity changes only, no slide or scale, durations capped at 80ms. This is not a fallback; it is a first-class state.

The drop zone has one exception to the restrained motion principle. When the user drags a file over it, the zone responds with a subtle scale and color shift to confirm the drop target is active. This single interaction is permitted to feel slightly more enthusiastic than the rest of the UI because it is the central gesture of the product.

## Photography and illustration

When real photography is used in marketing surfaces, the subjects are **Malaysian small business contexts**: an SME owner reviewing invoices on a laptop in a small office; a bookkeeper at a desk with paper documents and a phone; a delivery driver receiving a printed invoice; a coffee shop owner closing out the day. The photographs are warm, natural-light, and feel like they could have been taken in Klang, Penang, Kota Kinabalu, or Kuching. They are not stock photographs of Western office workers in suits.

We commission this photography rather than using stock libraries when budget allows. Where stock is unavoidable, we filter aggressively for authenticity to the Malaysian context and avoid the polished-corporate aesthetic that signals "this is just another tax software vendor".

When illustration is used, the style is **minimal geometric line illustration in ZeroKey Ink with selective ZeroKey Signal accents**, on ZeroKey Paper or transparent backgrounds. Illustrations are functional: they explain a concept, anchor a feature, or guide a workflow. They are never decorative in the sense of "fill the empty space".

Heavy 3D renders, isometric illustrations, gradient-saturated abstract shapes, and the corporate-purple-blob style of mid-2020s SaaS marketing are explicitly avoided.

## Layout and grid

Marketing surfaces use a 12-column grid with a maximum content width of 1280px. Margins on desktop are 80px minimum on either side of the content area; on tablet, 32px; on mobile, 20px.

Product UI is built on an 8px baseline grid. All spacing values are multiples of 4 (4, 8, 12, 16, 24, 32, 48, 64). Spacing values outside this scale require explicit justification.

The primary product layout is a fixed left navigation rail at 240px width, a top bar at 56px height, and a flexible content area filling the remaining space. The detail drawer slides in from the right at 480px width. The mobile layout collapses navigation into a bottom tab bar with five primary destinations.

## Component library and design tokens

The product UI is built on a customized version of **shadcn/ui** with Tailwind CSS. The shadcn baseline gives us accessibility-tested components and a sane default styling system. The customization layer applies our color tokens, typography tokens, and spacing tokens.

All design values — colors, typography, spacing, border radius, shadow elevation, motion duration, motion easing — exist as named tokens in a single source-of-truth file consumed by Tailwind, the marketing site, the product UI, and design tools (Figma). A change to a token propagates everywhere. Hardcoded values in component code are not permitted.

The token names follow a semantic-over-literal convention. Colors are referenced as `text-primary`, `surface-elevated`, `border-default`, `accent-signal`, not as `slate-600`, `paper`, `signal`. The literal values are an implementation detail that may change; the semantic roles are stable.

## Accessibility

All visual identity decisions are subject to accessibility constraints. Text against any background must meet WCAG AA contrast (4.5:1 for body text, 3:1 for large text). Interactive elements must have a minimum 44px tap target on mobile. Focus states use a visible outline in ZeroKey Signal at 2px weight; this outline is never removed for visual cleanliness. Motion respects the user's reduced-motion preference. Color is never the sole carrier of information; semantic states always pair with an icon or text label. Dynamic text resizing up to 200% must not break layout.

These constraints are not afterthoughts. They are part of the brand. A Malaysian SME owner with low vision or motor impairment is a customer we want to serve, and the visual identity is built to include them.

## Brand asset library

All brand assets — wordmark in every variant and color, icon mark in every size, color tokens in every format, type files, photography, illustrations, marketing templates — live in a centralized brand asset library at `brand.zerokey.symprio.com` (eventually) or in a shared Figma file (initially). Anyone working on ZeroKey marketing or product surfaces pulls from this library; nothing is recreated locally.

The library is versioned. When the visual identity evolves, a new version is published with clear migration notes for any consumers. Breaking changes to the wordmark or primary palette require explicit founder approval; smaller adjustments (a new icon, a new illustration style) are at the discretion of whoever owns brand work at the time.

## How this document is used

When a new visual surface is being designed — a new marketing page, a new product screen, a new ad, a new pitch deck — this document is consulted before any design work starts. When a question arises about whether a specific design choice fits the brand, this document is the authority. When this document and the actual product diverge, the document is updated to reflect the new reality, or the product is brought back into alignment with the document. Drift is not tolerated.