# Security and privacy, stated plainly

Vigil sits between you and an agent that can run commands on your machine, so
the honest version of what it does and does not protect matters more than a
reassuring sentence. If you find something wrong here, open an issue.

## What is written down, and where

Everything Vigil records lives under `~/.vigil` and stays on the machine.

| File | Holds | Notes |
|---|---|---|
| `sessions/*.json` | project folder name, tool name, a ≤120-character detail, state, timestamps | deleted when the session ends |
| `requests/`, `decisions/` | a pending approval and its answer | deleted as soon as it is answered |
| `log.txt` | one line per event that needed you | tier 3 and above only |
| `metrics.jsonl` | durations, tiers, truncated session ids | capped at 512 KB, trimmed oldest-first |
| `remote.json` | the two live settings (`approvals_enabled`, `message`) | replaced at each update check |

**Vigil never records your prompts or the agent's replies.** The detail on a
pill comes from the tool's own input — a command, a path, the agent's own
description — never from a `prompt` field. Before anything is written, long
opaque words (API keys, bearer tokens) are replaced with `[redacted]`; commit
shas and file paths are left readable. See `scrub()` in `app/vigil_hook.py`.

Vigil never reads the contents of your files, your repository, or your
agent's transcript.

## What leaves the machine

Two things, both from the widget and never from the hook:

1. **The update check**, about once a day: a GET to `vigilit.app/api/update`
   carrying only Vigil's own version number. The reply is the latest release
   and the live settings.
2. **The update download**, only after you click: a signed ZIP from storage.

That is the complete list. No analytics, no crash reporting, no session data,
no account identifier. The hook never opens a socket at all.

If you want zero network traffic, block `vigilit.app` — Vigil keeps working
and simply stops finding updates.

## How an update is trusted

A release is signed with an Ed25519 key that exists only on the publisher's
machine. Each install carries the public half. Before anything is unpacked:

- the download must match the published SHA-256, **and**
- that digest must carry a valid signature from the release key, **and**
- only allow-listed paths are extracted, with path-traversal rejected, **and**
- the staged copy is marked complete only after all of that succeeds.

So compromising the website, the database or the storage bucket is not enough
to push code to a user; an attacker would need the private key as well. That
key is passphrase-encrypted at rest (`tools/release_keygen.py --encrypt`) and
never leaves the publisher's machine.

## The trust boundary, and where it stops

Approvals are files under `~/.vigil`, readable and writable by your own user
account. Request ids are random UUIDs, so nothing can guess a pending id — but
**any program already running as you can list pending approvals and answer
them.** It could approve a destructive command you never saw.

That is a real limit and worth stating: Vigil is not a security boundary
against code already running as you. Such code could equally edit your agent's
settings, remove Vigil's hooks, or run the command itself without asking. The
approval channel is a convenience for a trusted desktop, not a sandbox.

If you want the stronger property — approvals that a compromised desktop
cannot forge — it needs a second device holding a key, which is exactly what
the hardware/phone approver in `docs/HARDWARE.md` is for.

## Failure behaviour

Vigil fails open, on purpose. If the hook crashes, hangs, is deleted, or the
kill switch turns approvals off, the agent prompts in its terminal exactly as
it would with Vigil uninstalled. The worst case is today's behaviour, never a
silently approved command.

## Reporting something

Email the address on [vigilit.app/privacy](https://vigilit.app/privacy), or
open a GitHub issue if it is not sensitive.
