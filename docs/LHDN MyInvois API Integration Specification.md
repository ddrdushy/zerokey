LHDN MyInvois API Integration Specification
e-Invois SaaS Platform
Version: 1.0
Date: April 29, 2026
Author: Integration Architecture Team

Table of Contents

Executive Summary
Integration Architecture Overview
Authentication & Authorization
Core API Endpoints
Document Types & Schema
Integration Workflows
Error Handling & Retry Logic
Rate Limiting & Throttling
Security Requirements
Environment Configuration
Implementation Roadmap
Testing Strategy
Monitoring & Observability
Appendix


1. Executive Summary
This document provides the technical specification for integrating the e-Invois SaaS platform with LHDN's MyInvois System. The integration enables automated submission, validation, and management of electronic invoices in compliance with Malaysian tax regulations.
1.1 Key Integration Points

OAuth 2.0 Client Credentials authentication
REST-based APIs for document submission and lifecycle management
UBL 2.1 compliant JSON/XML document formats
Real-time validation and status tracking
QR code generation and embedding
72-hour cancellation window support

1.2 Integration Scope
FeatureStatusPriorityLogin & Token ManagementRequiredP0Document Submission (Batch)RequiredP0Status Polling & TrackingRequiredP0Document CancellationRequiredP0TIN ValidationRequiredP1Document RetrievalRequiredP1Document SearchRequiredP2Rejection HandlingRequiredP2Notification RetrievalOptionalP3

2. Integration Architecture Overview
2.1 High-Level Architecture
┌─────────────────────────────────────────────────────────────────┐
│                    e-Invois SaaS Platform                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │   Invoice    │───▶│  Document    │───▶│  Submission  │    │
│  │  Extraction  │    │  Formatter   │    │    Queue     │    │
│  │   Service    │    │   (UBL 2.1)  │    │              │    │
│  └──────────────┘    └──────────────┘    └──────┬───────┘    │
│                                                   │            │
│                      ┌────────────────────────────┘            │
│                      ▼                                         │
│          ┌───────────────────────┐                            │
│          │  MyInvois API Client  │                            │
│          │  - Token Manager      │                            │
│          │  - Request Builder    │                            │
│          │  - Response Handler   │                            │
│          │  - Retry Logic        │                            │
│          └───────────┬───────────┘                            │
│                      │                                         │
└──────────────────────┼─────────────────────────────────────────┘
                       │
                       │ HTTPS/TLS 1.2+
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              LHDN MyInvois System (External)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Identity Service           │    e-Invoice API                 │
│  /connect/token            │    /api/v1.0/                     │
│  - OAuth 2.0 Auth          │    - Submit Documents             │
│                            │    - Get Submission               │
│                            │    - Cancel Document              │
│                            │    - Get Document                 │
│                            │    - Search Documents             │
└─────────────────────────────────────────────────────────────────┘
2.2 Component Responsibilities
MyInvois API Client:

Centralized HTTP client for all LHDN API calls
Token lifecycle management (acquisition, caching, renewal)
Request/response serialization (JSON/XML)
Error handling and retry logic
Rate limit compliance

Document Formatter:

Convert internal invoice format to UBL 2.1 schema
Generate SHA256 document hash
Base64 encoding of document payload
Document validation before submission

Submission Queue:

Asynchronous job processing for batch submissions
Priority queue for urgent submissions
Failed submission retry management
Status polling scheduler


3. Authentication & Authorization
3.1 OAuth 2.0 Client Credentials Flow
Endpoint:
POST {identityBaseUrl}/connect/token
Base URLs:

Sandbox: https://preprod-api.myinvois.hasil.gov.my
Production: https://api.myinvois.hasil.gov.my

Request Parameters:
ParameterTypeValueRequiredclient_idStringClient ID from LHDNMandatoryclient_secretStringClient secret from LHDNMandatorygrant_typeStringclient_credentialsMandatoryscopeStringInvoicingAPIOptional
Content-Type: application/x-www-form-urlencoded
Success Response (200 OK):
json{
  "access_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjE2...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "InvoicingAPI"
}
3.2 Token Management Strategy
Implementation Requirements:

Token Caching:

Cache token for expires_in duration (default: 3600 seconds)
Store in Redis/memory with TTL = expires_in - 300 (5-minute buffer)
Use company-specific cache keys: myinvois:token:{companyId}


Token Renewal:

Proactively renew 5 minutes before expiration
Handle concurrent requests with mutex/lock
Implement exponential backoff for failed renewals


Error Handling:

On 401 Unauthorized → immediately attempt token renewal
On renewal failure → retry with exponential backoff (max 3 attempts)



Rate Limit: 12 requests per minute per client ID

4. Core API Endpoints
4.1 Submit Documents
Purpose: Submit one or more invoices to MyInvois for validation.
Endpoint:
POST {apiBaseUrl}/api/v1.0/documentsubmissions/
Rate Limit: 100 requests/minute per client ID
Headers:

Authorization: Bearer {access_token}
Content-Type: application/json
Accept: application/json

Request Body:
json{
  "documents": [
    {
      "format": "JSON",
      "document": "base64EncodedDocumentString",
      "documentHash": "sha256HashOfOriginalDocument",
      "codeNumber": "INV-2026-001"
    }
  ]
}
Batch Constraints:

Maximum 100 documents per submission
Maximum 5MB total submission size
Maximum 300KB per document

Success Response (202 Accepted):
json{
  "submissionUID": "HJSD135P2S7D8IU",
  "acceptedDocuments": [
    {
      "uuid": "F9D425P6DS7D8IU",
      "invoiceCodeNumber": "INV-2026-001"
    }
  ],
  "rejectedDocuments": []
}

