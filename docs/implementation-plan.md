# Skippo CLI v1 implementation plan

## Goal and scope

Build and publish public `daxro/skippo-cli`, description `An unofficial CLI for Skippo.`, with Python package `skippo-cli`, module `skippo_cli`, executable `skippo`. Implement features 1–11: authentication, boat listing/details, default boat, boat updates, engines, checklist reads/completion, boat events/history, event creation, notes, and past trips/details. No navigation, GPS recording, or dedicated export/CSV/file commands (feature 12). Standard `--json` remains part of the CLI contract.

Follow https://clig.dev/ and existing daxro Python CLIs, especially tempus-cli and laget-cli. MIT license; English README and command help with Installation, Secure setup, Commands, Agent contract, Exit codes, Development, Security; uv install/upgrade examples. Include SECURITY.md, AGENTS.md, agent usage skill, pyproject.toml, uv.lock, CI.

## Evidence and discovery gate

Existing proof: Android package com.eniro.nauticalar version 12.6.0; authenticated Firebase email/password sign-in and GET https://nautical-hub.skippo.io/boat-profiles succeeded. Public My Boat JS at https://my-boat.skippo.io/assets/index-CBGww7bc.js provides API client definitions. APK and private data stay outside Git. Public web-client code and Android application strings provide supporting evidence.

First map every requested operation: method/path, request schema, response, auth, ownership, date semantics, pagination. Inspect official Android/WebView code and use authenticated read-only probes as needed. Distinguish code-derived contracts, simulated tests and live observations in docs/api-contracts.md. Never invent an endpoint/schema or silently stub a feature. If a server capability truly cannot be established, report it explicitly as a blocker; do not claim all features completed. Trips are a separate discovery track from boat events and may use Firebase APIs.

## Command contract

- `skippo auth login|status|logout`; `skippo setup` and `skippo status` may be ergonomic aliases.
- `skippo boats list`; `skippo boats show [ID]`; `skippo boats update [ID]` with explicit field flags.
- `skippo config get`; `skippo config set boat ID` validates ownership/existence. Explicit boat ID or --boat overrides local default; sole boat may auto-select; ambiguity fails helpfully.
- `skippo engines list|add|update` scoped to a boat, based on actual service cardinality.
- `skippo checklists list|show|check|uncheck` with exact checklist/item IDs.
- `skippo events list|show|add` with validated `--since`, `--until`, bounded `--limit` where supported.
- `skippo notes list|show|add|update|delete` where verified API supports these operations.
- `skippo trips list|show` read-only; filter dates and limit. Do not include route navigation or recording.
- Refine command parameters after discovery, preserving familiar consistent noun/verb conventions; document final interface.

Human-readable output by default; stable --json data on stdout, status/errors on stderr; --quiet/-q, --no-input, --no-color, NO_COLOR, -h/--help and --version. Global flags accepted consistently on command/subcommand levels. No unexpected prompt without TTY. stdin secrets separate from command data; no --password VALUE. Secrets via hidden terminal prompt, password-file or stdin; no secrets in shell history/logs. Errors actionable without traceback and redact sensitive request/response contents.

Exit codes: 0 success; 1 unexpected/general; 2 input/config; 3 authentication; 4 not found; 5 network/service; 130 interruption. Machine mode errors are stable JSON objects on stderr. Validate dates/ranges, numeric bounds, resource IDs, ownership and ambiguous names before writing.

## Architecture and sessions

Python >=3.10, setuptools, uv; use small modules for cli, API transport, auth, config/session storage, output/errors, and domain operations. Prefer stdlib argparse or a small established CLI library; requests/httpx for HTTP as appropriate. Platformdirs for paths and atomic restrictive 0600 session/config files, parent dirs 0700 on POSIX. Preserve a working session on failed login. Persist refresh token (not password) with automatic Firebase token refresh, locking and atomic replace to handle concurrent commands; logout removes local credentials/session and default boat appropriately. Respect proxies and CA trust.

Central approved HTTPS hosts/paths; production targets fixed and no arbitrary public endpoint override. Redirects never forward credentials cross-host. HTTP timeouts, bounded response sizes, schema checks, bounded pagination, Retry-After and capped retry for idempotent reads only. Refresh and replay a read once on expired auth, not an unbounded loop. Unit-test clock and token lifetimes. Do not persist account data/history caches by default.

## Writes

Discover actual write methods and payloads first. Explicit add/update/check/uncheck commands execute directly. Implement --dry-run for all domain writes: show proposed changes without mutating boat data; authentication refresh and prerequisite reads are allowed. --no-input never implies consent. Destructive delete requires confirmation, or explicit --yes with --no-input. Noninteractive execution without required input fails rather than blocking. Verify saved state via subsequent read before reporting success. Updates preserve unspecified fields; no blind overwrites with omitted/null defaults. No blind retry of creation or ambiguous write responses; report uncertain outcome with reconciliation instructions. Live write validation only reversible changes to dedicated temporary resources, with recorded original values and cleanup in finally; avoid altering user's existing boat fields/checklist or deleting existing content solely for a test.

