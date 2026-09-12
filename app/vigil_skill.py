"""Portable Codex skill, installed with Vigil; embedded for frozen builds."""
from pathlib import Path
import shutil
import time

SKILL = r"""---
name: vigil
description: Start the installed Vigil desktop widget when the user says "start vigil", "launch vigil", or "turn on vigil"; also check status or stop Vigil when requested.
---

# Vigil

On Windows, run the bundled PowerShell helper with the requested action.
Resolve scripts/vigil.ps1 relative to this SKILL.md. No Python or developer
checkout is needed. Example for the standard user installation:

```powershell
& "$env:USERPROFILE\.agents\skills\vigil\scripts\vigil.ps1" -Action Start
```

Use Start for "start vigil", Status for a status request, and Stop only when
the user asks to stop Vigil. The helper reports structured JSON and a nonzero
exit code on failure. Confirm success only after it reports running or
already_running. Keep the response short and tell the user the dot is above
their taskbar. Do not start a demo or generate test notifications.

If not_installed is returned, direct the user to the Vigil installer at
https://github.com/AdiN737/vigil/releases. Do not claim the widget is running.
The public v0.1.1 release predates this skill and Codex integration.

Starting the widget does not activate Codex hooks. If no events appear after
startup, explain that the user must review and trust the Vigil definitions in
/hooks and start a fresh Codex session. Never bypass hook trust.

This helper targets Windows. macOS support remains a separate preview; do not
run the Windows helper on other systems.
"""

LAUNCHER = r"""param(
    [ValidateSet('Start','Status','Stop')]
    [string]$Action = 'Start'
)
$ErrorActionPreference = 'Stop'
$exe = Join-Path $env:USERPROFILE '.vigil\app\Vigil.exe'

function Find-Vigil {
    @(Get-Process -Name Vigil -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path -eq $exe })
}
function Report($state, $items) {
    [pscustomobject]@{
        status = $state
        processIds = @($items | ForEach-Object Id)
        executable = $exe
    } | ConvertTo-Json -Compress
}
try {
    $items = @(Find-Vigil)
    if ($Action -eq 'Status') {
        if ($items.Count) { Report 'running' $items }
        else { Report 'stopped' @() }
        exit 0
    }
    if ($Action -eq 'Stop') {
        $items | Stop-Process
        if ($items.Count) { $items | Wait-Process -Timeout 10 }
        Report 'stopped' @()
        exit 0
    }
    if ($items.Count) { Report 'already_running' $items; exit 0 }
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        Report 'not_installed' @()
        exit 1
    }
    Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $items = @(Find-Vigil)
    } until ($items.Count -or [DateTime]::UtcNow -gt $deadline)
    if (-not $items.Count) { Report 'failed_to_start' @(); exit 1 }
    Start-Sleep -Seconds 5
    $items = @(Find-Vigil)
    if (-not $items.Count) { Report 'exited_during_startup' @(); exit 1 }
    if (-not @($items | Where-Object { $_.MainWindowTitle -eq 'Vigil' }).Count) {
        Report 'window_not_ready' $items; exit 1
    }
    Report 'running' $items
} catch {
    [pscustomobject]@{ status = 'error'; message = $_.Exception.Message } |
        ConvertTo-Json -Compress
    exit 1
}
"""


def install_skill(destination=None):
    """Install owned files only, backing up changed files before replacement."""
    root = Path(destination) if destination else Path.home() / '.agents/skills/vigil'
    try:
        for relative, content in {
            'SKILL.md': SKILL, 'scripts/vigil.ps1': LAUNCHER
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_text(encoding='utf-8-sig') != content:
                shutil.copy2(path, path.with_name(path.name + '.backup-' + str(time.time_ns())))
            temporary = path.with_suffix(path.suffix + '.tmp')
            temporary.write_text(content, encoding='utf-8')
            temporary.replace(path)
        return True, 'Codex skill installed. In a fresh Codex task, say "start vigil".'
    except Exception as exc:
        return False, f'Could not install Codex skill: {exc}'


if __name__ == '__main__':
    ok, message = install_skill()
    print(message)
    raise SystemExit(0 if ok else 1)
