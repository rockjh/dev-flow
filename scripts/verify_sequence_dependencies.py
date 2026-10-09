"""Installation-time wheel availability matrix, never invoked during source scanning."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = [value for value in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"] if value.startswith("tree-sitter")]
PLATFORMS = ("win_amd64", "manylinux2014_x86_64", "macosx_10_9_x86_64")


def check(platform):
    with tempfile.TemporaryDirectory(prefix="devflow-sequence-wheels-") as temporary:
        result = subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
            "--platform", platform, "--python-version", "3.11", "--implementation", "cp", "--abi", "cp311", "--abi", "abi3",
            "--dest", temporary, *DEPENDENCIES], capture_output=True, text=True, timeout=180)
        return {"platform": platform, "python": "3.11", "binary_wheels_available": result.returncode == 0,
                "wheels": sorted(path.name for path in Path(temporary).glob("*.whl")),
                "runtime_executed": False,
                "diagnostic": result.stderr[-1500:] if result.returncode else ""}


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as executor:
        report = list(executor.map(check, PLATFORMS))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(item["binary_wheels_available"] for item in report) else 1)
