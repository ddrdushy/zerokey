# ENGINE REGISTRY — ZeroKey

> The pluggable AI engine architecture. ZeroKey treats OCR engines and language models as interchangeable commodities behind a stable abstraction. This document specifies the abstraction, the routing logic, the cost and quality tracking, and the operational discipline that keeps us vendor-independent at the most strategically important layer of our stack.

## Why pluggable engines matter

The OCR and language-model layer is the highest-cost, fastest-moving, and most strategically risky component of ZeroKey. A single decision to lock into a particular vendor — Azure for OCR, OpenAI for language — would be the most consequential architectural mistake we could make.

Three forces make vendor lock-in unacceptable here. First, **prices change rapidly in unpredictable directions**. Language model pricing has dropped by orders of magnitude over the past two years, but new model releases sometimes come with higher initial pricing before settling. A platform locked to a specific vendor cannot route around adverse pricing changes. Second, **quality leadership rotates**. The best model for invoice extraction in March 2026 may not be the best in September 2026. Vendor competition is fierce and reordering happens every few months. We need to route to whichever vendor is currently best for our specific workload. Third, **enterprise customers sometimes mandate specific vendors**. A BFSI customer may require AWS-only deployment for their data residency or vendor-management reasons. A government-linked customer may require Malaysia-hosted models. Without a pluggable architecture, we cannot serve these deals.

The engine registry is therefore not just a coding pattern. It is a strategic moat. Every quarter that we maintain optionality is a quarter that compounds into pricing leverage, quality optimization, and enterprise sales credibility.

## The capability interfaces

The registry exposes a small number of capability interfaces. Each capability defines a stable contract that any registered engine must satisfy. Application code calls capabilities, never specific engines.

The **TextExtract** capability accepts a document (PDF, image, or any supported format) and returns the raw text content with positional metadata. This is implemented natively for native PDFs (using libraries like pdfplumber, no external engine needed) and through OCR engines for scanned documents and images.

The **VisionExtract** capability accepts an image or visual document and returns structured invoice fields directly, bypassing the intermediate text extraction step. This is the vision-language-model path used as a fallback for low-confidence OCR or for documents where layout matters more than text content.

The **FieldStructure** capability accepts raw text (typically from a TextExtract call) and a target schema (the LHDN field set) and returns structured field values with confidence scores. This is implemented through language models — Claude, GPT, Gemini, Mistral, etc.

The **Embed** capability accepts text and returns a vector representation. Used for semantic search in MSIC code suggestion and item master matching. Implemented through embedding models (OpenAI text-embedding-3, Cohere embed, Voyage, multilingual models).

The **Classify** capability accepts text and a target classification schema and returns the best-fit class with confidence. Used for things like detecting whether an invoice is self-billed, whether a transaction crosses the RM 10,000 threshold context, and similar discrete decisions. Implemented through small fast classification models or distilled prompts on larger models.

