# skippo-cli

An unofficial CLI for Skippo. This project is independent of Skippo and relies on undocumented APIs that may change.

**Development status:** early release. Trip reads follow the Android app’s Firestore path, but the tested account was denied access by the service. The main boat, engine, event, and note writes were verified on an isolated temporary boat. See the API evidence for coverage and limitations.

## Installation

Python 3.10 or later. Install or upgrade with:

```sh
uv tool install git+https://github.com/daxro/skippo-cli.git
uv tool upgrade skippo-cli
```

## Secure setup

```sh
skippo auth login --email you@example.com
skippo boats list
skippo config set boat BOAT_ID
```

The password is requested without echo on a terminal. For automation use `--password-stdin` or `--password-file`; never put a password in command arguments. The refresh token grants account access and is stored in the platform configuration directory. On POSIX, the directory and session files are restricted to the current user. `skippo auth logout` removes the session and default boat.

## Commands

Run `skippo --help` and `skippo COMMAND --help` for options.

```sh
skippo boats show
skippo boats update --name "My boat" --dry-run
skippo boats update --brand "Example" --model "Model" --dry-run
skippo boats harbor --latitude 59.0 --longitude 18.0 --dry-run
skippo engines list
skippo engines update --serial-number SERIAL --dry-run
skippo checklists list
skippo events list --since 2025-01-01
skippo events update EVENT_ID --title "Annual service" --cost 1200 --currency SEK
skippo notes list
skippo fuel add --type diesel --date 2025-01-02 --liters 20 --price-per-liter 18 --currency SEK
skippo checklists add-item CHECKLIST_ID --text "Check ropes"
skippo attachments list EVENT_ID
skippo attachments upload EVENT_ID receipt.pdf
skippo attachments download EVENT_ID ATTACHMENT_ID --output receipt.pdf
skippo settings update --safe-depth 2 --average-speed 15 --consumption 1.2
skippo insurance companies
skippo insurance update --company-id COMPANY_ID --policy-number POLICY_NUMBER
skippo insurance update --clear expiration-date
skippo fuel update EVENT_ID --clear liters --clear cost
skippo config unset boat
skippo trips list --limit 20
```

Groups: `auth`, `config`, `boats`, `engines`, `checklists`, `events`, `notes`, `fuel`, `attachments`, `settings`, `insurance`, and `trips`. A sole boat is selected automatically; with multiple boats set a default or use `--boat`. `boats show` and `boats update` accept a positional boat ID. All domain writes accept `--dry-run`; deletion requires confirmation or `--yes`. No prompt occurs without a terminal or with `--no-input`. Event dates are UTC calendar dates; filters are inclusive.

## Agent contract

Use `--json` for JSON on stdout, errors as JSON on stderr. Provider errors include `http_status` and a safe `reason` code when available, for example `EMAIL_NOT_FOUND`. Exit codes remain separate. Unknown server text is not exposed. `--no-input` disables prompts, but does not authorize deletion. An `outcome_unknown` or `written_not_verified` error means inspect the resource with the supplied command before any further action; do not blindly retry a creation. See [API evidence](docs/api-contracts.md) for source and verification limits.

## Exit codes

0 success; 1 unexpected error; 2 input or configuration; 3 authentication; 4 not found; 5 network or service; 130 interrupted.

## Development

```sh
uv sync
uv run python -m unittest discover -s tests -v
```

Tests use synthetic fixtures and a local HTTP server; credentials are never required. To opt into read-only live tests after logging in, run `SKIPPO_LIVE=1 uv run python -m unittest discover -s tests -p test_live.py`. The test-only launcher binds transport to the simulator and is not shipped. See the [independent E2E audit](docs/e2e-audit.md) for regression coverage and verification boundaries.

## Security

See [SECURITY.md](SECURITY.md). Do not share session files or tokens. Network requests respect standard proxy and CA settings. The CLI retrieves public connection configuration from the official My Boat website, so that website must be reachable when a command needs service access.

## Feature details

Fuel records use the app's event schema: the fuel name is the event title, litres are stored as text in its description, and cost is a total with currency (SEK by default). `--price-per-liter` with `--liters` calculates total cost; unit price is not separately stored. Tank level is not exposed by the discovered app contract.

`events update` changes only specified fields and checks that the original ID and attachment IDs remain present. A category change to or from fuel changes how the app interprets the title and description: fuel uses these for fuel type and litres. Updates read the current object and write it back; Skippo has no verified version precondition, so a concurrent change between the read and write may be overwritten. Check the record before retrying a failed verification.

For insurance, `--clear expiration-date` removes the expiry. For fuel, `--clear liters` and `--clear cost` remove those values; each `--clear` may be repeated. Omitting a flag preserves its value, and zero remains a value. Conflicting set and clear flags fail. Clearing navigation settings or engine data is not supported because a reliable clearing contract has not been established.

`boats update` and `engines add/update` accept `--brand NAME --model NAME` as a custom brand and model; `--model NAME` alone keeps an existing brand. Custom entries are not linked to the Skippo catalog. The engine serial number is stored in the boat's safety data: use `engines update --serial-number SERIAL` separately from other engine changes. Individual updates to multiple engines and editing the harbor name are not established.

Binder attachments belong to events. Upload and download support JPEG, PNG, GIF, WebP and PDF files up to 10 MiB; downloads require an explicit new path and never overwrite. The service accepted a PDF and returned its original bytes in a live temporary-boat test. The app's picker is image-only and its PDF preview is unverified. Attachment URLs are suppressed from command output.

Settings use metres for safe depth and height, knots for average speed, and litres per nautical mile for consumption. Read output uses the service fields (`speedInMs` in metres per second); the service stores speed to two decimal places. Checklist add/delete applies to individual user-created items. The app source does not expose create-list, rename-item or reorder endpoints; checklist output shows raw service values, which can differ from the app's inferred completion state. Insurance dates are UTC calendar dates.
