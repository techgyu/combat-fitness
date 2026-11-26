"""Build a standalone Windows folder and a ZIP ready to hand to another person."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.name != "nt":
        raise SystemExit("Build the Windows distribution on Windows.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", *(["--clean"] if args.clean else []),
                    "--distpath", str(output), "--workpath", str(ROOT / "build"),
                    str(ROOT / "tools/portable.spec")], cwd=ROOT, check=True)
    folder = output / "CombatFitness"
    (folder / "README.txt").write_text(
        "장병 전투체력 관리 — Windows 64비트 배포본\n\n"
        "1. ZIP 파일의 압축을 모두 풉니다.\n"
        "2. CombatFitness.exe를 더블클릭합니다. 웹 화면이 자동으로 열립니다.\n"
        "3. 최초 한 번 실행 창에 본인의 Claude API 키를 입력하고 '키 저장'을 누릅니다.\n"
        "4. 웹에서 군번 조회 또는 새 사례 입력 후 '8주 계획 생성'을 누릅니다.\n"
        "5. 종료할 때는 실행 창의 '종료'를 누릅니다. 브라우저만 닫으면 서버는 계속 실행됩니다.\n\n"
        "Python / Conda / pip / 패키지 설치는 필요하지 않습니다.\n"
        "CombatFitness.exe와 _internal 폴더를 같은 폴더에 유지하세요. EXE만 보내면 실행되지 않습니다.\n"
        "조회와 목표 계산은 오프라인으로 사용할 수 있습니다.\n"
        "AI 계획 생성에는 인터넷과 사용 가능한 Claude API 키/크레딧이 필요합니다.\n"
        "배포본에는 개발자의 API 키, 기존 DB, 생성 이력이 포함되지 않습니다.\n"
        "합성 장병 1,000명으로 시작하며 입력 기록은 현재 PC에 저장됩니다.\n"
        "저장 위치: %LOCALAPPDATA%\\CombatFitness\n"
        "API 키는 Windows 계정별로 암호화해 저장됩니다. 다른 PC에서는 다시 입력하세요.\n"
        "기본 포트는 웹/모듈1 8000, 모듈2 8001이며 사용 중이면 빈 포트를 자동 선택합니다.\n"
        "키 없이도 조회와 입력은 가능합니다. 실행만으로 Claude를 호출하지 않습니다.\n"
        "기준·운동량은 시제품 조건이며 실제 훈련 효과를 검증한 결과가 아닙니다.\n",
        encoding="utf-8-sig")
    notices = folder / "licenses"
    notices.mkdir(exist_ok=True)
    package_names = ["anthropic", "pydantic", "certifi", "packaging", "setuptools"]
    versions = {}
    while package_names:
        name = canonicalize_name(package_names.pop())
        if name in versions:
            continue
        try:
            package = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        versions[name] = package.version
        for requirement in package.requires or []:
            dependency = Requirement(requirement)
            if dependency.marker is None or dependency.marker.evaluate({"extra": ""}):
                package_names.append(dependency.name)
        for file in package.files or []:
            if any(part.lower().startswith(("license", "copying", "notice")) for part in file.parts):
                source = package.locate_file(file)
                if source.is_file():
                    target = notices / name / str(file).replace("/", "_").replace("\\", "_")
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
    for name in ("LICENSE.txt", "LICENSE_PYTHON.txt"):
        python_license = Path(sys.base_prefix) / name
        if python_license.exists():
            shutil.copy2(python_license, notices / ("Python-" + name))
    (folder / "VERSIONS.json").write_text(json.dumps({"python": sys.version, "packages": versions},
                                                   indent=2), encoding="utf-8")
    # Never copy developer credentials, local databases or server logs into the release.
    forbidden = [p for p in folder.rglob("*") if p.is_file() and
                 (p.name.startswith(".env") or p.suffix.lower() in {".sqlite3", ".sqlite", ".db", ".log"}
                  or p.name == "api-key.bin")]
    if forbidden:
        raise RuntimeError("Private runtime files found in release: " + ", ".join(p.name for p in forbidden))
    report = ROOT / "build/portable-self-test.json"
    # Restrict PATH and Python environment to prove the EXE uses its own bundled runtime.
    environment = {k: v for k, v in os.environ.items()
                   if k not in {"ANTHROPIC_API_KEY", "PYTHONPATH", "PYTHONHOME"}
                   and not k.startswith("CONDA")}
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    environment.pop("TCL_LIBRARY", None)
    environment.pop("TK_LIBRARY", None)
    subprocess.run([str(folder / "CombatFitness.exe"), "--self-test", str(report)],
                   cwd=folder, env=environment, check=True, timeout=120)
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("status") != "passed":
        raise RuntimeError("Packaged self-test failed; see build/portable-self-test.json")
    archive = shutil.make_archive(str(output / "CombatFitness-Windows-x64"), "zip",
                                  root_dir=output, base_dir="CombatFitness")
    print("Portable release: " + archive)
    print("Self-test passed; no external API was called.")


if __name__ == "__main__":
    main()
