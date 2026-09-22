# Antigravity (Gemini) — a design note, not a shipped feature

Vigil does **not** support Antigravity today. Nothing in the app claims it
does. This is the plan and the open questions, written down so the work can
start from something real rather than a guess.

Antigravity does have a hook system, which is what matters: a third provider
would reuse the existing hook binary and the existing queue, exactly as Codex
did. No second widget, no separate UI.

## What their hooks give us

Source: [Antigravity hooks documentation](https://antigravity.google/docs/hooks/).

| | |
|---|---|
| Global config | `~/.gemini/config/hooks.json` (workspace: `.agents/hooks.json`) |
| Events | `PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop` |
| Payload | `conversationId`, `workspacePaths[]`, `transcriptPath`, `modelName`, plus `toolCall` (name + args) on the tool events |
| Approval output | `{"decision": "allow｜deny｜ask｜force_ask｜deny_unless_prior_grant", "reason": "…"}` from `PreToolUse` |
| Timeout | per-hook, default 30s |

## How it would map onto Vigil

| Vigil state | Antigravity event |
|---|---|
| `working` | `PreInvocation` |
| `done` | `Stop` (and `PostInvocation` for a finished turn) |
| `idle` | `Stop` with `fullyIdle` true |
| `blocked` | `PreToolUse`, matched to risky tools only |

`identity_for()` would key sessions on `conversationId`; `describe()` would
take the project name from the first entry of `workspacePaths` and the detail
from `toolCall.args`, scrubbed the same way as everywhere else.

## The two questions that decide the design

**1. Approvals arrive through the wrong door.** Claude and Codex both have a
dedicated permission event, so Vigil only ever sees a request the agent was
*already* going to ask a human about. Antigravity has no such event: gating
happens in `PreToolUse`, which fires for every matched tool call — including
ones Antigravity would have allowed silently. Answering those with `allow`
would make Vigil the gate rather than the messenger, and a Vigil that fails
closed is a Vigil that can stall an agent. The likely shape is: match only
genuinely destructive tool calls, and return `ask` — never `allow` — when
nobody answers in time, so the IDE's own prompt still happens.

**2. `PreToolUse` runs on the hot path.** It fires per tool call, which is the
hook Vigil deliberately avoids on Claude for exactly this reason
([PERFORMANCE.md](PERFORMANCE.md)). A tool-name matcher keeps it off most
calls, but the cost needs measuring on a real install before this ships.

## What is needed to start

Someone with Antigravity installed who will test it. The protocol work is a
day; the trust work — being certain Vigil never blocks an agent that would
otherwise have run — is what takes the time, and it cannot be done blind.
