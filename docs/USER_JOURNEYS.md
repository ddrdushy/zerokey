# USER JOURNEYS — ZeroKey

> Eight end-to-end journeys describing how each persona moves through ZeroKey from first awareness through everyday use. Journeys are written as prose narrative, not as flow diagrams. The point is to anchor every screen, email, notification, and edge case to a real human moment, not to produce a process map.

## How to read these journeys

A journey describes a real human's path through a real situation. Each one names the persona, the trigger, the path, the moments of friction or delight, the touchpoints involved, and the success state. Journeys are written from the persona's point of view, with our internal product responses described from the outside. When designing any new feature, the test is whether it serves at least one of these journeys without harming the others.

The journeys are ranked by acquisition order and lifecycle position. The first three cover acquisition and first-use. The next three cover ongoing daily and weekly work. The last two cover edge cases — the angry customer and the audited customer — that disproportionately determine our brand reputation.

When this document and the actual product diverge, the document is updated to match the new reality, or the product is brought back into alignment. Journeys are living artifacts.

## Journey 1 — Aisyah discovers ZeroKey and signs up

Aisyah is at her desk on a Wednesday afternoon in May 2026. Her bookkeeper has just left after their monthly check-in, and the conversation circled, again, to the LHDN e-invoicing mandate. Her bookkeeper mentioned that two of her other clients started using "some new app" last month and seemed happy with it. Aisyah did not catch the name. She opens Chrome, types "lhdn e invoicing for sme malaysia" into Google, and starts scanning results.

The third result is a guide on the ZeroKey blog titled "What every Malaysian SME needs to know about LHDN MyInvois Phase 4." Aisyah clicks because the title is plain. The article opens with a calm, factual paragraph that does not panic her about January 2027. It explains the mandate, the threshold, the penalty regime, and the data fields, in language she understands. Halfway through the article, a soft inline link mentions ZeroKey as one option for SMEs who do not want to type invoices into MyInvois Portal manually. The article does not push her toward signup; it just informs.

Aisyah finishes the article and clicks through to ZeroKey's homepage. The hero says "Drop the PDF. Drop the Keys. Malaysian e-invoicing on autopilot." She reads the supporting line: "We accept any invoice format and submit to LHDN automatically. Built by Symprio for Malaysian SMEs." She has never heard of Symprio specifically but the name sounds Malaysian, which is reassuring; she is wary of foreign-owned tools handling her tax data.

She scrolls. She sees three short proofs: works with any invoice format, auto-extracts every field, learns from your corrections. She sees a small partnership bar with the LHDN logo, the Symprio logo, and Malaysia Digital (MDEC) accreditation. She sees pricing right there on the page — RM 99, RM 299, RM 799, RM 1,999, plus Custom for larger needs. She does not have to click "Pricing" or "Get a quote." This matters to her.

She clicks "Start free trial." The signup form asks for her name, her business name, her email, and her preferred language. No credit card. Two minutes later, she is logged in. The dashboard is mostly empty. A central drop zone says: "Drop your first invoice. Or send it to **aisyah-trading-7k4m@in.zerokey.symprio.com**, or WhatsApp +60-XX-XXXX-XXXX." Three big channels, each with a small icon.

Aisyah opens her email, finds a recent invoice from a supplier — a PDF for raw material she ordered last week — and forwards it to the email address ZeroKey gave her. Within ninety seconds, the dashboard shows a new card: the supplier's logo, the invoice number, the amount, status "Extracting." Forty seconds later, status changes to "Ready for review." She clicks.

The review screen shows the original PDF on the left and a clean form on the right with every field filled in. Two fields are highlighted in soft amber: the supplier's TIN ("we were not sure about this — please confirm") and the MSIC code on one of the line items ("we suggested 46411 — Wholesale of pharmaceuticals — please verify"). She knows the supplier's TIN by memory; she pastes it in. She accepts the suggested MSIC code because that is in fact what they sell.

