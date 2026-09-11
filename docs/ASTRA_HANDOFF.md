# GPT-6 Astra handoff prompt

Paste the prompt below into a new GPT-6 Astra coding task opened on the
`AdiN737/vigil` repository. Give the task access to both repositories.

---

You are taking over development of Vigil, a local-first Windows attention
companion for AI coding agents.

Repositories:
- https://github.com/AdiN737/vigil
- https://github.com/AdiN737/vigil-web
- Production site: https://vigilit.app

Mission:
Make Vigil the best Windows-first, cross-agent product for knowing exactly when
an AI coding session requires human action, and for answering supported approval
requests without returning to the agent window. Agent Island is the closest
competitor. Research its current product before making comparative claims;
do not rely on old assumptions about its supported platforms or agents.

Start by reading every tracked source and documentation file in both
repositories, plus all repository instructions. Inspect git status and preserve
unrelated user changes. Read the current official Codex hooks and App Server
documentation before changing the OpenAI integration.

Current architecture:
- A fast, Qt-free hook normalizes provider events into one JSON file per session
  under ~/.vigil/sessions.
- A PySide6 widget polls those records, ranks them by urgency, and applies five
  anti-spam gates.
- Permission requests use ~/.vigil/requests and ~/.vigil/decisions.
- Claude Code and Codex use different approval response shapes.
- Source now includes a provider-neutral schema, provider badges, Codex hook
  installation, and regression tests in tests/test_providers.py.
- Claude session IDs must remain backward-compatible.
- Codex subagents should become distinct rows when agent_id is available.
- Any adapter failure must fail open so the agent's normal approval UI remains.

Required build:
1. Review and harden the new Codex/ChatGPT adapter. Confirm every payload and
   response shape against current official OpenAI docs.
2. Test real Codex hooks on Windows through ~/.codex/hooks.json. Use /hooks to
   review and trust them; never bypass hook trust.
3. Verify working, question/approval, allow, deny, destructive, stop, session
   end, concurrent thread, and subagent flows. Measure hook latency and keep
   non-approval events under 300 ms.
4. Fix any duplicate-session, stale-state, race, timeout, focus, or anti-spam
   behavior found during real use.
5. Rebuild the separate Windows hook and widget binaries. Never link Qt into the
   hook. Package a clean release zip and verify it after extracting to a new
   directory.
6. Update README and provider docs with exact shipped support. Do not claim
   ordinary chatgpt.com monitoring unless a real browser/native bridge exists.
7. Update vigil-web so a first-time visitor understands the product in five
   seconds. Show the real sequence visually: agents work silently, a human-only
   decision opens one corner pill, the user approves, work resumes. Keep copy
   concise and distinguish “shipping now” from “in source” and “planned.”
8. Test desktop and mobile layouts, keyboard navigation, reduced motion, loading,
   all CTAs, the live demo, and the production build.
9. Commit coherent working changes to each repository and push main only after
   tests pass. Let Vercel deploy vigil-web and verify the production URLs.

Product rules:
- Windows first. macOS remains a future release until tested and packaged there.
- One provider-neutral queue, never separate widgets per agent.
- Notify only when a human action is needed. Working, done, and idle may change
  color but must not open the pill.
- Destructive actions always bypass notification cooldowns.
- Keep everything local; no account, telemetry, or network service.
- Never invent test numbers, testimonials, download counts, or compatibility.
- Keep the landing page visually restrained, product-led, and fast. Animation
  must explain causality rather than decorate the page.
- Preserve accessibility and prefers-reduced-motion behavior.
- Be brutally honest during QA. If the experience would not make a Windows
  multi-agent user want to install Vigil, identify the exact trust or clarity
  gap and fix it before stopping.

Deliverables:
- Tested Codex/ChatGPT coding-agent integration on Windows.
- Updated Windows installer and release artifact.
- Provider architecture documentation and migration notes.
- A clearer, more persuasive production landing page.
- A final report with commits, release URL, production URL, measured latency,
  tests run, remaining limitations, and the next highest-value step.

Work autonomously within these repositories. Ask only when credentials,
code-signing purchases, or an irreversible product decision is truly required.
