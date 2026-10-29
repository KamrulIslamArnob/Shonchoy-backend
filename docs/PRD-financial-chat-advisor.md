# PRD: Shonchoy Financial Chat Advisor

**Status:** Draft for product and engineering review  
**Date:** 2026-10-28  
**Companion:** [Delivery and architecture plan](agentic-financial-advisor-plan.md)

> **Latest interaction decision (2026-10-29):** Sending a message now initiates hosted narrative analysis directly, without a separate sharing or manual identity-review prompt. Suggested transactions still need acceptance before saving. This supersedes the per-story consent-screen requirements below.

> **Earlier privacy update (2026-10-29):** The user has chosen to allow a financial story and amounts to be sent to hosted Xiaomi MiMo after a per-story editable review, manual removal of identifying details, and explicit consent. Automatic redaction does not guarantee anonymity. The story extraction endpoint implements this exception; the generic-guidance endpoint continues to accept only fixed topics. Earlier sections describing a blanket ban on financial input are superseded for this consented story workflow.

## 1. Summary

Give Shonchoy users a chat advisor that can explain their finances and help them complete tasks across the app. Use an approved hosted model only for generic guidance; send it no user financial data or identity. Financial changes are proposals that the user reviews and approves in the app.

## 2. Background

The mobile app has an advisor screen and local answers; its default repository is an offline prototype. The backend has provider adapters and an authenticated relay, connected to the screen behind session-scoped opt-in for generic explanations. The older text filter catches only some identifiers and is not a model privacy boundary. See the [implementation plan](advisor-implementation-plan.md).

## 3. Objective and success measures

Help users understand their money and complete supported app tasks with confidence, while keeping user financial data and identity out of model input.

The following are **proposed pilot targets**, not existing baselines:

| Measure | Pilot target and measurement |
| --- | --- |
| Useful financial answers | At least 90% of a reviewed, synthetic test set of 100 supported questions give the correct figures and context. Incorrect or unsupported questions must be acknowledged rather than answered confidently. |
| Task completion | At least 80% of supported, unambiguous test tasks reach the correct answer or an accurate proposal, measured end to end. |
| Privacy and control | Zero seeded identity markers or credentials in captured model requests across the required privacy test suite; zero unapproved financial writes in the action and adversarial test suite. These tests do not prove anonymity. |

Track answer helpfulness, accepted and rejected proposals, errors, latency and cost using content-free, aggregated metrics. Set production targets after a pilot baseline is available.

## 4. Market segments

1. **People managing daily money:** want to understand spending, balances and upcoming obligations without searching across screens.
2. **People maintaining a financial plan:** want help drafting budgets and recording or correcting transactions without losing control of their data or decisions.

## 5. Value propositions

| | Daily money | Financial planning and recordkeeping |
| --- | --- | --- |
| **Who** | A person using Shonchoy to track their finances. | A person keeping budgets and a ledger up to date. |
| **Why** | They need a clear answer about their money. | They need to make changes without navigating several forms. |
| **What before** | They inspect accounts, reports and transactions themselves. | They enter or edit each item manually. |
| **How** | Chat explains calculated results and links to the relevant screen. | Chat prepares an itemized proposal for review and confirmation. |
| **What after** | They find the answer and its supporting period more quickly. | They can complete routine tasks while retaining the final decision. |
| **Alternatives** | Existing reports, spreadsheets or a general chatbot. | Existing app forms, spreadsheets or a general chatbot. |

Shonchoy combines locally calculated answers grounded in the user's own records with reviewable actions. The model receives only fixed generic capability descriptions.

## 6. Experience and requirements

