# Advisor provider configuration

The advisor is disabled by default. Copy `.env.advisor.example` to `.env.advisor` and set `FINTRACK_ADVISOR_PROVIDER` to `openai` or `anthropic`, `FINTRACK_ADVISOR_MODEL` to a model supported by the selected provider, and the corresponding `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. Set `FINTRACK_ADVISOR_BASE_URL` only when using an HTTPS-compatible endpoint; omit it for the official provider endpoint. Keep all real keys out of Git and mobile `EXPO_PUBLIC_*` configuration.

For the authenticated core relay, set `FINTRACK_ADVISOR_SERVICE_URL` and `FINTRACK_ADVISOR_SERVICE_KEY` in the core backend environment. The service key must match `FINTRACK_ADVISOR_DEV_API_KEY` in the advisor environment. HTTP is accepted only on loopback; remote service URLs require HTTPS. This is an internal service credential, separate from the provider API key.

`POST /v1/core/advisor/explanation` requires the user's existing authenticated session, explicit `consent: true`, and a registered `capability`. The core forwards only that capability and the internal service credential. The advisor converts the capability into fixed app-owned generic instructions; user financial facts, amounts, dates, identifiers and free-form chat are not sent to the provider. The current hosted output is a generic explanation, not personalized analysis. Financial calculations remain in trusted code.

The mobile screen connects to the relay only after session-scoped opt-in and labels hosted text as generic guidance. The core relay applies an in-process limit of 20 requests per user per minute; this does not provide a shared limit across server instances. The advisor's development-key endpoint and these adapters are not a production-readiness certification; distributed rate limiting, deployment security, provider terms, privacy evaluation, native device testing and live-provider verification remain necessary. Tests use synthetic credentials and mocked providers.

Provider interfaces: [OpenAI Responses API](https://developers.openai.com/api/docs/guides/text), [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create).

## Story extraction

`POST /v1/core/advisor/narrative-extraction` accepts `{text, consent: true}` from an authenticated session. Sending a chat message starts hosted analysis without a separate provider consent or identity-review screen, as requested by the user. The configured provider receives the submitted message and financial amounts; identity is not automatically removed from its text. User JWTs, session identifiers and account records are not forwarded to the provider. The response contains suggestions only. Each suggested transaction must still be accepted before saving. Voice input and live-provider compatibility remain unverified.
