"""AgentCore Platform v1.0 - RET-C2-080 ReportGenerateNode (outer post_process slot).

Step 3: EmployeeIDMaskingGate (S-3 non-suppressible). Employee IDs are masked
(hashed, 個人情報保護法) and this is re-verified unconditionally at the S-3 hook -
neither the masking nor the statutory-flag-count check trusts a prior state.
Any unmasked ID or dropped statutory-threshold flag => drop output, return a safe
error, log to audit (never silent).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import build_anomaly_report, dropped_statutory_flag, has_unmasked_employee_id


class ReportGenerateNode(FunctionNode):
    """S-3 EmployeeIDMaskingGate + risk-ranked daily anomaly report assembly."""

    # S-1: explicit by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return {"status": AgentStatus.ERROR.value}

        ranked = from_json(state.get("risk_ranked_findings"), [])
        report = build_anomaly_report(ranked)

        emit_trace_event(
            "anomaly_report_generated",
            {
                "total_findings": report["total_findings"],
                "statutory_flag_count": report["statutory_flag_count"],
                "correlation_id": state.get("correlation_id", ""),
            },
            state,
        )

        return {
            "anomaly_report": to_json(report),
            "formatted_output": report,
            "result": to_json(report),
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 domain hook: non-suppressible re-check of employee-ID masking + statutory-flag count."""
        report = from_json(state.get("anomaly_report"), {})
        if not report:
            return state

        ranked = from_json(state.get("risk_ranked_findings"), [])
        raw_employee_ids = [f.get("employee_id", "") for f in ranked]
        expected_statutory_count = sum(1 for f in ranked if f.get("statutory_flag"))

        if has_unmasked_employee_id(report, raw_employee_ids):
            emit_trace_event("output_gate_unmasked_employee_id_blocked", {}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["S-3 gate: unmasked employee ID detected in report - blocked"],
            }
        if dropped_statutory_flag(report, expected_statutory_count):
            emit_trace_event("output_gate_dropped_statutory_flag_blocked", {}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["S-3 gate: statutory-threshold flag was dropped from the report - blocked"],
            }
        return state