She clicks "Submit to LHDN." A small modal asks her to upload her LHDN-issued digital certificate, with a one-line explanation that the certificate is encrypted and stored in a separate hardware-backed key system, never in ZeroKey's database. There is a "How do I get my digital certificate?" link beside the upload field. She has the certificate file from when she registered with MyInvois three months ago in a panic; she finds it, uploads it, sets a passphrase. The certificate uploads in three seconds.

She clicks Submit again. The dashboard updates: status "Submitted to LHDN," then thirty seconds later "Validated." A QR code appears on the invoice card. The card shows: "Sent to LHDN. ID generated. Here is the QR code." She has just submitted her first e-invoice. The whole process from clicking the email forward button to seeing the QR code took under five minutes.

A toast in the corner says: "First invoice complete. Welcome to ZeroKey. Drop your next one anytime." A small banner at the top reminds her: "You are on the 14-day free trial. 19 invoices remaining."

Aisyah leans back in her chair. She had been dreading this for weeks. It was less work than her last grocery order on FoodPanda. She closes the laptop without opening another tab, takes a sip of teh tarik, and decides that on Friday, when her bookkeeper comes back, she will mention it casually. Maybe ask if she could put all her clients on this.

This is the journey we are designing for. This is the ten-minute first-success that determines whether Aisyah ever opens ZeroKey again.

## Journey 2 — Wei Lun evaluates and adopts ZeroKey

Wei Lun has had ZeroKey on a tab since Tuesday. His managing director forwarded him a LinkedIn post about it last week and asked him to "look into it." Wei Lun has already evaluated three other tools this quarter, so he is not enthusiastic about another evaluation. But he opens the tab on Friday morning over coffee and starts scanning.

He goes straight to the pricing page. He reads it in ninety seconds. Five tiers, prices visible, what is included clearly listed, no "Contact us." He notes the Pro tier at RM 1,999 includes SSO and multi-entity, which he might want eventually but does not need yet. He decides Growth at RM 299 is probably his target, with maybe an upgrade to Scale at RM 799 once they hit volume. He likes that the upgrade path is obvious.

He clicks "Start free trial" and signs up using his work email. Two minutes later he is in. The dashboard shows the same drop zone Aisyah saw, but Wei Lun is more deliberate. He goes to Settings first. He wants to see what is configurable. He finds team management — invite users, assign roles. He finds API keys — an option to generate a sandbox API key now and a production key after upgrading. He finds the audit log — already populated with his signup and his settings views. He finds an integrations section listing AutoCount as a supported connector with a "configure" button.

He goes back to the dashboard. He drops three test PDFs from his recent client invoices into the drop zone. All three are processed within two minutes. He clicks into each one and inspects the extraction. The first two are perfect. The third is a Singapore-based client whose invoice is in SGD; ZeroKey detected the foreign currency, fetched the exchange rate from Bank Negara Malaysia for the invoice date, and surfaced both currencies clearly. Wei Lun nods at his screen.

He goes to the AutoCount connector. He follows a short setup flow: enter his AutoCount database connection details, select which sales journal to sync from, set the sync frequency to fifteen minutes. ZeroKey runs a one-time pull and shows him the most recent fifty invoices from AutoCount, ready for processing. He cancels the pull because he wanted to see how it works, not actually do the work yet.

He goes to the API documentation. He skims the authentication, the upload endpoint, the webhook schema, the error codes. The documentation has runnable curl examples. He generates a sandbox API key, runs a curl upload of a test invoice from his terminal, watches it appear in the dashboard within seconds. He sets up a webhook listener using ngrok and confirms the validation event arrives with a clean JSON payload.

He goes to the security page. ISO 27001 alignment in progress, SOC 2 Type II planned, PDPA compliance, KMS-backed certificate storage, Row-Level Security multi-tenancy. He finds a security questionnaire response template available on request — that means they are taking enterprise procurement seriously even if it is not a fit for him today.

