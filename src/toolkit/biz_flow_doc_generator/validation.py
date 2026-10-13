"""Strict analysis binding, semantic request gates, and canonical asset checks."""
from ..core.schema import BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA, BIZ_FLOW_EVIDENCE_REQUEST_SCHEMA, validate_schema
from .evidence import digest, FACT_ARRAYS


def validate_no_critical_unresolved(facts):
    return [f'CRITICAL_UNRESOLVED: {g["finding_id"]}:{g["code"]}' for g in facts["gaps"] if g["critical"]]


def validate_entry_analysis(value, facts):
    errors = validate_schema(BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA, value)
    if errors:
        return errors
    for key in ("entry_id", "source_fingerprint"):
        if value[key] != facts[key]:
            errors.append("ENTRY_EVIDENCE_MISMATCH: " + key)
    if value["facts_hash"] != digest(facts):
        errors.append("FACTS_HASH_MISMATCH")
    errors.extend(validate_resolutions(value.get("resolutions", []), facts))
    errors.extend(validate_no_critical_unresolved(facts))
    if not facts["coverage"]["complete"] or not facts["outcomes"]:
        errors.append("BEHAVIOR_COVERAGE_INCOMPLETE")
    targets = {f["fact_id"]: f["evidence_refs"] for array in FACT_ARRAYS for f in facts[array]}
    proof_ids = {s["evidence_id"] for s in facts["sources"]}
    for participant in facts["participants"]:
        targets[participant["participant_id"]] = participant["evidence_refs"]
    known = proof_ids | set(targets)
    annotations = value["annotations"]
    if len({a["target_id"] for a in annotations}) != len(annotations) or {a["target_id"] for a in annotations} != set(targets):
        errors.append("ANNOTATION_COVERAGE_MISMATCH")
    for item in [*annotations, *value["review"].values()]:
        refs = set(item["evidence_refs"])
        if not refs <= known:
            errors.append("ANALYSIS_REFERENCE_OUT_OF_SCOPE")
        if "target_id" in item:
            target = item["target_id"]
            if target in targets and not refs.intersection({target, *targets[target]}):
                errors.append("ANNOTATION_EVIDENCE_UNRELATED: " + target)
        if item["text"].strip() in {"成功", "业务对象", "数据库", "处理数据", "代码中未确认", "待确认"}:
            errors.append("ANALYSIS_PLACEHOLDER")
    return sorted(set(errors))


def validate_resolutions(resolutions, facts):
    """A resolution explains an adapter-proven fact; it cannot waive unknown IO."""
    from .supplement import fact_path
    items = {f["fact_id"]: f for array in FACT_ARRAYS for f in facts[array]}
    proofs = {p["evidence_id"]: p for p in facts["sources"]}
    seen, errors = set(), []
    for value in resolutions:
        code, _, target_id = value["finding"].partition("|")
        target = items.get(target_id)
        if target is None or value["finding"] in seen:
            errors.append("RESOLUTION_FINDING_INVALID: " + value["finding"])
            continue
        seen.add(value["finding"])
        if (value["path"] != fact_path(facts, target_id)
                or value["controls"] != [facts["entry_id"], *target["conditions"]]
                or any(proofs.get(p["evidence_id"]) != p for p in value["evidence"])
                or not set(target["evidence_refs"]) <= {p["evidence_id"] for p in value["evidence"]}
                or value["unknowns"]):
            errors.append("RESOLUTION_EVIDENCE_INVALID: " + value["finding"])
        expected = None
        if target["type"] == "normal_completion" and target["phase"] == "entry":
            expected = ("OUTCOME_UNRESOLVED", "normal_completion")
        elif target["type"] in {"short_circuit", "ternary_expression"}:
            expected = ("BRANCH_LINE_UNRESOLVED", "non_business_decision")
        elif target["type"] in {"pure_or_memory", "pure_path_construction"} or any(
                effect["type"] == "task_submission" and effect["details"].get("task_call") == target_id for effect in facts["effects"]):
            expected = ("PERSISTENCE_OBJECT_UNRESOLVED", "non_persistence")
        if expected != (code, value["classification"]):
            errors.append("RESOLUTION_NOT_PROVEN: " + value["finding"])
    return errors


def validate_evidence_request(request, manifest, task, facts):
    errors = validate_schema(BIZ_FLOW_EVIDENCE_REQUEST_SCHEMA, request)
    if errors:
        return errors
    expected = {"run_id": manifest["run_id"], "task_id": task["task_id"], "entry_id": task["entry_id"],
                "source_fingerprint": manifest["source_fingerprint"], "facts_hash": digest(facts)}
    for key, value in expected.items():
        if request[key] != value:
            errors.append("REQUEST_BINDING_MISMATCH: " + key)
    gaps = {g["finding_id"]: g for g in facts["gaps"]}
    fact_ids = {f["fact_id"] for array in FACT_ARRAYS for f in facts[array]}
    sources = {s["evidence_id"]: s for s in facts["sources"]}
    finding = gaps.get(request["finding_id"])
    if request["finding_id"] is not None and finding is None:
        errors.append("REQUEST_FINDING_UNKNOWN")
    if request["target_id"] not in gaps and request["target_id"] not in fact_ids:
        errors.append("REQUEST_TARGET_UNKNOWN")
    if any(sources.get(p["evidence_id"]) != p for p in request["sources"]):
        errors.append("REQUEST_SOURCE_PROOF_MISMATCH")
    if not set(request["path"]) <= fact_ids:
        errors.append("REQUEST_PATH_UNREACHABLE")
    if finding:
        target = next((f for array in FACT_ARRAYS for f in facts[array] if f["fact_id"] == request["target_id"]), None)
        if target is None or (finding["target_id"] != target["context_id"] and target["fact_id"] not in finding["controls"]):
            errors.append("REQUEST_FINDING_UNRELATED")
        if target and request["controls"] != target["conditions"]:
            errors.append("REQUEST_CONTROLS_MISMATCH")
    # A source location proves identity, not a semantic claim. Every supported
    # request must change canonical output through its registered source adapter.
    return sorted(set(errors))


def validate_markdown_structure(markdown, analyses, facts):
    from .documents import render_entry
    import re
    if "<!-- devflow:entry-directory -->" in markdown:
        return ["MODULE_INVENTORY_BELONGS_IN_OVERVIEW"]
    matches = list(re.finditer(r"^<!-- biz-flow-entry: (.+) -->\s*$", markdown, re.M))
    if len(matches) != len(analyses) or {m[1] for m in matches} != set(analyses):
        return ["MARKDOWN_ENTRY_OWNERSHIP_MISMATCH"]
    errors = []
    for i, match in enumerate(matches):
        entry_id = match[1]
        section = markdown[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(markdown)].strip()
        if section != render_entry(facts[entry_id], analyses[entry_id], validate_diagram=False).strip():
            errors.append("CANONICAL_FLOW_ASSET_MISMATCH: " + entry_id)
    return errors
