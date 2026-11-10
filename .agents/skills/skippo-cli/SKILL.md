---
name: skippo
description: Safely read and manage a user's Skippo boat profile using the skippo CLI.
---

Use `skippo --help` and the relevant subcommand help. For automation use `--json --no-input`. Select a boat by its exact ID; use `--dry-run` to inspect intended writes. A failed or unverified write requires reading the resource before taking further action. Never request or expose a password or session token in command arguments, logs, or output.