He looks at his watch. Forty minutes have passed. He has decided. He goes to the billing settings, enters his corporate card, and upgrades to Growth tier with annual billing for the fifteen percent discount. He invites his two junior staff with Submitter role. He configures the approval workflow so that any invoice above RM 50,000 requires his approval. He sets up his AutoCount sync to start running daily at 9 AM.

He emails his managing director: "ZeroKey looks solid. We are on it. I will run it parallel with our manual MyInvois Portal process for two weeks and then switch fully. No retention surprises so far."

This is the journey for the high-leverage customer. Wei Lun came in skeptical and converted himself in forty minutes because every tool we gave him answered the question he was actually asking.

## Journey 3 — Priya onboards and brings her first three clients

Priya has been hearing about ZeroKey for two months from her younger clients. One of them, the owner of a Tamil-language Saturday school in Brickfields, mentioned it specifically and offered to introduce her to "the people who built it." Priya was hesitant. She has been burned by software changes before. But the school owner sent her a one-paragraph email that said simply, "It is in Tamil also. You will like it."

Priya signs up at home on a Sunday afternoon. The signup form auto-detects her browser language as English but offers Tamil as a one-click switch. She switches. The form, the welcome email, the dashboard, all in clean readable Tamil. She nods. This was done by people who care.

She skips the empty-state drop zone and goes straight to Settings, looking for multi-entity support. She finds it under "Workspace." She is on Starter tier from the trial; she sees that multi-entity needs Pro tier. She does not upgrade yet. She wants to see the product first.

She drops one of her own invoices — for her bookkeeping services to one of her clients — into the drop zone. ZeroKey processes it. The extracted invoice is correct. The MSIC code suggested for "professional accounting services" is right. She submits it. It validates. Her first invoice on her own behalf is done.

She goes back to her client list. She calls one of her closer clients, the medical clinic owner she has been doing books for since 2014. She asks if he would like to try a new tool that might make their monthly compliance work easier. He says yes. He is the second test.

Priya cannot yet add him as a separate entity (Pro tier needed for that), so for now she creates a separate ZeroKey trial account with his details, walks him through email forwarding setup over the phone, and submits two of his invoices on his trial account during the call. Both validate. He is impressed. He says, "If you are using this, I trust it."

Three weeks later, Priya has tested ZeroKey with three clients on three separate trial accounts and is convinced. She upgrades to Pro tier, adds her three clients as separate entities under her workspace, and sends each of them a read-only access invite so they can see their own dashboards. Over the next two months, she migrates twenty-eight more of her clients onto ZeroKey. By August, all thirty-two of her clients are on ZeroKey, and Priya is managing all of them from a single dashboard. Her two assistants have been given Submitter access scoped to specific entities. Her assistants can do half her former workload in a fraction of the time.