The **TIN/MSIC verification** capabilities are wrappers around external APIs (LHDN's TIN verification endpoint, the locally cached MSIC catalog) and not strictly AI engines, but they are exposed through the same registry abstraction so that the calling code is uniform.

## The engine adapter pattern

Each engine in the registry is a thin Python adapter conforming to one or more of the capability interfaces. An adapter encapsulates the vendor-specific authentication, request shaping, response parsing, error mapping, and metric emission.

A typical adapter is small — a few hundred lines at most — because the heavy lifting happens at the vendor's API. The adapter's job is to translate between our stable internal contract and the vendor's wire protocol. When a vendor changes their API (which they do, with frustrating regularity), only the adapter needs to be updated; the rest of the codebase is insulated.

Adapters are versioned. When a vendor releases a new model version (Claude Sonnet 4.7 succeeds Claude Sonnet 4.6, GPT-5 succeeds GPT-4o), a new adapter version is registered, the old one is kept active for compatibility, and routing rules can switch over deliberately.

## The launch engine roster

ZeroKey launches with the following engine roster, registered in priority order for each capability. This roster is configurable from the super-admin console; the values below are the initial seed configuration.

### TextExtract capability

The primary native-PDF text extractor is **pdfplumber**, a Python library running in-process. It handles the majority of native PDF invoices with no external API call. Cost is essentially zero (compute only). Latency is hundreds of milliseconds.

The secondary extractor for native PDFs that pdfplumber struggles with (complex layouts, mixed text/image PDFs) is **PyMuPDF**, also running in-process. It catches edge cases pdfplumber misses.

For scanned PDFs and images, the primary engine is **Azure Document Intelligence** (formerly Form Recognizer). Azure was chosen for the launch primary because it has the most mature document AI capability in the major cloud vendors, has excellent multilingual support including Malay text and printed Tamil and Mandarin, and runs in the same data-residency region we use. Cost is approximately a few cents per page. Latency is a few seconds.

The secondary OCR engine is **AWS Textract**. Useful for customers (especially BFSI) who require AWS-only routing. Cost similar to Azure.

The tertiary OCR engine is **Google Document AI**. Slightly behind on Malay-specific accuracy but excellent on English and Mandarin. Used selectively when customer preference dictates.

For local fallback (when no external engine is reachable, or for cost-sensitive customers), **PaddleOCR** runs on dedicated GPU instances in our infrastructure. Quality is below cloud vendors but good enough for many cases. Cost is amortized infrastructure only. Tesseract is registered as a final fallback for situations where even PaddleOCR is unavailable.

### VisionExtract capability

The primary vision engine is **Anthropic Claude Sonnet** (the latest version available, currently Claude Sonnet 4.6). Claude was chosen for the launch primary because of its strong document-understanding accuracy, its conservative output behavior (less hallucination on field extraction), and the founder's prior experience with the Anthropic API stack. Cost is a few cents per invoice. Latency is several seconds.

The secondary vision engine is **OpenAI GPT-4o** or its successor. Good multilingual support and competitive pricing.

The tertiary vision engine is **Google Gemini Pro Vision**. Useful for Mandarin-heavy documents where Gemini sometimes outperforms.

### FieldStructure capability

The primary structuring engine is **Anthropic Claude Sonnet**. Same reasoning as vision: good calibration, low hallucination rate on structured outputs.

The secondary is **OpenAI GPT** (GPT-5 mini for cost-sensitive cases, GPT-5 full for complex cases). 

The tertiary is **Mistral Large**. Useful for cost-sensitive paths and as a check against vendor concentration risk. Some Custom-tier deployments may also use **Llama 3.x via self-hosted inference** for customers who require fully on-premise model serving.

### Embed capability

The primary embedding engine is **OpenAI text-embedding-3-large** for English-dominant content.

The secondary is **Cohere multilingual-v3** for Malay, Mandarin, and Tamil content.

The tertiary is **a self-hosted multilingual model** (currently a fine-tuned variant of multilingual E5) for customers requiring on-premise inference.

### Classify capability

Classification jobs are routed through whichever language model is currently routing the FieldStructure capability for the same job, since the additional cost of one more prompt is negligible compared to switching engines mid-pipeline.

## The routing logic

Routing is the heart of the engine registry. For every job, the routing logic selects the engine to call based on a set of inputs and a set of rules.

The inputs to routing include the job type (which capability is being requested), the file characteristics (type, size, page count, language detection), the customer's plan tier, the customer's per-customer engine preferences if any (Custom-tier deployments often have specific engine requirements), the engine's current health status (degraded engines are skipped), and the engine's recent quality and cost statistics.

The rules are stored in PostgreSQL as `EngineRoutingRule` entities. Each rule has a priority, a condition expression evaluated against the inputs, the chosen engine, the fallback engine chain, and an active flag. The rules are evaluated in priority order; the first matching rule selects the engine.

The default rules at launch route as follows. Native PDFs go to pdfplumber for TextExtract. Scanned PDFs and images go to Azure Document Intelligence for TextExtract, with a confidence threshold below which the result is escalated to vision. FieldStructure jobs go to Claude Sonnet. Vision jobs (escalated from low-confidence text extraction, or chosen directly for layout-heavy documents) go to Claude Sonnet vision. Embedding jobs go to OpenAI text-embedding-3-large for English content and to Cohere multilingual for non-English content. Self-hosted PaddleOCR is used only when both Azure and AWS are unhealthy.

These rules are admin-editable. As we accumulate evidence about which engines perform best for our specific workload, the rules tighten. The rules are versioned, and changes are audit-logged.

## The fallback chain

Every routing rule includes a fallback chain. When the primary engine fails (timeout, rate limit, vendor outage, an explicit error response), the next engine in the chain is tried automatically. The customer never sees the failure; they see only that their invoice took slightly longer to process.

Fallback retries use a budget. Each job has an overall budget — say, three engine attempts — before it is escalated to the customer's exception inbox as "we couldn't process this automatically." This prevents pathological cases from running forever or costing many times the normal per-invoice cost.

Each fallback attempt is recorded with the engine, the failure reason, the timestamp, and the next engine. This data feeds the engine health monitoring discussed below.

## Engine health monitoring

Every engine call is tracked. For each engine, the system maintains rolling statistics over the past five minutes, the past hour, and the past day. The tracked metrics include success rate (proportion of calls returning success), average latency (mean and 95th percentile), error rate by class (timeout, rate limit, malformed response, vendor error), confidence outputs (where applicable), and per-call cost (computed from vendor pricing tables).

When an engine's success rate drops below a threshold (default 90% over the past five minutes), the engine is marked as degraded and routing skips it temporarily. The degradation is reported to the operations dashboard. When the success rate recovers, the engine is restored to active routing.

When an engine is consistently slow (95th-percentile latency above its expected baseline by more than two times for an extended period), it is similarly de-prioritized.

Vendor outages are detected through this mechanism without us needing to know about them in advance. When OpenAI has a region outage, calls to OpenAI engines start failing, our metrics catch it, and routing falls back to alternates while we wait for the recovery.

## Cost tracking and routing-by-cost

Every engine call records its computed cost based on the vendor's pricing for that specific request shape (tokens consumed, pages processed, embedding count). The cost is attributed to the originating Invoice and aggregated for cost-per-customer and cost-per-plan analysis.

Cost-aware routing is a P1 capability. Once we have several months of cost data per engine, we can introduce rules that prefer cheaper engines for cost-sensitive paths (Starter-tier customers, batch processing of low-priority invoices) while reserving the more expensive engines for high-priority and high-confidence-required paths (Pro and Custom tier, exception-inbox cleanups, customer-specific deals).

Cost routing is never visible to the customer at the per-invoice level. From their perspective, every invoice is processed; only the engine selection differs internally.

## Quality calibration

Different engines produce different confidence scores with different distributions. A "0.85 confidence" from Claude is not necessarily the same as "0.85 confidence" from GPT or Azure. The registry maintains a per-engine calibration curve that maps the vendor's reported confidence to a normalized confidence score that downstream code can compare meaningfully.

Calibration curves are computed offline from labeled extraction data. The labeled set comes from invoices the customer has reviewed and corrected — every correction is a ground-truth signal. As the labeled set grows, calibration improves. Recalibration runs weekly.

The calibration is stored as a per-engine, per-field calibration object. The supplier-TIN field on Azure may have a different calibration curve than the line-item-quantity field on Azure, because the engine's reliability varies across field types.

## Customer-specific engine preferences

Some customers, particularly Custom-tier deployments and BFSI customers, have specific engine requirements. The data model supports this: per-Organization engine overrides specify which engines may or may not be used for that customer's jobs. Common overrides include "AWS only" (replacing Azure with AWS Textract), "no OpenAI" (replacing OpenAI with Anthropic or Mistral for vendor-management reasons), and "self-hosted only" (using only our PaddleOCR and self-hosted Mistral/Llama options for fully on-premise BFSI deployments).

These overrides are configured by super-admin staff at deal close and are visible in the customer's account record. They are not customer-self-serviceable; the cost and quality implications are negotiated as part of the deal.

## Adding a new engine

The process for registering a new engine has multiple steps to ensure quality.

First, the engine is registered as a new adapter implementing the relevant capability interfaces, following the same pattern as existing adapters. The adapter is reviewed for proper error handling, observability, and credential handling.

Second, the engine is run in shadow mode against a sample of production traffic, where the routing system selects the existing engine as the primary but also calls the new engine in parallel for comparison. Shadow mode runs for at least a week, collecting per-field quality and cost data.

Third, the shadow data is analyzed. The new engine is graduated to the registered roster only if its quality is competitive with or better than existing engines for the cost. If it is competitive but not strictly better, it is added as a fallback option for resilience and as a hedge against vendor concentration.

Fourth, routing rules are updated to incorporate the new engine for the appropriate paths. These changes are made in the super-admin console, audit-logged, and rolled out gradually.

Fifth, the launch is announced to the team and noted in the public changelog if it is customer-visible (for customers with engine preferences in their plans).

## Removing or deprecating an engine

The process for removing an engine mirrors the addition process. Deprecation is announced internally and (for customer-affecting cases) externally. Routing rules are gradually shifted away from the deprecated engine over weeks. Once production traffic to the engine has dropped to zero for a sustained period, the adapter code is archived (kept in source history but removed from active wiring). Configuration entries are marked as inactive; they are not deleted, since historical AuditEvents may reference them.

## Vendor independence as a structural property

The architecture deliberately avoids any non-trivial dependency on a specific vendor's ecosystem. We do not use OpenAI Assistants API or function calling in vendor-specific shapes; we use chat-completion-style calls with structured output prompts, which all major vendors support. We do not store vendor-specific document IDs; we always route through our internal Invoice and IngestionJob entities. We do not use vendor-specific embeddings without going through the Embed capability that produces our internal vector representation; switching embedding providers requires re-embedding our corpus, but this is a planned operation, not a vendor lock-in.

The few places where vendor-specific behavior matters — Anthropic's prompt caching, OpenAI's structured output mode, Azure's prebuilt invoice models — are handled inside the adapter and exposed only as performance optimizations behind the stable capability interface.

## Observability and auditability

Every engine call is logged to the central observability stack with the engine, the capability, the input shape (size, type), the output shape, the latency, the success status, the cost, the confidence (where applicable), and a request identifier that ties back to the originating Invoice and IngestionJob.

When a customer asks "why was this invoice processed differently than the last one?" or "why was the cost on this batch higher than usual?", the engine call logs are the answer.

Engine calls that touch customer data are also recorded in the AuditEvent log per the audit specification. The audit entry records the engine identity, the call reason, and a content-hash of the data sent and received (without storing the data itself, to minimize PII exposure in the audit log).

## How this document evolves

When a new engine is registered, this document is updated to reflect the new roster. When a routing rule changes meaningfully, this document is updated. When a vendor releases a new model version that we adopt, this document is updated.

When a customer asks "what AI vendors does ZeroKey use?", the answer comes from this document. We are honest about our roster; we are not coy. Vendor independence is a feature, not a secret.
