"""Verify every installable Skill declares the committed-source generation gate."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = "Git source snapshot gate"
CLEANUP = "process-only temporary artifacts"


def main() -> int:
    missing = []
    for skill in sorted((ROOT / "skills").iterdir()):
        if not skill.is_dir() or skill.name.startswith("_"):
            continue
        for name in ("SKILL.md", "agents/openai.yaml"):
            path = skill / name
            if not path.is_file() or REQUIRED not in path.read_text(encoding="utf-8") or CLEANUP not in path.read_text(encoding="utf-8"):
                missing.append(str(path.relative_to(ROOT)))
    if missing:
        raise SystemExit("missing committed Git snapshot gate: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