She emails the team at ZeroKey with a list of small things she wants improved (a better client switcher, a way to bulk-export QR codes to PDF for her clients' records). She gets a personal reply from a real person within a day acknowledging each suggestion and committing to two of the three. The third is "noted but not soon" with a brief, honest reason.

Priya tells her bookkeeping peers in her CTIM chapter about ZeroKey. Three of them sign up within a month.

This is the journey that unlocks the channel. Priya does not become a customer; she becomes a multiplier. The design of multi-entity, the role granularity, the language localization, the responsive small-team feel — all of it had to work for her to become a multiplier, and all of it earns the leverage.

## Journey 4 — Aisyah's daily rhythm three months in

Aisyah has been using ZeroKey for three months. It is now August 2026. Her workflow has settled.

She wakes at six, opens her phone, checks WhatsApp first. There are seven new messages in the Symprio Trading WhatsApp chat with her staff. Her warehouse manager has sent four photos of supplier delivery invoices that arrived overnight; her sales manager has sent three PDFs from B2B customer orders. Aisyah forwards all seven to the ZeroKey WhatsApp number, one by one. The bot acknowledges each: "Got it. Processing."

She goes downstairs, makes breakfast, helps her daughter with school prep. By the time she returns to her phone at eight-thirty, ZeroKey has finished extraction on all seven. Two are flagged for review (low-confidence MSIC codes); five are auto-validated and ready for her to approve.

She opens the ZeroKey app on her phone. The dashboard shows: "5 invoices ready to submit. 2 need your attention." She taps the five. Each one shows a clean summary. She swipes right on each to approve. They submit. Within four minutes all five have validated and returned QR codes. She forwards two of them to the relevant customers as PDFs (ZeroKey lets her share the PDF and QR code via a quick share menu).

She taps the two that need attention. The first has a low-confidence supplier TIN; she taps the suggested correction (ZeroKey found a near-match in her customer master from a prior invoice) and submits. The second has a low-confidence MSIC code on a new item type; she taps "see suggestions" and picks the second option which is correct. Both submit and validate within minutes.

It is now nine o'clock. Her morning ZeroKey work is done. Total time: under ten minutes. She has not opened her laptop today. She drives her daughter to school.

At work, she opens her laptop briefly at noon to look at the compliance dashboard. It shows that her first-submission validation rate is 96 percent — meaning 96 percent of her invoices passed LHDN validation on the first try without needing rework. It shows her plan usage: 380 of her 500 included invoices used this month, with eight days left in her billing cycle. She notices she is on track to come close to the limit. She opens billing and considers upgrading to Scale; she decides to wait one more month to see if this is a seasonal spike.

In the afternoon she gets a customer call asking for a copy of a specific invoice from June. She opens ZeroKey, searches by customer name and amount, finds the invoice in three seconds, downloads the LHDN-stamped PDF, and emails it. Total time: under one minute. Pre-ZeroKey, this would have meant her bookkeeper digging through SQL Account.

Aisyah no longer thinks about LHDN compliance during the workday. It happens in the background. She tells her bookkeeper at their September check-in that she does not need help with e-invoicing anymore. Her bookkeeper, who is also a ZeroKey customer through Priya, says she is hearing the same thing from other clients.

This is the journey we are designing for. The product disappears into the rhythm of Aisyah's working life. She does not love ZeroKey; she loves not thinking about LHDN. The two are the same thing.

## Journey 5 — Wei Lun handles a busy month-end with his team

It is the last Thursday of September 2026. Month-end at Wei Lun's firm. The two junior staff who have been onboarded over the past two months are clearing the backlog of invoices to issue.

By Tuesday afternoon, ninety-seven new invoices have been drafted in ZeroKey by the junior staff. They appear in Wei Lun's approval queue. Of those, sixty-three have all extracted fields confident and validation passing — these have a green "Ready" tag. Twenty-six have one or two low-confidence fields the junior staff already corrected and approved at their level. Eight have validation issues the junior staff escalated to Wei Lun's queue with notes.

Wei Lun blocks out ninety minutes Wednesday morning to clear the queue. He works through the green "Ready" sixty-three first by opening the bulk-approve action: he reviews the summary table, spot-checks five at random, and approves the rest in one click. They submit in a batch within seven minutes; sixty-one validate, two return rejection codes that he can address afterward.

He works through the twenty-six corrected ones. Each one shows him the original extraction and the junior staff's correction with their note. He approves twenty-three on the spot, sends two back to the junior staff with a question, and overrides one because the junior staff misunderstood a corner case in the buyer's address.

He works through the eight escalations. Three are foreign-currency issues he sorts out by accepting the auto-fetched exchange rate. Two are buyers whose TINs ZeroKey could not verify against LHDN's lookup; he calls the buyers, gets the right TINs, updates the customer master, and resubmits. Three are genuine ambiguities where ZeroKey was right to flag — one involves a self-billed scenario for a Singapore vendor, two involve consolidated B2C invoicing rules. Wei Lun resolves each carefully, partly because he cares and partly because resolving them updates the customer master and item master, which means similar invoices in the future will route automatically.

By eleven o'clock he has cleared the entire month-end queue. He runs a monthly export to CSV and forwards it to the firm's external auditor for the year-end prep. He looks at the compliance dashboard: their first-submission validation rate this month is 94 percent, slightly below target. He drills into the failures and notes that most were related to one specific buyer's repeatedly-changing address; he writes that buyer a courteous email asking them to confirm their current registered address. He logs this in his task list as a process-improvement note.

This is the journey for the customer who scales. Wei Lun's team has grown. Their volume has grown. ZeroKey has scaled with them without requiring more clicks per invoice. The product compounds on his side as much as on ours.

## Journey 6 — A new ingestion edge case surfaces and gets resolved

It is a Tuesday in October 2026. Aisyah forwards her usual batch of supplier invoices from WhatsApp to ZeroKey. Six of seven process normally. The seventh is a photo of a printed invoice from a new supplier in Penang, taken in poor lighting in a warehouse. ZeroKey's pipeline runs OCR on the photo, fails to reach high confidence on the supplier's TIN and three of the line items, and routes the invoice to the vision-language-model fallback path.

The fallback path improves several fields but the supplier's TIN is still low-confidence because part of the TIN is obscured by a coffee stain on the original printed invoice. ZeroKey flags the invoice in Aisyah's inbox: "We could not read the supplier's TIN from this photo. Type it in here, or paste it from your records."

Aisyah does not have the TIN. The supplier is new — they delivered for the first time last week. She replies via WhatsApp to her warehouse manager: "What is the TIN of the new supplier in Penang?" The warehouse manager does not know either. Aisyah calls the supplier directly. The supplier provides the TIN over the phone. Aisyah pastes it into the ZeroKey field. ZeroKey runs the live TIN verification against LHDN; it confirms. The invoice submits and validates.

ZeroKey records the supplier's TIN in Aisyah's customer master. Two weeks later, the same supplier sends another invoice. ZeroKey extracts it from the photo, recognizes the supplier from the customer master, auto-populates the TIN, and the invoice flows through without intervention.

Behind the scenes, ZeroKey's engineering team gets an aggregated, anonymized signal that vision-fallback paths are being triggered slightly more often than the model-quality target. They route a sample of these to their evaluation pipeline, retrain the field-extraction prompts for the language model, and ship a small improvement that raises overall first-pass confidence by two percentage points the next sprint.

This is the journey of the messy edge case. The product handles it gracefully on the human side. The system improves silently on the engineering side. The customer never knows that a continuous improvement loop is running behind their daily work.

## Journey 7 — A customer is unhappy and decides to leave

It is November 2026. A customer named Nuru, who runs a small construction subcontracting business, has been on ZeroKey for two months on Starter tier. He has used it for sixty-three invoices. He is generally satisfied but has been increasingly frustrated with one specific recurring issue: his invoices to a particular government-linked corporation buyer keep getting rejected by LHDN with a confusing error related to the buyer's classification code, and he has spent more time fighting this than he expected. He has emailed ZeroKey support three times. The first reply was within six hours and explained the issue clearly. The second reply was within four hours and walked him through a fix that worked for the next batch. The third reply was within five hours but did not solve the new variation of the issue.

Nuru decides he is going to try a different tool. He logs into ZeroKey, goes to billing, clicks "Cancel subscription." A confirmation page asks him to choose immediate cancellation with prorated refund or end-of-cycle cancellation. He picks immediate cancellation. A short optional feedback field asks why; he writes one sentence: "I keep having issues with one of my GLC buyers and it is not being fixed." He clicks Cancel.

The cancellation processes. The refund (RM 33 prorated for the unused portion of his current month) is queued to his card. A confirmation email arrives within a minute, telling him: his cancellation is effective today, his refund will land within five business days, his data will be retained in read-only access for sixty days for any audit needs, and after sixty days it will be permanently deleted unless he requests export. The email signs off: "Thanks for trying ZeroKey. If you ever come back, your customer master and item master will be waiting for you."

Twenty minutes later, Nuru gets a personal email from the support lead at ZeroKey. The email says: "I saw your cancellation. I read the previous tickets. The third reply did not solve your issue and I am sorry for that. Would you mind a quick call this afternoon? I want to understand the problem properly. Whether or not you come back, I want to fix this for the next customer like you. No sales pitch."

Nuru accepts the call. The support lead, with an engineer on the line, walks through Nuru's case in detail. They discover that the GLC buyer's classification code was changed by the GLC last quarter, and ZeroKey's customer master had cached the old code. The fix is real: ZeroKey ships a feature within two weeks that detects classification code changes from LHDN and prompts customers to refresh their customer master entries proactively.

Nuru does not come back to ZeroKey immediately. Three months later, in February 2027, when penalty enforcement kicks in and his current tool is creaking, he comes back. His customer master is exactly where he left it. He resubscribes to Growth tier. His first invoice in his second life on ZeroKey validates without issue.

This is the hardest journey to design for. The customer who left and we let them go gracefully. The brand reputation we earned by handling cancellation with dignity. The honest follow-up that fixed the underlying issue for everyone. The reactivation that happened because we did not punish him for leaving. Brand trust in our category is built and lost in moments exactly like this.

## Journey 8 — A customer is audited by LHDN and ZeroKey is the safety net

It is March 2027. A customer named Mei Lin runs a small wholesale electronics business in Kepong. She has been on ZeroKey since June 2026. She receives an email from LHDN: a routine audit of her e-invoicing compliance for the period October 2026 through February 2027. She has thirty days to provide the auditor with her complete e-invoice records, audit logs, and supporting documentation for any anomalies.

Mei Lin opens ZeroKey. She has never had to use the audit features before but she knows they exist. She goes to the audit log section and selects "Generate audit package." A short form asks her to specify the date range and the level of detail. She picks October 2026 through February 2027 with full detail.

The audit package generation takes about ninety seconds. ZeroKey produces a single ZIP file containing: a master CSV of every invoice submitted in the period with status, LHDN UUID, validation timestamp, and amount; the original signed XML for every invoice; the original source document (PDF, image, or Excel) for every invoice as ingested by ZeroKey; the complete hash-chained audit log for the period in a tamper-evident signed format; a summary report showing first-submission validation rate, total invoices submitted, total invoices rejected, and any cancellations or amendments; and a verification document explaining how the auditor can independently verify the integrity of the hash chain using publicly-documented cryptographic procedures.

Mei Lin downloads the package. It is 240 megabytes. She emails it to her LHDN auditor with a polite note. Three days later, the auditor replies: the records are clean, the hash chain verifies, the audit is closed with no findings.

Mei Lin sleeps better that night than she has in months. She tells three of her wholesale peers about ZeroKey within the week. She also does something that gives the entire ZeroKey team a great Friday: she writes a short email to support saying simply, "Thank you. The audit was painless because of you."

This is the journey that defines our category position. We are not a product that customers love because it is fun. We are a product that customers trust because when the moment that matters arrives — the audit, the inspection, the regulator at the door — we are the one thing in their stack that is ready.

---

## How these journeys relate to the rest of the documentation

Every screen in `PRODUCT_REQUIREMENTS.md` exists to serve at least one of these journeys. Every principle in `UX_PRINCIPLES.md` is justified by how it shows up in these moments. Every brand voice decision in `BRAND_KIT.md` is calibrated to be the right voice during these journeys. Every architecture decision in `ARCHITECTURE.md` is in service of making these journeys reliable at scale.

When a new feature is being considered, the test is: which of these journeys does it improve, and by how much. If it does not improve any of them, it is probably not a ZeroKey feature. When a journey is added (because we have learned something about a new shape of customer or a new edge case), this document is updated. When a journey changes (because the product has evolved), this document is updated. We do not let the documented journey diverge from the lived journey. Drift is a bug.