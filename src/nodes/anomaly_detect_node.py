"""AgentCore Platform v1.0 - RET-C2-080 AnomalyDetectNode (inner step)."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json
from src.services.service import detect_anomalies, rank_findings


class AnomalyDetectNode(FunctionNode):
    """Rule + Z-score detection across fraud patterns + the non-suppressible statutory gate.

    CreditHouhuThresholdGate (the 割賦販売法 statutory-threshold check) runs
    unconditionally inside detect_anomalies() regardless of the cold_start flag -
    it is never suppressed by any config or upstream state.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            parsed = None
        if not isinstance(parsed, dict) or not parsed.get("transactions"):
            return {"status": AgentStatus.ERROR.value, "error_log": ["AnomalyDetectNode: missing transactions batch"]}

        transactions = parsed["transactions"]
        aggregates = parsed.get("aggregates", {})
        cold_start = bool(parsed.get("cold_start", False))

        findings = detect_anomalies(transactions, aggregates, cold_start)
        ranked = rank_findings(findings)

        emit_trace_event(
            "anomalies_detected",
            {
                "finding_count": len(ranked),
                "statutory_count": sum(1 for f in ranked if f.get("statutory_flag")),
                "correlation_id": state.get("correlation_id", ""),
            },
            state,
        )
        return {"risk_ranked_findings": to_json(ranked), "status": AgentStatus.SUCCESS.value}
