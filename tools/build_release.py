"""Build the Windows release zip for the version in app/vigil_version.py.

    python tools/build_release.py

Builds the hook and the widget with PyInstaller in a temp folder (never in
OneDrive or the repo), assembles the same layout the installer expects:

    Vigil-<version>-windows.zip
        Vigil.exe, _internal/        the widget
        hook/vigil-hook.exe, hook/_internal/
        Install Vigil.bat, Uninstall Vigil.bat, README.txt

then re-opens the zip and checks it the way the updater will. Output lands in
dist/ (git-ignored). Signing and uploading are a separate step:
tools/publish_release.py.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))
from vigil_version import VERSION  # noqa: E402

REQUIRED = ["Vigil.exe", "hook/vigil-hook.exe", "Install Vigil.bat",
            "Uninstall Vigil.bat", "README.txt"]
# Libraries the hook must never carry: it runs on every agent event.
HOOK_FORBIDDEN = ("PySide6", "Qt6", "cryptography", "_ssl", "libssl")


def pyinstaller(spec, work):
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
         str(APP / spec)],
        cwd=APP, check=True)


def main():
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"Vigil-{VERSION}-windows.zip"

    with tempfile.TemporaryDirectory(prefix="vigil-build-") as td:
        work = Path(td)
        print(f"Building Vigil {VERSION} in {work}")
        pyinstaller("Hook.spec", work)
        pyinstaller("Vigil.spec", work)

        stage = work / "Vigil"
        shutil.copytree(work / "dist" / "Vigil", stage)
        shutil.copytree(work / "dist" / "vigil-hook", stage / "hook")
        for f in (ROOT / "packaging").iterdir():
            shutil.copy2(f, stage / f.name)

        leaked = [p.name for p in (stage / "hook").rglob("*")
                  if any(bad.lower() in p.name.lower() for bad in HOOK_FORBIDDEN)]
        if leaked:
            sys.exit(f"The hook picked up heavy libraries: {leaked[:5]}. Fix Hook.spec.")

        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(stage).as_posix())

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        bad = z.testzip()
    missing = [r for r in REQUIRED if r not in names]
    if bad or missing:
        sys.exit(f"Zip check failed. Corrupt: {bad}. Missing: {missing}")

    mb = out.stat().st_size / 1048576
    print(f"\nBuilt {out} ({mb:.1f} MB, {len(names)} files)")
    print("Next: python tools/publish_release.py")


if __name__ == "__main__":
    main()
