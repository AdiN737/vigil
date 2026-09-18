# Vigil provider architecture

Vigil is no longer designed around one agent. The desktop widget consumes a
small provider-neutral record from `~/.vigil/sessions`; adapters translate each
agent's lifecycle into that record.

## Canonical session record

Every adapter writes one JSON file per session with these stable fields:

| Field | Meaning |
|---|---|
| `schema` | Contract version. Currently `1`. |
| `provider` | `claude`, `codex`, or a future adapter id. |
| `session_id` | Globally unique Vigil identity. |
| `native_session_id` | The provider's original session/thread id. |
| `state` / `tier` | One of Vigil's seven normalized attention states. |
| `project` / `cwd` | Where the work is happening. |
| `tool` / `detail` | The action a human may need to understand. |
| `since` / `updated` | State start and last-observed timestamps. |

The widget, anti-spam gates, queue ordering, hardware serial output, and future
phone/watch clients depend only on this contract.

## Shipped adapter: Claude Code

`~/.claude/settings.json` receives five hooks. Claude approval replies use
`hookSpecificOutput.decision.behavior` (`allow` or `deny`), per the
[official PermissionRequest contract](https://code.claude.com/docs/en/hooks#permissionrequest-decision-control).
`permissionDecision` belongs to PreToolUse, not PermissionRequest. This source
correction does not update the released ZIP. Isolated source-process tests cover
allow/deny and the 45-second expiry (exit 0, no decision, request cleanup); live
Claude Code acceptance and rebuilt-binary validation remain outstanding. On
expiry the agent retains control; a non-interactive session may deny rather than
show a prompt.

## Source adapter: Codex / ChatGPT coding agent

`~/.codex/hooks.json` receives lifecycle hooks for prompts, approvals, stops,
session ends, and subagent starts/stops. Codex approval replies use
`hookSpecificOutput.decision.behavior`.

Codex hook definitions must be reviewed once with `/hooks`. This is a Codex
trust requirement and Vigil must never bypass it.

The adapter uses documented hook fields rather than parsing transcripts.
Codex-specific `model`, `turn_id`, `permission_mode`, and `agent_id`
fields identify the provider. Subagents receive distinct Vigil rows by adding
`agent_id` to the normalized session identity.

## What “ChatGPT support” means

The framework supports local Codex tasks and ChatGPT's coding-agent surfaces
that emit Codex lifecycle hooks. It does not scrape ordinary chatgpt.com
conversations. General web-chat support requires a browser extension and a
native-messaging bridge; that should remain a separate adapter because DOM
scraping is less stable and cannot safely own OS-level approvals.

## Adding another provider

1. Translate its lifecycle into `working`, `done`, `question`, `blocked`,
   `failed`, or `idle`.
2. Include a stable provider and session identity.
3. Write through the same atomic one-file-per-session contract.
4. Implement the provider's approval response separately.
5. Fail open: if the adapter fails or times out, the provider's normal prompt
   must still appear.
6. Add contract tests before adding installer UI.

Do not copy the widget for each provider. One queue is the product.

Windows Codex session filenames use a digest of the full identity; approval
requests use UUIDs so provider IDs never become invalid Windows paths. See
[Codex setup and verification](CODEX.md) for the local preview status.
