"""Shared lifeline and activation checks for generated Mermaid sequences."""
from collections import Counter
import re


TECHNICAL_ROLES = frozenset({"service", "middleware", "database", "storage", "external", "executor"})
PARTICIPANT_ROLES = TECHNICAL_ROLES | {"actor", "caller"}


def participant_declaration(alias, label, role):
    if role not in PARTICIPANT_ROLES:
        raise ValueError(f"UNKNOWN_PARTICIPANT_ROLE: {role}")
    kind = "participant" if role in TECHNICAL_ROLES else "actor"
    return f"{kind} {alias} as {label}"


class Activations:
    """Track exact call identities; closing a view never invents a return."""

    def __init__(self, lines, technical):
        self.lines = lines
        self.technical = set(technical)
        self.active = {}

    def open(self, key, participant):
        if participant in self.technical:
            if key in self.active:
                raise ValueError(f"DUPLICATE_ACTIVATION: {key}")
            self.active[key] = participant
            self.lines.append(f"activate {participant}")

    def close(self, key):
        participant = self.active.get(key)
        if participant:
            if next(k for k in reversed(self.active) if self.active[k] == participant) != key:
                raise ValueError(f"ACTIVATION_RETURN_ORDER_INVALID: {key}")
            self.active.pop(key)
            self.lines.append(f"deactivate {participant}")

    def boundary(self, retained=()):
        for key in reversed(tuple(self.active)):
            if key not in retained:
                self.lines.append(f"Note over {self.active[key]}: 执行观察到此处，未确认完成")
                self.close(key)


def validate_sequence(diagram, roles=None):
    """Check declarations and activation depth on each control arm and in Mermaid order.

    A participant declaration denotes a technical component; external human/test
    initiators must use actor. Domain canonical checks bind that choice to facts.
    """
    lines = [line.strip() for line in diagram.splitlines() if line.strip() and not line.strip().startswith("%%")]
    if not lines or lines[0] != "sequenceDiagram":
        return ["missing sequenceDiagram header"]
    errors = []
    if "autonumber" not in lines:
        errors.append("missing autonumber")
    declared = {}
    for line in lines:
        if match := re.fullmatch(r"(participant|actor)\s+(\w+)(?:\s+as\s+.+)?", line):
            kind, alias = match.groups()
            if alias in declared:
                errors.append(f"duplicate participant: {alias}")
            declared[alias] = kind
    technical = {alias for alias, kind in declared.items() if kind == "participant"}
    if roles is not None:
        for alias, role in roles.items():
            if role not in PARTICIPANT_ROLES or alias not in declared:
                errors.append(f"unknown participant role: {alias}")
            elif (role in TECHNICAL_ROLES) != (alias in technical):
                errors.append(f"participant role/declaration mismatch: {alias}")
    depth = Counter()
    blocks = []
    activated = set()
    for index, line in enumerate(lines[1:], 1):
        if match := re.fullmatch(r"(activate|deactivate)\s+(\w+)", line):
            action, alias = match.groups()
            if alias not in technical:
                errors.append(f"activation requires a declared technical participant: {alias}")
            if action == "activate":
                depth[alias] += 1
                activated.add(alias)
            elif depth[alias] <= 0:
                errors.append(f"deactivate without activation: {alias}")
            else:
                depth[alias] -= 1
        elif line.startswith(("alt ", "opt ", "loop ", "par ")):
            blocks.append((line.split()[0], +depth))
        elif line.startswith(("else ", "and ")):
            expected = "alt" if line.startswith("else ") else "par"
            if not blocks or blocks[-1][0] != expected:
                errors.append(f"unexpected control arm: {line}")
            elif +depth != blocks[-1][1]:
                errors.append(f"activation leaks across control arm: {line}")
        elif line == "end":
            if not blocks:
                errors.append("unmatched end")
            elif +depth != blocks.pop()[1]:
                errors.append("activation depth differs at control exit")
        elif match := re.fullmatch(r"(\w+)\s*(-->>|->>|-->|->|--\)|-\))([+-]?)\s*(\w+)\s*:\s*.*", line):
            sender, arrow, change, receiver = match.groups()
            if sender not in declared or receiver not in declared:
                errors.append(f"unknown participant in message: {line}")
            if change == "+":
                if receiver not in technical:
                    errors.append(f"activation requires a technical participant: {receiver}")
                depth[receiver] += 1
                activated.add(receiver)
            elif change == "-":
                if sender not in technical or depth[sender] <= 0:
                    errors.append(f"deactivate without technical activation: {sender}")
                else:
                    depth[sender] -= 1
            if arrow in {"->>", "->", "-)", "--)"} and receiver in technical and not depth[receiver]:
                following = lines[index + 1] if index + 1 < len(lines) else ""
                if following != f"activate {receiver}":
                    errors.append(f"technical request lacks activation: {receiver}")
        elif line.startswith("Note over "):
            match = re.match(r"Note over\s+(\w+)(?:\s*,\s*(\w+))?:", line)
            if not match or any(alias not in declared for alias in match.groups() if alias):
                errors.append(f"unknown participant in note: {line}")
        elif line == "autonumber" or line.startswith(("participant ", "actor ")):
            continue
        else:
            errors.append(f"unsupported sequence statement: {line}")
    if blocks:
        errors.append("unclosed control block")
    if +depth:
        errors.append("unclosed activation: " + ", ".join(sorted(+depth)))
    if not activated:
        errors.append("sequence diagram needs a technical activation")
    return errors
