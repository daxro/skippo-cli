# Independent E2E audit and fixes

A new Terra 6.1 agent independently audited version 0.2.0, commit `9b5a728`.
It built wheel/sdist packages, installed the wheel on Python 3.10 and 3.14,
installed the published Git commit separately, and exercised the real CLI entry
point against a stateful local HTTP service. The 18 existing E2E tests passed
on both versions. The agent then added adversarial regression tests.

## Confirmed client defects fixed in 0.2.1

- Disabling an engine with `--type none` saved the change but incorrectly
  reported `written_not_verified` because verification compared old engine data.
- Engine updates could read plural `engines` profiles but verification only
  understood the legacy singular `engine` field. Selection, listing and
  verification now share the same normalization. Multiple engines remain
  unsupported for writes and cannot be overwritten via a legacy single field.
- A password file with invalid UTF-8 produced an unexpected error instead of
  an input error. It now returns exit 2 without sending a login request.
- A Firestore 403 after a successful token refresh was classified differently
  from an initial 403. Both paths now return `permission_denied`, exit 5;
  authentication rejection still uses exit 3 and refresh is attempted once.
- Directory, lock and atomic-save failures could produce unexpected errors.
  They now report a local configuration error, exit 2, without exposing file
  contents. Malformed local configuration also fails explicitly.
- Malformed HTTP 200 login/refresh responses could overwrite a good session
  with empty or invalid tokens. Token strings and positive expiry are now
  validated before any save. Tests compare the complete original session file
  before and after rejected responses. Legacy sessions without a UID remain
  supported. A malformed provider response is a service error, exit 5, rather
  than evidence that the account credentials were revoked.

## Fuel attachment verification

A simulator replacing an entire fuel event lost attachment metadata during
update. This does **not** establish that Skippo's backend loses attachments:
its official writer omits read-only attachment metadata and uses a separate
asset service. The CLI retains that source-derived write payload rather than
sending guessed relationship fields or signed URLs. Readback additionally
checks that existing attachment IDs remain present before reporting success.
A fault-injection test verifies this check and confirms that a write is not
replayed after an uncertain result.

## Verification boundaries

The independent audit exercised public configuration discovery against Skippo's
real website. No live account session was configured for the audit, and no
live account writes were performed. Live evidence from the earlier temporary
boat checks remains recorded separately in [API contracts](api-contracts.md).
In particular, the account's Firestore permission denial remains unresolved;
this audit does not identify a subscription or email-verification cause.

Regression tests are in `tests/test_audit_e2e.py`. Normal CI uses only synthetic
data. Live account reads are an explicit opt-in and are skipped by default.

## Release verification

The final 0.2.1 wheel was installed into separate clean Python 3.10 and 3.14
virtual environments outside the checkout. Each ran 33 test methods: 32 passed
and the opt-in live account test was skipped. This includes 14 new regression
methods in addition to the 18 original E2E methods. Ruff, compile checks,
wheel/sdist builds, package-content checks and secret-pattern scans also passed.
