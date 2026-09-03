"""
Vigil, but it's your terminal. Run this in a spare window:  python watch.py

This is the whole product with the hardware faked out. If you find yourself
glancing at this window while Claude works, the device is worth building.
If you ignore it, you just saved yourself $50 and a month.
"""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")

# ANSI colours: the ring, basically
C = {
    1: ("\033[90m", "IDLE"),          # grey
    2: ("\033[94m", "WORKING"),       # blue
    3: ("\033[92m", "DONE"),          # green
    4: ("\033[93m", "QUESTION"),      # yellow
    5: ("\033[33m", "BLOCKED"),       # amber
    6: ("\033[91m", "FAILED"),        # red
    7: ("\033[97m\033[41m", "DESTRUCTIVE"),   # white on red
}
R = "\033[0m"


def ago(t):
    s = int(time.time() - t)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s//60}m"
    return f"{s//3600}h{(s%3600)//60:02d}"


def main():
    os.system("")            # enables ANSI on Windows terminals
    last = None
    while True:
        try:
            with open(STATE) as f:
                r = json.load(f)
        except Exception:
            r = {"tier": 1, "state": "idle", "project": "-", "detail": "",
                 "since": time.time()}

        tier = r.get("tier", 1)
        col, name = C.get(tier, C[1])
        blink = "\a" if tier >= 6 and r != last else ""   # terminal bell on bad news

        os.system("cls" if os.name == "nt" else "clear")
        print()
        print(f"  {col}  ●●●●●●●●  {name}  ●●●●●●●●  {R}")
        print()
        print(f"     project   {r.get('project','-')}")
        print(f"     waiting   {ago(r.get('since', time.time()))}")
        if r.get("detail"):
            print(f"     doing     {r['detail'][:60]}")
        print()
        if tier >= 5:
            print(f"  {col} >> GO LOOK AT YOUR TERMINAL << {R}")
        if tier == 7:
            print("     (this one wants to delete or deploy something)")
        print(f"\n  {'-'*46}")
        print("   tier 1 idle  2 working  3 done  4 question")
        print("        5 blocked  6 failed  7 destructive")
        print(blink, end="", flush=True)

        last = r
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
