# Design Specification: Shonchoy Backend Architecture

This document details the software architecture, database schemas, API design patterns, and agent runtime specifications for `shonchoy-backend`.

## 1. Domain Modeling & Hexagonal Architecture

The backend core adheres to Clean/Hexagonal Architecture:

```
┌────────────────────────────────────────────────────────┐
│                   Inbound Adapters                     │
│  FastAPI HTTP Routes (src/fintrack_core/finance/http.py)│
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│                   Application Layer                    │
│   Command & Query Handlers (application/commands.py)   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│                     Domain Layer                       │
│  Entities, Value Objects, Aggregates (finance/domain.py)│
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│                  Outbound Ports/Adapters               │
│  SQLAlchemy Async Repositories (persistence.py)        │
│  PostgreSQL (Neon) Database                            │
└────────────────────────────────────────────────────────┘
```

### Key Domain Aggregates

1. **Account**: Represents bank accounts, MFS wallets (bKash/Nagad), cash, and investments. Maintains balance in integer minor units, category, institution routing code, and optimistic version.
2. **Transaction**: Immutable ledger item recording money movements, counterparty, fees, tags, and reconciliation status.
3. **Budget**: Category-scoped spending envelope with monthly allocation, roll-over preferences, and alert thresholds.
4. **RecurringSeries**: Periodic recurring payments, subscriptions, and anticipated salary inflows with recurrence rules.

## 2. API Design & HTTP Contract Standards

- **RESTful Endpoints**: Versioned under `/api/v1/`.
- **Envelope Standard**:
  ```json
  {
    "data": { ... },
    "meta": {
      "version": 4,
      "serverTime": "2026-10-21T02:00:00Z"
    }
  }
  ```
- **Concurrency & ETags**:
  - GET responses return `ETag: W/"<version>"`.
  - Mutating operations (`PATCH`, `DELETE`) require `If-Match: W/"<version>"`.
  - Mismatched versions reject with HTTP `412 Precondition Failed`.
- **Command Safety**:
  - `POST` commands require `Idempotency-Key: <uuid>`. Duplicate submissions return cached outcomes without re-executing ledger operations.

## 3. LangGraph Advisor Architecture

- The `fintrack_advisor` service uses LangGraph to manage financial advisory conversations.
- **State Machine**:
  - `Ingest`: Extracts user query and context.
  - `Retrieve`: Scopes read-only queries to `fintrack_core` via authenticated internal service token.
  - `Analyze`: Evaluates spending patterns, budget anomalies, and cash-flow projections.
  - `Propose`: Synthesizes recommendations; formats proposals with clear before/after impacts.
- **Safety Boundary**: The advisor node has **no write credentials** to the financial database. All actionable advice returns structured proposal schemas (`ActionProposal`) for client review.