1. **Ask and understand:** Users can ask about spending, income, cash flow, budgets, net worth and upcoming recurring items. Answers show the period, currency, source freshness and links to supporting app data. When data is missing, stale or ambiguous, the advisor says so.
2. **Prepare an action:** For a supported change, chat shows a structured preview with the relevant account or category, amount, currency, before/after values and consequences. The user can edit, confirm or cancel it. No mutation occurs before confirmation.
3. **Use the whole app over time:** A capability registry will add navigation, reads and proposed changes for each domain in stages; the first release covers spending and budget analysis plus a small set of budget/transaction proposals. See the [capability map](agentic-financial-advisor-plan.md#4-app-wide-capability-map).
4. **Keep user data away from the model:** A trusted gateway sends only fixed generic capability descriptions. Financial amounts, dates, account and category labels, identifiers, names, raw chat, attachments and credentials are not model inputs. Unclassifiable requests stay local and ask the user for clarification. All record resolution stays inside the trusted app boundary.
5. **User control:** Explain what financial categories of data are sent, obtain opt-in before hosted processing, offer stop/retry and a local fallback, and let users delete their chat history. A privacy-gateway failure stops hosted processing.
6. **Accurate finance:** Compute figures and money movements in deterministic code using integer minor units. Never mix currencies, invent transactions, claim a payment occurred, or present an estimate as a guaranteed outcome. Show assumptions for forecasts.
7. **Existing restrictions:** The advisor is read-only and cannot call database mutation functions or mutation endpoints. Its proposals are executed only by the normal authenticated app command after user approval. The existing restriction on loans for connected Shonchoy accounts remains in place until the shared-agreement feature supports them.

The hosted model must be reviewed for contractual data use, retention, security and deployment location before release. User financial data must never be sent to it. [NIST: de-identification](https://csrc.nist.gov/pubs/ir/8053/final) explains why simply removing names does not eliminate re-identification risk.

## 7. Assumptions and open decisions

- **Confirmed:** Support OpenAI-compatible and Anthropic-compatible providers; do not send user financial data or identity to the model.
- **Assumption:** The first pilot targets existing Shonchoy users who opt in, beginning with BDT and the current app workflows; additional currencies must still remain correctly separated.
- **Decision needed before release:** Approve the provider, data-processing terms and retention, processing region, budget and access model.
- **Decision needed before implementation:** Choose the supported first-release question and action list, pilot cohort, success baseline and release owner.
- **Trade-off:** Open-ended chat cannot be guaranteed to contain no identifying or financial information by regex alone. The hosted release sends only fixed, generic capability labels; requests that cannot be safely represented must ask for clarification or remain local.

## 8. Release

| Stage | Outcome | Exit requirement |
| --- | --- | --- |
| **0. Foundation** | Privacy gateway, hosted-provider review, authenticated tenant boundary and synthetic evaluation harness. | Privacy and security gates pass; no user financial data reaches a model. |
| **1. Read-only pilot** | Spending, budget, cash-flow and net-worth answers with sources and local fallback. | Numerical correctness, privacy and isolation targets pass. |
| **2. First actions** | Reviewed budget and transaction proposals through existing app command flows. | Confirmation, idempotency, stale-data and rejection tests pass. |
| **3. Expand app coverage** | Add account, recurring, rules, reports and other supported domains one capability at a time. | Each capability has its own permissions, tests and rollout switch. |

External money transfers, sharing or messaging other people, autonomous account security changes, and mutual loan agreements are outside the first release. They require their own product, security and integration design before they can be offered.

## 9. Guided chat product specification

### Product promise and privacy trade-off

The user can start a task from the advisor, answer follow-up questions using selection blocks and locally entered values, review the complete result, and approve or cancel. Financial questions, amounts, identities, dates, labels, transaction descriptions, account and person identifiers, attachments, chat history, tool results and proposals never reach a hosted model. A selected generic topic is sent only with opt-in and can reveal a topic of interest. No hosted LLM sees the user's request or supplies private action parameters. Therefore unrestricted personalized natural-language understanding is not supported by the hosted model; a local deterministic interpreter can recognize explicitly supported patterns and otherwise offers choices or clarification. A future on-device model needs separate design and privacy review.

### Conversation lifecycle

1. **Choose:** User selects a supported task or uses an unambiguously recognized local phrase. Unknown, conflicting or ambiguous input leads to a question; no silent guesses.
2. **Collect:** App-owned prompts collect one missing field at a time. Choice blocks contain only eligible local records, with search and disambiguation where needed. The user can edit an earlier answer, go back or cancel.
3. **Validate:** Domain logic checks user scope, required fields, currency, minor-unit amounts, dates, eligible records and current versions. It fails closed and explains how to correct invalid or stale data.
4. **Review:** A locally rendered preview displays the action, target, exact amount and currency, date, consequences, and any relevant account and debt effects. Financial data stays in the trusted app. Nothing has been saved at this point.
5. **Confirm:** A deliberate user action approves exactly the displayed proposal. Revalidate against fresh state and reject changed, expired, replayed, cross-account or tampered approvals. The app uses the existing authenticated command pipeline; the advisor never calls a mutating function.
6. **Finish or recover:** Show success only after confirmation by the repository. Distinguish cancellation, validation conflict, partial failure and uncertain outcomes. Retry an uncertain command only with its original idempotency key and exact payload. Never report that a payment or notification occurred unless actually supported.

Keep transient proposal state isolated by authenticated user and workspace; prevent stale async callbacks from crossing sign-in/out. Persist drafts only when an account-scoped encrypted persistence design exists and explicit retention behavior is clear. No private values, prompts, payloads or provider credentials in analytics, logs or crash reporting.

### First journeys and acceptance criteria

| Journey | Questions and choices | Required review and safeguards |
| --- | --- | --- |
| Cash out | Expense type, amount, eligible account, category when applicable, date, optional description. | Explicit expense/out direction, amount, currency, account, category, date and description; positive integer minor units. Use existing Transaction creation; do not imply a bank transfer or that ordinary entry updates balance observations. |
| Cash in | Income type, amount, eligible account, category when applicable, date, optional description. | Explicit income/in direction and the same validation and review rules as cash out. |
| Personal loan | Lent or borrowed, eligible existing person or separately reviewed person creation, amount, due date, and the supported cash-recording choice. | Show debt direction, cash effect, currency, amount, person and due date. Reject linked Shonchoy profiles until shared agreements exist. Never imply a notification or actual payment. Handle the current separate person and debt writes as potentially partial; do not claim atomicity. |
| Account | Account type, name, currency, existing account-specific required fields and opening balance if supported. | Preview account details and consequences; reuse current setup validation; sensitive receiving details remain local. No invented balances or financial institution linking. |

A proposal must never be executed from a model-generated answer or when a user merely sends a chat message. Duplicate taps, late callbacks, stale versions, rejected permission and app restart must not create unintended or repeated records. Transfers, split transactions, connected-person loans, recurring changes, imports, security, account deletion, external payments, messaging and bulk changes remain unavailable through guided chat until each has a dedicated reviewed capability and tests.

### App capability map and rollout

| Area | Existing app | Guided advisor release |
| --- | --- | --- |
| Home, reports | Local dashboard and reports | Local read-only explanation and navigation after correctness and freshness verification. |
| Transactions | Expenses, income, transfers, reviews and splits | Phase 1: guided expense/income. Transfers and edits follow separately. |
| Accounts | Setup, metadata, archive, balance observation | Phase 2: guided account setup. Reconciliation/archive require individual review. |
| People and personal loans | Local personal-debt tracking, linked-person restrictions | Phase 2: private loan proposal using supported local flow; connected backend parity is not assumed. |
| Budget and recurring | Budget plans, rollover and recurring series | Phase 3: versioned budget and recurring proposals, one capability at a time. |
| Categories, rules, ingestion and receipt scanning | Existing UI and local/connected functionality varies | Phase 4: inventory and validate each command; raw OCR and SMS never leave the trusted app for a model. |
| Settings, authentication, exports, data deletion and external sharing | Existing settings and security workflows | Navigation only until separately designed, authorized and tested. |

The app currently defaults to a synthetic offline repository. A connected deployment requires independent authentication, tenant isolation and per-command parity verification. SMS/receipt capture has special local balance and deduplication behavior; do not treat it as ordinary transaction entry or assume backend parity.

### Test and release gates

- **Privacy:** Intercept all model-bound payloads and headers; seed multilingual names, identifiers, account labels, values, dates, chat, attachments and adversarial instructions. Unknown input, errors, retries and cancellation never forward them. Inspect logs and telemetry. Test that optional generic topics are accurately disclosed.
- **Conversation:** Required fields, ambiguous selection, empty/no eligible options, edits, cancellation, back navigation, unsupported intents, accessibility, screen-reader labels and interrupted sessions.
- **Financial:** Exact money parsing and rounding, currency isolation, eligible/archived accounts and categories, loan direction and caps, linked-person restriction, no duplicate booking and balanced transfer invariants.
- **Approval and isolation:** Exact preview binding, tampered/stale/expired approvals, duplicate taps, cross-user switches, idempotent uncertain retry and explicit partial failures; no mutation without confirmation.
- **Release:** Device testing for native encrypted history; full repository checks; provider terms and retention review; measured latency and synthetic evaluations. No production data in tests or isolated database operations.

### Research informing the design

- [Google Dialogflow parameters](https://docs.cloud.google.com/dialogflow/cx/docs/concept/parameter): collect missing values through structured prompts; here the actual collection remains local.
- [Google conversation confirmations](https://developers.google.com/assistant/conversation-design/confirmations): distinguish confirming an answer from confirming the action.
- [OWASP AI agent security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html): verify permissions and enforce human approval in trusted code.
- [Microsoft human-in-the-loop workflows](https://learn.microsoft.com/agent-framework/workflows/human-in-the-loop): pause a workflow to gather input or approval; use the pattern locally without forwarding private values to a hosted model.
