"""Source-proven supplemental bindings, replayed on every canonical rebuild."""
from .evidence import collect_evidence, digest, FACT_ARRAYS
from .validation import validate_evidence_request
from .git import source_view
from .java_behavior import JavaIndex
from ..core.syntax import text
import re


def fact_path(facts, target_id):
    items = {f["fact_id"]: f for array in FACT_ARRAYS for f in facts[array]}
    gaps = {g["finding_id"]: g for g in facts["gaps"]}
    target = items.get(target_id) or gaps.get(target_id)
    if target is None:
        return []
    context = target.get("context_id", target.get("target_id"))
    calls = {f["context_id"]: f for f in facts["calls"]}
    path, seen = [target_id], set()
    while context in calls:
        if context in seen:
            raise ValueError("REQUEST_CONTEXT_CYCLE")
        seen.add(context)
        call = calls[context]
        if call["fact_id"] != target_id:
            path.insert(0, call["fact_id"])
        context = call["details"]["parent_context"]
    return path


def verify_semantics(request, facts, sources):
    items = {f["fact_id"]: f for array in FACT_ARRAYS for f in facts[array]}
    target = items.get(request["target_id"])
    if request["path"] != fact_path(facts, request["target_id"]):
        raise ValueError("REQUEST_PATH_NOT_CONNECTED")
    if target is None or request["controls"] != target["conditions"]:
        raise ValueError("REQUEST_TARGET_CONTROL_MISMATCH")
    if not set(target["evidence_refs"]) <= {p["evidence_id"] for p in request["sources"]}:
        raise ValueError("REQUEST_TARGET_PROOF_MISSING")
    binding = request["binding"]
    if request["type"] == "branch_classification" and target["type"] == "if_statement":
        expected = {"true": "constant_true", "false": "constant_false"}.get(
            target["details"]["condition"].strip().strip("()").strip())
        proof = next(p for p in request["sources"] if p["evidence_id"] == target["evidence_refs"][0])
        if (expected is None or binding["classification"] != expected or binding["declaration_id"] != proof["declaration_id"]
                or binding["parameter_types"]):
            raise ValueError("BRANCH_CLASSIFICATION_NOT_PROVEN")
    elif request["type"] in {"call_binding", "callback_binding"} and target["type"] in {"invocation", "method_reference"}:
        index = JavaIndex(sources)
        candidates = [m for t in index.types.values() for m in t.methods if m.identity == binding["declaration_id"]]
        if len(candidates) != 1:
            raise ValueError("CALL_DECLARATION_NOT_UNIQUE")
        method = candidates[0]
        expected_type = "method_reference" if request["type"] == "callback_binding" else "invocation"
        gap = next((g for g in facts["gaps"] if g["target_id"] == target["context_id"] and g["code"] in {"CALL_BINDING_AMBIGUOUS", "CALLBACK_BINDING_UNRESOLVED"}), None)
        owner = index.types.get(target["details"]["receiver_type"])
        implementations = index.implementations(owner) if owner else []
        def primary(typ):
            declaration = text(typ.node, typ.raw).split("{", 1)[0]
            return (typ.imports.get("Primary") == "org.springframework.context.annotation.Primary"
                    and re.search(r"@Primary\b", declaration)
                    and any(typ.imports.get(a) == "org.springframework.stereotype." + a
                            and re.search(r"@" + a + r"\b", declaration) for a in ("Service", "Component")))
        primaries = [t for t in implementations if primary(t)]
        proof_ids = {p["declaration_id"] for p in request["sources"]}
        if (target["type"] != expected_type or not gap or method.identity not in gap["candidates"] or primaries != [method.owner]
                or binding["receiver_type"] != method.owner.name
                or binding["parameter_types"] != method.parameter_types
                or binding["classification"] != "spring_primary"
                or not {method.identity, method.owner.name} <= proof_ids):
            raise ValueError("CALL_BINDING_NOT_PROVEN")
    elif request["type"] == "behavior_classification" and target["type"] == "invocation":
        receiver, method = target["details"]["receiver_type"], target["details"]["method"]
        signature = receiver + "." + method + "(java.lang.String,java.lang.String[])"
        if (receiver, method) not in {("java.nio.file.Path", "of"), ("java.nio.file.Paths", "get")} or (
                not target["details"]["argument_types"] or any(t != "java.lang.String" for t in target["details"]["argument_types"])
                or binding != {"declaration_id": signature, "receiver_type": receiver,
                    "parameter_types": ["java.lang.String", "java.lang.String[]"], "classification": "java_se17_path_construction"}):
            raise ValueError("BEHAVIOR_CLASSIFICATION_NOT_PROVEN")
    elif request["type"] == "resource_mapping" and target["type"] == "invocation":
        index = JavaIndex(sources)
        repository = index.types.get(target["details"]["receiver_type"])
        entity = index.types.get(binding["declaration_id"])
        bound = [index.resolve_type(name, owner) for owner, name in index.repository_entities(repository)]
        config_proofs = [p for p in request["sources"] if p["declaration_id"] == "jpa-naming-configuration"]
        expected_line = "spring.jpa.hibernate.naming.physical-strategy=org.hibernate.boot.model.naming.PhysicalNamingStrategyStandardImpl"
        expected_implicit = "spring.jpa.hibernate.naming.implicit-strategy=org.hibernate.boot.model.naming.ImplicitNamingStrategyJpaCompliantImpl"
        configs = [sources[p["file"]] for p in config_proofs if p["file"].endswith(".properties")]
        header = text(entity.node, entity.raw).split("{", 1)[0] if entity else ""
        explicit_table = bool(re.search(r"@Table\b", header))
        if (not entity or bound != [entity] or target["details"]["method"] not in {"save", "saveAndFlush", "findById", "findAll", "delete", "deleteById", "existsById", "count"}
                or binding != {"declaration_id": entity.name, "receiver_type": entity.name,
                    "parameter_types": [], "classification": "jpa_standard_default_columns" if explicit_table else "jpa_standard_default_table"}
                or not re.search(r"@Entity\b", header)
                or explicit_table and (entity.imports.get("Table") not in {"jakarta.persistence.Table", "javax.persistence.Table"}
                    or not re.search(r'@Table\s*\([^)]*\bname\s*=\s*"[^\"]+"', header))
                or entity.imports.get("Entity") not in {"jakarta.persistence.Entity", "javax.persistence.Entity"}
                or len(configs) != 1 or not {expected_line, expected_implicit} <= {line.strip() for line in configs[0].splitlines()}
                or sum("physical-strategy" in line for line in configs[0].splitlines()) != 1
                or sum("implicit-strategy" in line for line in configs[0].splitlines()) != 1
                or any(re.search(r"default_schema", content) for content in sources.values())
                or any(re.search(r"physical-strategy|physical.naming|PhysicalNamingStrategy", content) and file != config_proofs[0]["file"] for file, content in sources.items() if file.endswith((".properties", ".yml", ".yaml", ".xml")))
                or entity.name not in {p["declaration_id"] for p in request["sources"]}):
            raise ValueError("RESOURCE_MAPPING_NOT_PROVEN")
    elif request["type"] == "outcome_fact" and target["type"] == "throw":
        handlers = target["details"].get("possible_handlers", [])
        thrown = re.fullmatch(r'throw\s+new\s+(?:java\.lang\.)?(IllegalArgumentException|IllegalStateException|RuntimeException)\s*\([^;]*\);', target["details"]["expression"].strip())
        matches = [h for h in handlers if any(re.search(r"\b(?:" + (thrown[1] if thrown else "never") + r"|RuntimeException|Exception|Throwable)\b", arm) for arm in h["handlers"])]
        required = {target["evidence_refs"][0], *[ref for h in matches for ref in items[h["branch_id"]]["evidence_refs"]]}
        proof = next(p for p in request["sources"] if p["evidence_id"] == target["evidence_refs"][0])
        index = JavaIndex(sources)
        owners = [t for t in index.types.values() if any(m.identity == proof["declaration_id"] for m in t.methods)]
        shadowed = not owners or any(index.resolve_type(name, owners[0]) for name in (thrown[1], "RuntimeException", "Exception", "Throwable")) if thrown else True
        if (not thrown or len(matches) != 1 or binding != {"declaration_id": proof["declaration_id"],
                "receiver_type": "java.lang." + thrown[1], "parameter_types": [], "classification": "caught_error"}
                or shadowed or matches[0] != handlers[-1]
                or not required <= {p["evidence_id"] for p in request["sources"]}):
            raise ValueError("OUTCOME_FACT_NOT_PROVEN")
    else:
        raise ValueError("EVIDENCE_SEMANTICS_UNSUPPORTED: " + request["type"])


