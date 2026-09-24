"""AgentCore Platform v1.0 - RET-C2-080 TransactionParseNode (outer pre_process slot).

Step 1: parse/normalize the daily POS transaction batch, compute per-register/
per-employee aggregates, and apply the cold-start baseline guard. Empty/malformed
batch is an S-2 input-validation error. Serializes to validated_input (JSON string)
so the inner domain workflow graph can reconstruct it.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json
from src.services.service import compute_aggregates, is_cold_start, parse_transactions


def _batch_from_user_input(raw: Any) -> dict[str, Any] | None:
    """Parse a JSON batch envelope ({"transactions": [...], "baseline_days": N}) from user_input."""
    if not isinstance(raw, str) or not raw.strip().startswith("{"):
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


class TransactionParseNode(FunctionNode):
    """Parse + normalize the batch, compute aggregates, apply the cold-start guard."""

    # S-1: explicit by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        input_context = state.get("input_context") or {}  # read-only [C1]
        if not input_context.get("transactions"):
            # Standalone HTTP entry (src/api/server.py) carries only the `input`
            # string, so accept the same batch envelope as a JSON user_input.
            # input_context stays authoritative whenever it carries a batch.
            input_context = _batch_from_user_input(state.get("user_input", "")) or input_context
        raw_batch = input_context.get("transactions", [])
        baseline_days = int(input_context.get("baseline_days", 0))

        emit_trace_event(
            "transaction_batch_received",
            {
                "batch_size": len(raw_batch) if isinstance(raw_batch, list) else 0,
                "correlation_id": state.get("correlation_id", ""),
            },
            state,
        )

        transactions = parse_transactions(raw_batch)
        if not transactions:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["TransactionParseNode: batch is empty or malformed - S-2 rejection"],
            }

        aggregates = compute_aggregates(transactions)
        cold_start = is_cold_start(baseline_days)
        if cold_start:
            emit_trace_event("cold_start_warmup_notice", {"baseline_days": baseline_days}, state)

        return {
            "transactions_batch": to_json(transactions),
            "aggregates": to_json(aggregates),
            "cold_start": cold_start,
            "validated_input": json.dumps(
                {"transactions": transactions, "aggregates": aggregates, "cold_start": cold_start},
                ensure_ascii=False,
            ),
            "status": AgentStatus.SUCCESS.value,
        }
