"""Build-time synchronization of the sequence Skill's shared diagram contract."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


OWNER = "sequence-diagram-generator"
REFERENCE = "references/diagram-conventions.md"
GENERATED = (
    "<!-- Generated from the sequence-diagram-generator Skill by "
    "scripts/sync_sequence_conventions.py; do not edit. -->\n\n"
).encode("utf-8")
SEQUENCE_USAGE = re.compile(r"sequenceDiagram|时序图|sequence[ -]diagrams?", re.IGNORECASE)


def sync_conventions(skills: Path, *, check: bool = False) -> list[str]:
    """Require local routing for every diagram consumer, then synchronize copies."""
    source = (skills / OWNER / REFERENCE).read_bytes()
    errors = []
    consumers = []
    # This scan is a release gate, never runtime Skill or prompt discovery.
    for entry in sorted(skills.glob("*/SKILL.md")):
        skill = entry.parent
        documents = [path for path in skill.rglob("*")
                     if path.is_file() and path.suffix in {".md", ".yaml"}
                     and path != skill / REFERENCE]
        contents = [path.read_text(encoding="utf-8") for path in documents]
        if not any(REFERENCE in content or SEQUENCE_USAGE.search(content) for content in contents):
            continue
        for route in (entry, skill / "agents/openai.yaml"):
            if not route.is_file() or REFERENCE not in route.read_text(encoding="utf-8"):
                errors.append(f"{route}: sequence diagrams require a local {REFERENCE} route")
        if skill.name != OWNER:
            target = skill / REFERENCE
            consumers.append(target)
            if check and (not target.is_file() or target.read_bytes() != GENERATED + source):
                errors.append(f"{target}: shared sequence conventions are missing or stale")
    if not errors and not check:
        for target in consumers:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(GENERATED + source)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args()
    errors = sync_conventions(Path(__file__).resolve().parents[1] / "skills", check=args.check)
    for error in errors:
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
