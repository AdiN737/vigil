# Shipping a Vigil update

Installed copies check vigilit.app about once a day. When a newer signed
release is live, the tray offers it; the user clicks once and it installs on
the next restart. Nothing reaches a user's machine unless it is signed with
the private key that only the publisher holds.

```
edit code ─► bump VERSION ─► build ─► upload (draft) ─► publish ─► every install offers it within ~24h
```

## Every release

1. Bump `VERSION` in `app/vigil_version.py` (e.g. `0.2.0` → `0.2.1`).
2. Run the tests:
   `PYTHONPATH="app:." python -m unittest tests.test_providers tests.test_hook_process tests.test_update`
3. Build: `python tools/build_release.py` → `dist/Vigil-<version>-windows.zip`
4. Sign and upload as a draft: `python tools/publish_release.py upload --notes "What changed"`
5. Install the draft yourself if you want a final check, then go live:
   `python tools/publish_release.py publish <version>`

Bad release? `python tools/publish_release.py unpublish <version>`, then ship
a fixed higher version. Copies that already installed it keep it until then.

## Live settings (no new build needed)

| Command | Effect |
|---|---|
| `publish_release.py message "text"` | One line in every tray menu (and a single notification). `--clear` removes it. |
| `publish_release.py approvals off` | Kill switch: Vigil stops answering permission requests; agents show their own prompts. `on` restores. |
| `publish_release.py status` | What is live, drafted, and the current settings. |

Settings reach installs at their next daily check, not instantly.

## The signing key

- Private key: `%USERPROFILE%\.vigil-signing\release-private.pem`. Never commit
  it, never upload it. Keep an offline backup (password manager file vault).
- Lose it and installed copies can never be updated again; they would need a
  manual reinstall of a build carrying a new public key.
- Leak it and someone could sign malware your users would accept. Ship a new
  key in a release immediately, and rotate.
