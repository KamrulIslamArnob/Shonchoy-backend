# Advisor implementation plan: no financial data to models

This plan supersedes the earlier proposal to send minimized financial facts to a hosted model. The model must receive no user-supplied financial data, identity, free-form chat, account labels, record IDs, dates or amounts. Deterministic code inside the app or trusted backend performs calculations, resolves records and renders financial answers. Only fixed, app-owned generic capability labels may be sent to a model. Unknown requests must fail closed or stay local; removing names with regex is not enough.

## Module loop

Implement each module, test its public boundary with synthetic data, fix failures and run applicable quality gates before starting the next module.

1. **Privacy boundary:** replace the previous financial-facts model contract with fixed, typed, app-owned generic prompts. Capture outgoing requests in tests and prove identity, financial values, dates, labels and chat never appear. Preserve local deterministic analysis. Failure or unknown input must never fall back to sending raw text.
2. **Provider adapters:** support OpenAI Responses-compatible and Anthropic Messages-compatible endpoints, selected through server-only environment configuration. Read keys through secret settings, never expose them in the mobile app, and test both adapters with fake HTTP responses. No live calls or credentials are needed for tests.
3. **Advisor orchestration:** connect the provider only to the privacy boundary. Validate output against registered capabilities; no arbitrary tools, URLs, SQL, financial data or model-directed mutations. Timeouts, malformed output and missing configuration fail safely to local behavior.
4. **Trusted financial tools:** implement scoped read-only calculations for spending, income, net worth, budgets and recurring items, with integer minor units, correct currency and freshness. Resolve all user-specific results locally, outside the model context.
5. **Reviewable actions:** add typed proposals for budget and transaction changes; resolve targets within the authenticated workspace and show exact previews. Only the user-facing app may submit approved commands, using idempotency and version checks. Preserve the connected-person loan restriction.
6. **App integration and expansion:** connect mobile transport and consent/settings only after the preceding privacy and authorization tests pass. Add remaining app capabilities individually, each with a scoped contract, explicit approval for writes, and regression tests.
7. **Release readiness:** test tenant isolation, injection, privacy canaries, retries, key handling, offline behavior and kill switches. Run the repository quality gates and document provider configuration and remaining device/deployment verification.

The mobile app currently uses an offline synthetic repository; production authentication and connected data must not be assumed. No test may create a Neon branch or use production data. API keys belong only in backend environment configuration, not source control or `EXPO_PUBLIC_*` variables.

## Current implementation status

- Fixed generic prompts, provider adapters for the two API formats, and an authenticated consent-gated core relay have focused synthetic tests. The provider is disabled by default; no live provider has been tested.
- The advisor screen offers session-scoped opt-in for the mobile privacy transport. The local/hosted composition sends only a capability and consent to the trusted core; native device and configured-provider verification remain open.
- On supported native devices authenticated chat history is encrypted with a key in device secure storage. Web and unavailable secure storage use memory only. Device verification remains open.
- Local budget and transaction review drafts and stale-state checks exist. They prepare commands but do not execute them; the approval UI, authorization binding and end-to-end execution remain to be implemented.
- A first in-memory guided Transaction module collects cash-in or cash-out fields and prepares a local review. It is not wired to chat, persisted, approved or executable; tests cover both directions, invalid choices and cancellation.
- Multi-domain action coverage, production observability/rate limits, provider review, device verification and release readiness remain open.
