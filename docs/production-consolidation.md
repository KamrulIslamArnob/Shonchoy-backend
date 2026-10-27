# Production database and authentication consolidation

Executed on 2026-10-27 for project `FinTrack_DB` (`winter-surf-88756036`), database
`neondb`. The application now uses `production` (`br-billowing-star-b4ih39ph`) for
both managed authentication and financial records.

## Preserved data

- Copied all 25 public tables from `fintrack-backend-dev`, including constraints,
  indexes, identity columns, 2,052 transactions, and 3,307 balance observations.
  Every copied row was compared with the source backup before commit.
- Copied all seven auth users and their seven credential records from
  `shonchoy-mobile-auth-dev`, preserving IDs and password hashes.
- Preserved the four existing financial workspaces and their memberships/data.
  Their ownership is not guessed or assigned to newly signed-in users.
- Kept production's managed auth configuration and signing keys. Users sign in
  again on the production endpoint; old development sessions are not imported.
- Applied Alembic revision `d531c682a4f0`, adding private identity mappings,
  ownership constraints, and forced RLS on 18 financial/user/feedback tables.

## Application configuration

The private `.env` files in both repositories point at production's Auth URL.
Backend auth and finance use the same PostgreSQL database. Runtime connections
use the restricted `shonchoy_runtime` role through the pooled endpoint; migrations
use the owner through the direct endpoint. The runtime role cannot bypass RLS
and can read only the necessary managed-session columns.

The mobile development API URL is `http://192.168.0.154:8000`, matching the current
computer's Ethernet address. The backend runs on `0.0.0.0:8000`; restart Expo after
the environment change. A store release still requires a deployed HTTPS API.

Neon's issuer clock was approximately 16 seconds ahead of this API host. JWT
verification now allows 30 seconds of skew while retaining signature, algorithm,
issuer, audience, and time checks. Regression tests cover accepted small skew,
rejected future tokens, and rejected expired tokens.

## Verification and recovery

Live verification signed in two migrated test users, obtained Neon JWTs, and
called the backend with its real production database. Both received distinct
private workspaces. Swapped session IDs, unsigned requests, and revoked sessions
were rejected. A rolled-back PostgreSQL write verified cross-user read/update
denial and missing-scope denial under the runtime role.

Frontend lint and typecheck passed (lint has existing warnings); 36 targeted
frontend auth/workspace tests passed. All backend checks passed, including unit
tests, dependency integrity/audit, Ruff, mypy, and Bandit.

Private local backups, operational scripts, inventories, and verification output
are under `../../.local/neon-consolidation/` (ignored by Git). These contain private
data and must not be committed. A Neon finance snapshot also exists:
`snap-lucky-breeze-b4x51b43`. Neon refused a child-auth snapshot and an additional
production snapshot; complete local backups were taken for all three branches.

## Completed branch cleanup

After explicit user confirmation on 2026-10-27, deleted `fintrack-backend-dev`
(`br-calm-truth-b4ghgt7x`) and `shonchoy-mobile-auth-dev` (`br-fancy-wind-b44ffkid`).
Neon branch listing verified that only the default `production` branch remains.
Both repositories' `AGENTS.md` files require this single production branch for
auth and finance and prohibit creating additional Neon branches for migrations
or tests. Isolated tests must use local disposable databases.