4.2 Get Submission (Polling)
Endpoint:
GET {apiBaseUrl}/api/v1.0/documentsubmissions/{submissionUID}
Rate Limit: 300 requests/minute
Polling Strategy:

Initial wait: 2 seconds
Exponential backoff: 2s, 4s, 8s, 16s, 30s (max)
Stop when overallStatus ≠ "InProgress"


4.3 Cancel Document
Endpoint:
PUT {apiBaseUrl}/api/v1.0/documents/state/{uuid}/state
Rate Limit: 12 requests/minute
Request Body:
json{
  "status": "cancelled",
  "reason": "Customer cancelled the order"
}
Cancellation Window: 72 hours from dateTimeValidated

4.4 Get Document (with QR Code)
Endpoint:
GET {apiBaseUrl}/api/v1.0/documents/{uuid}/raw
Rate Limit: 60 requests/minute
QR Code Generation:
The longId field from response is used to generate QR code:
Validation URL Format:
{portalBaseUrl}/{uuid}/share/{longId}
Example:
https://myinvois.hasil.gov.my/F9D425P6DS7D8IU/share/LIJAF97HJJKH8298...

4.5 Validate Taxpayer TIN
Endpoint:
GET {apiBaseUrl}/api/v1.0/taxpayer/validate/{tin}
Rate Limit: 60 requests/minute
Best Practice:

Call BEFORE invoice submission
Cache validated TINs for 24 hours


5. Document Types & Schema
5.1 Supported Document Types
Document TypeVersionPurposeInvoice1.0, 1.1Standard commercial invoiceCredit Note1.0, 1.1Reduce value of issued invoiceDebit Note1.0, 1.1Additional chargesRefund Note1.0, 1.1Confirm refund to buyerSelf-Billed Invoice1.0, 1.1Buyer-issued invoice
Version Differences:

v1.0: Digital signature validation disabled
v1.1: Digital signature validation enabled (recommended)


5.2 UBL 2.1 Mandatory Fields
Internal FieldUBL 2.1 PathValidationInvoice NumberInvoice.IDMax 50 charsInvoice DateInvoice.IssueDateYYYY-MM-DDSupplier TINAccountingSupplierParty.Party.PartyTaxScheme.CompanyID12 digitsSupplier NameAccountingSupplierParty.Party.PartyLegalEntity.RegistrationNameMax 300 charsTotal AmountLegalMonetaryTotal.PayableAmount2 decimal places

6. Integration Workflows
6.1 Complete Submission Flow
1. User uploads invoice
   ↓
2. OCR + LLM extraction
   ↓
3. Manual correction (if needed)
   ↓
4. Validate TIN (recommended)
   ↓
5. Convert to UBL 2.1 JSON
   ↓
6. Generate SHA256 hash
   ↓
7. Base64 encode document
   ↓
8. Acquire access token
   ↓
9. Submit document (batch up to 100)
   ↓
10. Poll for validation status
   ↓
11. Retrieve validated document
   ↓
12. Generate QR code
   ↓
13. Embed QR in PDF
   ↓
14. Store & notify user

7. Error Handling
7.1 HTTP Status Codes
StatusMeaningAction200OKSuccess202AcceptedAsync operation accepted400Bad RequestFix request and retry401UnauthorizedRenew token and retry422UnprocessableValidation error429Too Many RequestsWait and retry with backoff500Server ErrorRetry with exponential backoff
7.2 Common Error Scenarios
DuplicateSubmission (422):

Identical submission within 10 minutes
Wait time specified in Retry-After header

MaximumSizeExceeded (400):

Split into smaller batches
Reduce documents per submission

OperationPeriodOver (400):

Cancellation window expired
Guide user to use Credit Note instead


8. Rate Limiting
8.1 Rate Limits per Endpoint
API EndpointLimit (RPM)Login12Submit Documents100Get Submission300Cancel Document12Get Document60Validate TIN60

9. Security Requirements
9.1 Encryption

TLS 1.2+ required for all API calls
Certificate validation enforced

9.2 Credential Storage

Store in environment variables or secure vault
Never hardcode credentials
Rotate every 90 days

9.3 Token Storage

Cache in Redis with TTL
Never persist to database


10. Environment Configuration
10.1 Sandbox
Identity: https://preprod-api.myinvois.hasil.gov.my
API: https://preprod-api.myinvois.hasil.gov.my
Portal: https://preprod.myinvois.hasil.gov.my
Characteristics:

Lower rate limits
Data retained for 3 months max
For testing only

10.2 Production
Identity: https://api.myinvois.hasil.gov.my
API: https://api.myinvois.hasil.gov.my
Portal: https://myinvois.hasil.gov.my

11. Implementation Roadmap
Phase 1: Core Integration (Weeks 1-2)

OAuth 2.0 token manager
API client with retry logic
Submit Documents API
Get Submission API with polling
UBL 2.1 formatter

Phase 2: Document Lifecycle (Weeks 3-4)

Get Document API
Cancel Document API
Validate TIN API
Error handling
Integration tests

Phase 3: Advanced Features (Weeks 5-6)

QR code generation
PDF template integration
Batch optimization
Production deployment


12. Code Lists (Appendix)
Invoice Type Codes

01: Invoice
02: Credit Note
03: Debit Note
04: Refund Note

Payment Means Codes

01: Cash
02: Cheque
03: Bank Transfer
04: Credit Card
05: Debit Card
06: E-Wallet

Malaysia State Codes

01: Johor
10: Selangor
14: W.P. Kuala Lumpur
(full list in detailed spec)


13. Reference Links

MyInvois SDK: https://sdk.myinvois.hasil.gov.my/
UBL 2.1 Spec: http://docs.oasis-open.org/ubl/UBL-2.1.html
Integration Practices: https://sdk.myinvois.hasil.gov.my/integration-practices/