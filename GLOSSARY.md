# Shonchoy Domain Glossary

This document defines the ubiquitous domain vocabulary used across the `shonchoy-backend` codebase and architectural seams.

---

### Core Financial Concepts

- **Account**: A financial container representing bank accounts, MFS wallets (bKash/Nagad), cash, DPS (Deposit Pension Scheme), or debts. Maintains balances in integer minor units (e.g. paisa/cents) and optimistic concurrency versions.
- **Transaction**: An immutable financial record capturing money movements with direction (`in` / `out`), kind (`income`, `expense`, `transfer`), merchant/description, booking date, and optional category splits.
- **Split**: An itemized allocation of an expense transaction across multiple categories, strictly conserving the transaction's total amount.
- **Observation (Balance Observation)**: A point-in-time recorded balance reconciliation event for an account, with monotonic effective date ordering.
- **Budget**: A currency-scoped spending plan containing monthly category envelopes, versioned allocations over time, and rollover rules.
- **Recurring Series**: Scheduled, periodic cash inflows or outflows projected into the future according to calendar recurrence frequencies.

---

### Deepened Seams & Modules

- **Ledger**: The authoritative financial accounting and reporting module. It computes cashflow summaries, category spending totals, liquid net worth, and asset/liability aggregations directly across transaction and account records, encapsulating accounting invariants behind an analytical query interface.
