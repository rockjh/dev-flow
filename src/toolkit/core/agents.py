"""Consistency checks for session-attested agents; never launches agents.

JSON can bind evidence; only the coordinating session can attest tool calls.
"""
from datetime import datetime


def parse_timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamp requires a timezone")
    return result


def validate_active_observations(observations: list, bindings: dict[str, str]) -> list[str]:
    """Validate snapshots explicitly observing distinct children running together.

    Dispatch/receive bounds cannot prove overlap. References are host-attested,
    not authenticated by this local consistency check.
    """
    errors = []
    if not isinstance(observations, list):
        return ["ACTIVE_OBSERVATIONS_INVALID"]
    for observation in observations:
        if not isinstance(observation, dict):
            errors.append("ACTIVE_OBSERVATION_INVALID")
            continue
        ids = observation.get("active_task_ids")
        if (not isinstance(ids, list) or not all(isinstance(item, str) for item in ids)
                or len(ids) < 2 or len(ids) != len(set(ids))
                or any(item not in bindings for item in ids)
                or len({bindings.get(item) for item in ids}) != len(ids)
                or observation.get("time_source") not in {"host", "coordinator_observed"}
                or not isinstance(observation.get("tool_reference"), str)
                or not observation["tool_reference"].strip()):
            errors.append("ACTIVE_OBSERVATION_INVALID")
        try:
            parse_timestamp(observation.get("observed_at"))
        except (TypeError, ValueError):
            errors.append("ACTIVE_OBSERVATION_TIME_INVALID")
    return errors
