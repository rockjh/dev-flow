"""Canonical source facts. Adapters are statically registered and fail closed."""
from __future__ import annotations
import ast
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from ..core.redaction import redact
from ..core.artifacts import state_root, write_json
from ..core.syntax import normalized, parser_versions
from .git import source_view

ADAPTER_VERSION = "5.2.1"
FACT_ARRAYS = ("calls", "branches", "persistence_actions", "effects", "outcomes")
RESOURCE_TYPES = {"relational_table", "document_collection", "kv_namespace", "search_index", "object_storage", "file_resource"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stable_id(prefix, *parts):
    return prefix + "-" + digest(parts)[:20]


def trim_cache(directory, limit=128):
    """Bound rebuildable caches; never touch run or recovery artifacts."""
    files = [p for p in directory.glob("*.json") if len(p.stem) == 64
             and all(c in "0123456789abcdef" for c in p.stem) and not p.is_symlink()]
    ordered = []
    for path in files:
        try:
            ordered.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError:
            continue  # Another process may have already pruned this cache.
    for _, path in sorted(ordered)[:-limit]:
        path.unlink(missing_ok=True)


class Facts:
    def __init__(self, scan, entry, sources, hints=(), budget=2000):
        self.scan, self.entry, self.sources, self.budget = scan, entry, sources, budget
        self.ordinals, self.stack, self.background, self.count = Counter(), [], [], 0
        self.hints = {h["target_id"]: h for h in hints if h["entry_id"] == entry.entry_id}
        self.value = {
            "schema_version": 6, "entry_id": entry.entry_id, "source_commit": scan.git.target,
            "source_fingerprint": scan.source_fingerprint, "adapter_version": ADAPTER_VERSION,
            "registration": {"kind": entry.kind, "identifier": entry.identifier, "handler": entry.handler,
                "business_name": entry.business_name, "trigger_summary": entry.trigger_summary,
                "source_evidence": entry.source_evidence},
            "participants": [], "sources": [], **{k: [] for k in FACT_ARRAYS}, "flow": [], "gaps": [],
            "coverage": {"scope": "selected-entry-reachable", "complete": False, "persistence": "unknown",
                         "limitations": ["static conditional reachability; no general path satisfiability or concurrency proof"]},
        }
        if entry.file.endswith(".java"):
            self.value["adapter_dependencies"] = {"tree-sitter": parser_versions("java")[0],
                "tree-sitter-java": parser_versions("java")[1]}
        elif entry.file.endswith((".ts", ".tsx", ".js", ".jsx", ".go")):
            language = "go" if entry.file.endswith(".go") else "typescript" if entry.file.endswith((".ts", ".tsx")) else "javascript"
            self.value["adapter_dependencies"] = {"tree-sitter": parser_versions(language)[0],
                "tree-sitter-" + language: parser_versions(language)[1]}
        else:
            self.value["adapter_dependencies"] = {"python-ast": __import__("sys").version.split()[0]}

    def source(self, file, node, identity, raw=None):
        raw = self.sources[file].encode() if raw is None else raw
        if isinstance(node, ast.AST):
            semantic = ast.dump(node, include_attributes=False)
            line, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        else:
            semantic = raw[node.start_byte:node.end_byte].decode("utf-8") if node.type in {"line_comment", "block_comment"} else normalized(node, raw)
            line, end = node.start_point.row + 1, node.end_point.row + 1
        ref = stable_id("S", file, identity, semantic)
        proof = {"evidence_id": ref, "file": file, "line": line, "end_line": end,
                 "content_hash": digest(semantic), "declaration_id": identity}
        if proof not in self.value["sources"]:
            self.value["sources"].append(proof)
        return ref

    def participant(self, identity, role):
        pid = stable_id("A", identity, role)
        item = {"participant_id": pid, "identity": identity, "role": role}
        if item not in self.value["participants"]:
            self.value["participants"].append(item)
        return pid

    def source_document(self, file, identity):
        content_hash = digest(self.sources[file])
        ref = stable_id("S", file, identity, content_hash)
        proof = {"evidence_id": ref, "file": file, "line": 1,
            "end_line": max(1, len(self.sources[file].splitlines())),
            "content_hash": content_hash, "declaration_id": identity}
        if proof not in self.value["sources"]:
            self.value["sources"].append(proof)
        return ref

    def add(self, array, typ, source, context, phase, controls, details, refs=()):
        key = (array, typ, source, context, digest(details))
        ordinal = self.ordinals[key]
        self.ordinals[key] += 1
        fid = stable_id({"branches": "B", "persistence_actions": "P", "outcomes": "O", "calls": "C", "effects": "E"}[array], *key, ordinal)
        item = {"fact_id": fid, "type": typ, "context_id": context, "phase": phase,
                "conditions": list(controls), "evidence_refs": list(dict.fromkeys([source, *refs])), "details": details}
        self.value[array].append(item)
        return item

    def step(self, kind, fact, controls=(), arm=""):
        self.value["flow"].append({"step_id": stable_id("T", fact["fact_id"], kind, len(self.value["flow"])),
            "kind": kind, "fact_id": fact["fact_id"], "context_id": fact["context_id"],
            "phase": fact["phase"], "controls": list(controls), "arm": arm})

    def gap(self, code, source, context, question, candidates=(), controls=()):
        finding = {"finding_id": stable_id("G", self.entry.entry_id, code, source, context), "code": code,
                   "critical": True, "target_id": context, "question": question,
                   "evidence_refs": [source], "candidates": list(candidates), "controls": list(controls)}
        if finding not in self.value["gaps"]:
            self.value["gaps"].append(finding)
        return finding

    def outcome(self, typ, source, context, phase, controls, expression="", refs=()):
        item = self.add("outcomes", typ, source, context, phase, controls,
            {"expression": expression, "observed_by_entry": phase == "entry" and typ in {"entry_response", "normal_completion", "async_submission", "async_rejection"}, "meaning": typ,
             "guarantee": "conditional static fact"}, refs)
        self.step("outcome", item, controls)
        return item

    def outbound(self, call, system, endpoint, refs=()):
        """A declared/literal destination proves an attempt, never delivery."""
        call["type"] = "external_api"
        call["details"].update(target_owner=system, endpoint=endpoint, may_throw=True)
        call["evidence_refs"] = list(dict.fromkeys([*call["evidence_refs"], *refs]))
        self.participant(system, "external")
        effect = self.add("effects", "external_call_attempt", call["evidence_refs"][0], call["context_id"],
            call["phase"], call["conditions"], {"system": system, "endpoint": endpoint, "delivery": "not established"}, refs)
        self.step("state_change", effect, call["conditions"])

    def finish(self):
        for participant in self.value["participants"]:
            identity, role = participant["identity"], participant["role"]
            if role == "storage":
                refs = [ref for action in self.value["persistence_actions"] if action["details"]["resource_name"] == identity for ref in action["evidence_refs"]]
            elif role == "caller":
                refs = [s["evidence_id"] for s in self.value["sources"][:1]]
            elif role == "external":
                refs = [ref for call in self.value["calls"] if call["details"].get("target_owner") == identity for ref in call["evidence_refs"]]
            else:
                separator = ":" if self.entry.file.endswith(".py") else "."
                refs = [s["evidence_id"] for s in self.value["sources"] if s["declaration_id"] == identity or s["declaration_id"].startswith(identity + separator)]
            participant["evidence_refs"] = list(dict.fromkeys(refs))
        self.value["coverage"]["complete"] = not self.value["gaps"]
        self.value["coverage"]["persistence"] = ("proven" if self.value["persistence_actions"] else
            "none_in_verified_scope" if not self.value["gaps"] else "unknown")
        return redact(self.value)


def collect_evidence(scan, *, hints=(), sources=None, budget=2000):
    from .java_behavior import JavaIndex, JavaFacts
    from .python_behavior import PythonFacts
    from .tree_behavior import TreeFacts
    cache = None
    if sources is None:
        identity = digest([str(scan.root.resolve()), scan.git.target, scan.source_fingerprint,
            ADAPTER_VERSION, sys.version, parser_versions("java"), parser_versions("typescript"), parser_versions("go"),
            [asdict(entry) for entry in scan.entries], list(hints), budget])
        cache = state_root() / "biz-flow" / "facts-cache" / (identity + ".json")
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved["identity"] == identity and saved["checksum"] == digest(saved["facts"]):
                print(f"progress stage=evidence completed={len(scan.entries)} total={len(scan.entries)} cache=hit", file=sys.stderr)
                return saved["facts"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    if sources is None:
        with source_view(scan.root, scan.git.target) as (root, _):
            sources = {file: (root / file).read_text(encoding="utf-8") for file in scan.files}
    index = JavaIndex(sources)
    python_index = None
    result = {}
    print(f"progress stage=evidence completed=0 total={len(scan.entries)} cache=miss", file=sys.stderr)
    for completed, entry in enumerate(scan.entries, 1):
        if entry.file.endswith(".java"):
            adapter = JavaFacts(scan, entry, sources, hints, budget, index=index)
        elif entry.file.endswith(".py"):
            adapter = PythonFacts(scan, entry, sources, hints, budget, index=python_index)
            python_index = (adapter.definitions, adapter.parents, adapter.shadowed)
        elif entry.file.endswith((".ts", ".tsx", ".js", ".jsx", ".go")):
            adapter = TreeFacts(scan, entry, sources, hints, budget)
        else:
            adapter = Facts(scan, entry, sources, hints, budget)
            adapter.gap("SOURCE_ADAPTER_UNAVAILABLE", entry.entry_id, entry.entry_id, "No registered behavior adapter for this language")
        result[entry.entry_id] = adapter.analyze() if hasattr(adapter, "analyze") else adapter.finish()
        print(f"progress stage=evidence completed={completed} total={len(scan.entries)}", file=sys.stderr)
    if cache is not None:
        write_json(cache, {"identity": identity, "facts": result, "checksum": digest(result)})
        trim_cache(cache.parent)
    return result
