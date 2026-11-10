# skippo-cli

An unofficial CLI for Skippo. This project is independent of Skippo and relies on undocumented APIs that may change.

**Development status:** early release. Trip reads follow the Android app’s Firestore path, but the tested account was denied access by the service. The main boat, engine, event, and note writes were verified on an isolated temporary boat. See the API evidence for coverage and limitations.

## Installation

Python 3.10 or later. Once published, install or upgrade with:

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
skippo boats harbor --latitude 59.0 --longitude 18.0 --dry-run
skippo engines list
skippo checklists list
skippo events list --since 2025-01-01
skippo notes list
skippo trips list --limit 20
```

 Groups: `auth`, `config`, `boats`, `engines`, `checklists`, `events`, `notes`, and `trips`. A sole boat is selected automatically; with multiple boats set a default or use `--boat`. `boats show` and `boats update` accept a positional boat ID. All domain writes accept `--dry-run`; note deletion requires confirmation or `--yes`. No prompt occurs without a terminal or with `--no-input`. Event dates are UTC calendar dates; filters are inclusive.

## Agent contract

Use `--json` for JSON on stdout, errors as JSON on stderr. `--no-input` disables prompts, but does not authorize deletion. An `outcome_unknown` or `written_not_verified` error means inspect the resource with the supplied command before any further action; do not blindly retry a creation. See [API evidence](docs/api-contracts.md) for source and verification limits.

## Exit codes

0 success; 1 unexpected error; 2 input or configuration; 3 authentication; 4 not found; 5 network or service; 130 interrupted.

## Development

```sh
uv sync
uv run python -m unittest discover -s tests -v
```

Tests use synthetic fixtures and a local HTTP server; credentials are never required. To opt into read-only live tests after logging in, run `SKIPPO_LIVE=1 uv run python -m unittest discover -s tests -p test_live.py`. The test-only launcher binds transport to the simulator and is not shipped.

## Security

See [SECURITY.md](SECURITY.md). Do not share session files or tokens. Network requests respect standard proxy and CA settings.
