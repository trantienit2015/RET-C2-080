"""AgentCore Platform v1.0 - RET-C2-080 state schema."""

# ADR-005: State must be a flat TypedDict - never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects (and nested
# dict/list containers) are not msgpack-safe. Extend AgentState with agent-specific
# fields only. Nested list[dict]/dict fields are stored as JSON strings and
# (de)serialized at the node boundary via to_json/from_json below. Do NOT add
# credentials, secrets, or Pydantic models.

from __future__ import annotations

import json
from typing import Any, NotRequired, Optional

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> Optional[str]:
    """Serialize a list/dict State value to a compact JSON string (ADR-005, msgpack-safe)."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def from_json(value: Any, default: Any) -> Any:
    """Deserialize a JSON-string State value back to its list/dict form (tolerant)."""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# Type-check note: the wheel ships no py.typed, so mypy resolves AgentState to Any
# and reports every NotRequired below as valid-type. The fields are correct (the state
# contract requires NotRequired) -- the report is a packaging artifact, suppressed per field.
# Drop these ignores once the wheel ships py.typed.
class State(AgentState):
    """POS transaction anomaly & fraud detection state.

    Shared fields (user_input, validated_input, status, session_id, node_history,
    error_log, result, formatted_output, hitl_*, etc.) are inherited from AgentState.
    Only agent-specific, flat, JSON-serializable fields are declared below; all are
    NotRequired (written mid-pipeline - C8).
    """

    # JSON list[{register_id, employee_id, amount, type, timestamp, ...}] - normalized batch.
    transactions_batch: NotRequired[str | None]  # type: ignore[valid-type]
    # JSON dict{register_id/employee_id: {void_rate, refund_rate, off_hours_count}}.
    aggregates: NotRequired[str | None]  # type: ignore[valid-type]
    cold_start: NotRequired[bool]  # type: ignore[valid-type]  # true when baseline history is insufficient
    # JSON list[{pattern, register_id, employee_id, score, alert_code, statutory_flag}].
    findings: NotRequired[str | None]  # type: ignore[valid-type]
    risk_ranked_findings: NotRequired[str | None]  # type: ignore[valid-type]  # JSON list, sorted by risk score desc
    anomaly_report: NotRequired[str | None]  # type: ignore[valid-type]  # JSON final report with masked IDs
