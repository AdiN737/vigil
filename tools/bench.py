"""Measure what Vigil costs: hook latency, memory, CPU.

    python tools/bench.py                       # source hook
    python tools/bench.py --exe path\\to\\hook\\vigil-hook.exe   # the real build

The hook runs inside the agent's critical path, so its latency is added to
every tool call the agent makes. That number belongs on the website before
someone installs this, not in a footnote afterwards.

Reported: p50 / p95 / max wall time for one hook invocation, and the widget's
memory and CPU if it is running. Nothing is uploaded; this prints and exits.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

PAYLOADS = {
    "working (PreToolUse)": dict(
        state="working", payload=dict(
            session_id="bench", cwd="C:/work/demo", hook_event_name="PreToolUse",
            tool_name="Bash", tool_input={"command": "npm run build"})),
    "done (Stop)": dict(
        state="done", payload=dict(
            session_id="bench", cwd="C:/work/demo", hook_event_name="Stop")),
    "idle (SessionEnd)": dict(
        state="idle", payload=dict(
            session_id="bench", cwd="C:/work/demo", hook_event_name="SessionEnd")),
}


def run_once(cmd, payload, env):
    data = json.dumps(payload)
    t0 = time.perf_counter()
    subprocess.run(cmd, input=data, text=True, capture_output=True, env=env)
    return (time.perf_counter() - t0) * 1000


def pct(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def widget_cost():
    """Memory and CPU of a running Vigil widget, via Windows' own tools."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$p = Get-Process Vigil -ErrorAction SilentlyContinue | "
             "Sort-Object WorkingSet64 -Descending | Select-Object -First 1; "
             "if ($p) { $a = $p.TotalProcessorTime.TotalSeconds; Start-Sleep -Seconds 10; "
             "$p.Refresh(); $b = $p.TotalProcessorTime.TotalSeconds; "
             "'{0} {1}' -f [math]::Round($p.WorkingSet64/1MB,1), "
             "[math]::Round((($b-$a)/10)*100/[Environment]::ProcessorCount,2) }"],
            capture_output=True, text=True, timeout=60).stdout.split()
        if len(out) == 2:
            return float(out[0]), float(out[1])
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", help="packaged vigil-hook.exe (default: run from source)")
    ap.add_argument("-n", type=int, default=40, help="runs per event type")
    args = ap.parse_args()

    base = [args.exe] if args.exe else [sys.executable, str(ROOT / "app/vigil_hook_main.py")]
    label = "packaged vigil-hook.exe" if args.exe else "source (python)"

    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, VIGIL_DATA_DIR=td)
        print(f"Hook latency — {label}, {args.n} runs each\n")
        print(f"  {'event':22s} {'p50':>8s} {'p95':>8s} {'max':>8s}")
        for name, spec in PAYLOADS.items():
            cmd = base + [spec["state"], "claude"]
            run_once(cmd, spec["payload"], env)              # warm the cache
            ms = [run_once(cmd, spec["payload"], env) for _ in range(args.n)]
            print(f"  {name:22s} {pct(ms, 50):7.0f}ms {pct(ms, 95):7.0f}ms "
                  f"{max(ms):7.0f}ms")
        print(f"\n  (median of medians: "
              f"{statistics.median([pct([run_once(base + [s['state'], 'claude'], s['payload'], env) for _ in range(5)], 50) for s in PAYLOADS.values()]):.0f}ms)")

    cost = widget_cost()
    print()
    if cost:
        print(f"Widget — {cost[0]} MB resident, {cost[1]}% of one core over 10s")
    else:
        print("Widget — not running, so memory and CPU were not measured.")
    print("\nThese are this machine's numbers. Re-run before quoting them anywhere.")


if __name__ == "__main__":
    main()