## Tests: release acceptance

1. Unit tests for config precedence, default selection, validation, formatting, schemas, auth refresh, session file security, HTTP boundaries/redaction, partial updates and filtering/pagination.
2. Deterministic subprocess E2E: install/build real package, invoke `skippo` against a local HTTP simulator using synthetic fixtures. Use a separate test launcher, excluded from distributions, to inject local endpoint bindings before invoking the installed entry point. The actual CLI process must exercise the same HTTP client, serialization, timeouts, error handling and on-disk session storage against real HTTP as production. Do not replace HTTP with an in-memory fake in tests described as E2E. A private test mechanism must not weaken production host restrictions. Simulator records requests and enforces auth and state, rather than unconditional canned success.
3. E2E cover login -> persisted session -> list/show -> choose default -> boat update preserving fields -> engines -> check/uncheck -> events add/list/show -> notes CRUD -> trip list/detail -> refresh/restart -> logout. Verify remote readback, stdout JSON parseability, stderr separation and exit codes. Independent contract assertions ensure tests do not merely mirror implementation.
4. Failure E2E: wrong password, failed login preserving prior session, expired/revoked refresh token, missing config, ambiguous boat, empty lists, 403/404/429/5xx, timeout, malformed/oversized response, pagination repeats, invalid dates, absent TTY, --no-input, Ctrl-C, confirmation denied, dry-run zero writes, uncertain writes no retry, secret redaction, concurrent refresh. Test --help and --version without network/config.
5. Opt-in live integration suite excluded from normal CI. Real backend reads verify session, boats, checklists, events/notes and trips as supported. Credentials provided privately at runtime, never in fixtures/CI outputs. Live writes gated separately and isolated as above. Report skipped/unverified live paths honestly; simulator E2E is not proof of a live write contract.
6. Build wheel/sdist, install wheel into clean environment, run smoke help and E2E there. CI Python 3.10 plus current supported versions, Linux; add Windows/macOS compatibility if practical. Run lint (ruff), tests, compile checks, build, git diff --check, secret scan and inspect packaged file list.

Use synthetic data only in committed fixtures: no real account IDs, email, home harbor coordinates, signed URLs, 1Password links, tokens or APKs. Existing README/RESEARCH.md contain real boat facts and local paths; replace/sanitize before publication. Old skippo.py is a prototype, retire it when package works.

## Execution sequence

A. Commit this reviewed plan locally; discover and document all contracts.
B. Scaffold package, session/transport/output, auth, boat reads/default; E2E foundation.
C. Add verified writes, engines/checklists, events/notes, trips; expand stateful E2E per feature.
D. Full tests and clean package install; live checks and honest coverage report.
E. Rewrite README around final interface, documentation and generated examples. Secret/artifact review including Git history; initialize repository with clean allowlisted files only. Create public GitHub repo daxro/skippo-cli, description above; push reviewed implementation and plan. Run/watch GitHub CI and resolve failures. User has explicitly authorized public repo creation/publication.

## Definition of done

All features 1–11 implemented against verified contracts, deterministic full CLI E2E passing, real login and boat retrieval verified, live-vs-simulated coverage stated, packaged install works, public repository created/pushed and CI passing. Any unresolved API capability is an explicit blocker, not a stubbed success. Final report links repository and notes concrete test evidence and remaining live limitations.

## Review incorporated before implementation

Independent plan review accepted the following refinements:

- Maintain an operation evidence matrix in docs/api-contracts.md: command, method/path, source provenance, synthetic contract test, simulator E2E and current live verification. Code-derived and live-verified are distinct.
- Direct explicit add/update/check/uncheck, dry-run with zero domain writes, delete confirmation or --yes; --no-input never consents. Dry-run may authenticate/refresh and read.
- E2E uses actual HTTP and an installed CLI entry point; test launcher is not distributed. No production endpoint override or HTTP bypass.
- Session locking/generation invalidation must prevent refresh racing logout from resurrecting credentials. Test the race explicitly.
- Mutations are never automatically replayed. A write followed by failed readback returns `outcome_unknown` or `written_not_verified`, with exit code 5 and a concrete read command for reconciliation; do not suggest retrying add.
- Public Git and distribution contents both use explicit reviewed file allowlists. Never `git add .` over the existing research directory. Inspect complete Git history, wheel and sdist; replace private research notes before first commit.
- Date filters use real ISO dates and inclusive boundaries; document timezone and local versus server filtering. State bounded scan limits separately from result limits; detect repeated pagination/cursors.
- E2E covers identical boat names, foreign boat/subresource IDs, stale default boat, refresh-versus-logout, broken pipe and missing/unknown subcommands.
- Required CI baseline is Linux with Python 3.10/3.14. Do not claim Windows/macOS support without checks. POSIX 0600 guarantees are not claimed on Windows.
- Document refresh tokens as account-access secrets. Missing fresh credentials must not block deterministic tests, but live evidence must match the current implementation and list skips honestly.