def rebuild_verified(result, hints):
    """Replay source proofs in their original fact order, never trust a stored waiver."""
    if not hints:
        return collect_evidence(result)
    with source_view(result.root, result.git.target) as (root, _):
        sources = {p: (root / p).read_text(encoding="utf-8") for p in result.files}
    facts = collect_evidence(result, sources=sources)
    accepted, seen = [], set()
    pending = list(hints)
    while pending:
        batch = []
        first = pending[0]
        while pending and pending[0]["run_id"] == first["run_id"]:
            batch.append(pending.pop(0))
        before = digest(facts)
        for request in batch:
            validate_replayed_request(request, result, facts, sources, seen)
        accepted.extend(batch)
        facts = collect_evidence(result, hints=accepted, sources=sources)
        if digest(facts) == before:
            raise ValueError("EVIDENCE_REQUEST_NO_PROGRESS")
    return facts


def validate_replayed_request(request, result, facts, sources, seen):
    entry_id = request["entry_id"]
    if entry_id not in facts:
        raise ValueError("REQUEST_ENTRY_OUT_OF_SCOPE")
    current = facts[entry_id]
    errors = validate_evidence_request(request, {"run_id": request["run_id"],
        "source_fingerprint": result.source_fingerprint}, {"task_id": "entry:" + entry_id, "entry_id": entry_id}, current)
    if errors:
        raise ValueError("EVIDENCE_REPLAY_INVALID: " + "; ".join(errors))
    verify_semantics(request, current, sources)
    key = entry_id, request["target_id"]
    if key in seen:
        raise ValueError("EVIDENCE_REQUEST_NO_PROGRESS")
    seen.add(key)
