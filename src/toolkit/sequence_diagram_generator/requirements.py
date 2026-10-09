"""Source-segment reconciliation; no similarity-based implementation claims."""
from .models import RequirementReport, RuleResult, ValidationReport
from .validation import target_evidence


class RequirementMapper:
    def evaluate(self, requirements, links, model, intent, excluded_segments=(), proposed_steps=(), proposed_controls=()):
        snapshot, items = requirements
        candidates = {s.segment_id for s in snapshot.segments} if snapshot else set()
        evidence = {e.evidence_id for s in model.scopes for e in s.evidence}
        targets = {s.step_id for scope in model.scopes for s in scope.steps}
        targets.update(c.control_id for scope in model.scopes for c in scope.controls)
        targets.update(e for scope in model.scopes for c in scope.controls for e in c.exit_ids)
        targets.update(o.operation_id for scope in model.scopes for o in scope.external)
        targets.update(s.symbol_id for scope in model.scopes for s in scope.symbols)
        bindings = target_evidence(model.scopes)
        code_targets, code_evidence = set(targets), set(evidence)
        items_by_id = {item.requirement_id: item for item in items}
        proposal_requirements = {}
        for proposed in (*proposed_steps, *proposed_controls):
            identifier = getattr(proposed, "step_id", None) or proposed.control_id
            proofs = {segment for rid in proposed.requirement_ids if rid in items_by_id for segment in items_by_id[rid].segment_ids}
            for target in (identifier, *getattr(proposed, "exit_ids", ())):
                targets.add(target)
                bindings[target] = proofs
                proposal_requirements[target] = set(proposed.requirement_ids)
        evidence.update(candidates)
        processed, rules = set(), []
        identifiers = [item.requirement_id for item in items]
        rules.append(RuleResult("requirement.unique_ids", len(set(identifiers)) == len(identifiers), "unique R IDs"))
        by_id = {link.requirement_id: link for link in links}
        rules.append(RuleResult("requirement.unique_links", len(by_id) == len(links) and set(by_id) <= set(identifiers), "one many-target mapping per requirement"))
        critical = any(g.critical for s in model.scopes for g in s.gaps)
        implemented = True
        for item in items:
            refs = set(item.segment_ids)
            rules.append(RuleResult("requirement.source", bool(refs) and refs <= candidates and bool(item.text.strip()), item.requirement_id))
            processed.update(refs)
            link = by_id.get(item.requirement_id)
            if link:
                proofs = set(link.evidence_ids)
                rules.append(RuleResult("requirement.targets", bool(link.target_ids) and set(link.target_ids) <= targets and proofs <= evidence
                                        and all(proofs & bindings.get(target, set()) for target in link.target_ids)
                                        and proofs <= set().union(*(bindings.get(target, set()) for target in link.target_ids))
                                        and all(item.requirement_id in proposal_requirements[target] for target in link.target_ids if target in proposal_requirements), item.requirement_id))
            if item.status == "implemented":
                rules.append(RuleResult("requirement.implemented_evidence", bool(model.scopes) and bool(link) and bool(link.evidence_ids)
                                        and set(link.target_ids) <= code_targets and set(link.evidence_ids) <= code_evidence
                                        and not critical and item.implementation_assessment == "checked", item.requirement_id))
            elif item.status == "partially_implemented":
                rules.append(RuleResult("requirement.partial_evidence", bool(link) and bool(set(link.target_ids) & code_targets)
                                        and bool(set(link.evidence_ids) & code_evidence) and bool(item.difference.strip()), item.requirement_id))
                implemented = False
            elif item.status == "requirement_only":
                rules.append(RuleResult("requirement.absence_boundary", bool(item.difference.strip()) and (item.implementation_assessment == "not_evaluated" or item.implementation_assessment == "checked_not_found" and bool(model.scopes) and not critical), item.requirement_id))
                implemented = False
            elif item.status == "conflict":
                rules.append(RuleResult("requirement.conflict", bool(link) and bool(set(link.target_ids) & code_targets)
                                        and bool(set(link.evidence_ids) & code_evidence) and bool(item.difference.strip()) and intent == "proposal", item.requirement_id))
                implemented = False
            elif item.status == "unresolved":
                rules.append(RuleResult("requirement.unresolved", False, item.unresolved_reason or item.requirement_id))
                implemented = False
            elif item.status == "not_applicable":
                rules.append(RuleResult("requirement.not_applicable", bool(item.difference.strip()), item.requirement_id))
        exclusions = dict(excluded_segments)
        rules.append(RuleResult("requirement.exclusions", len(exclusions) == len(excluded_segments) and set(exclusions) <= candidates and not set(exclusions) & processed and all(reason.strip() for reason in exclusions.values()), "documented exclusions"))
        processed.update(exclusions)
        rules.append(RuleResult("requirement.segment_reconciliation", processed == candidates, f"{len(processed)}/{len(candidates)} source segments handled"))
        if intent == "implementation":
            rules.append(RuleResult("requirement.implementation_gate", implemented, "all in-scope requirements implemented"))
        consistency = "not_evaluated" if not model.scopes else "passed" if implemented and not critical and all(rule.passed for rule in rules) else "failed"
        return RequirementReport(tuple(items), tuple(links), len(candidates), len(processed), consistency, ValidationReport(tuple(rules)))
