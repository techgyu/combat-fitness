# PyInstaller build specification. Only public resources are allow-listed.
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [
    (str(root / "frontend" / name), "frontend")
    for name in ("index.html", "app.js", "styles.css")
]
datas += [(str(root / "docs" / "openapi.json"), "docs"),
          (str(root / "backend/module1/03_validate_and_compute.py"), "module1"),
          (str(root / "backend/module1/data/synthetic_soldiers.json"), "module1/data")]
for module, folder in (("module1", "config"), ("module2", "data")):
    datas += [(str(path), f"{module}/{folder}")
              for path in (root / "backend" / module / folder).glob("*.json")]
datas += collect_data_files("certifi") + copy_metadata("anthropic")

# A venv created from Conda still depends on its base environment's native DLLs.
# Explicit sources avoid accidentally collecting incompatible DLLs from another
# Conda installation on PATH (in particular libexpat/OpenSSL/Tcl).
native = Path(sys.base_prefix) / "Library" / "bin"
binaries = [(str(path), ".") for path in native.glob("*.dll")
            if path.name.lower() not in ("tcl86t.dll", "tk86t.dll")] if native.exists() else []

a = Analysis([str(root / "desktop_launcher.py")],
             pathex=[str(root), str(root / "backend")],
             binaries=binaries, datas=datas,
             hiddenimports=collect_submodules("anthropic") + ["csv", "unittest"],
             hookspath=[], runtime_hooks=[],
             excludes=["pytest", "fastapi", "uvicorn", "numpy", "pandas", "matplotlib", "IPython", "tkinter"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CombatFitness", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False,
          console=bool(os.environ.get("COMBAT_FITNESS_CONSOLE")))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CombatFitness")
