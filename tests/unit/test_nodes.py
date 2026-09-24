# RET-C2-080 - Unit tests: per-node success + error/edge paths.

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.anomaly_detect_node import AnomalyDetectNode
from src.nodes.post_process_node import ReportGenerateNode
from src.nodes.pre_process_node import TransactionParseNode
from src.schemas.state import from_json, to_json

STATUTORY_TX = {"register_id": "R1", "employee_id": "E1", "amount": 250000, "type": "sale", "hour": 14}
NORMAL_TX = {"register_id": "R1", "employee_id": "E1", "amount": 500, "type": "sale", "hour": 14}


class TestTransactionParseNode:
    def test_success(self):
        state = {"input_context": {"transactions": [NORMAL_TX], "baseline_days": 30}}
        r = TransactionParseNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["cold_start"] is False

    def test_empty_batch(self):
        state = {"input_context": {"transactions": [], "baseline_days": 30}}
        assert TransactionParseNode().execute(state)["status"] == AgentStatus.ERROR

    def test_malformed_batch(self):
        state = {"input_context": {"transactions": [{"foo": "bar"}], "baseline_days": 30}}
        assert TransactionParseNode().execute(state)["status"] == AgentStatus.ERROR

    def test_cold_start_flag(self):
        state = {"input_context": {"transactions": [NORMAL_TX], "baseline_days": 5}}
        r = TransactionParseNode().execute(state)
        assert r["cold_start"] is True

    def test_batch_from_json_user_input_when_input_context_empty(self):
        # Standalone HTTP entry carries only the `input` string.
        state = {"user_input": json.dumps({"transactions": [NORMAL_TX], "baseline_days": 30})}
        r = TransactionParseNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["cold_start"] is False

    def test_input_context_takes_precedence_over_user_input(self):
        state = {
            "input_context": {"transactions": [NORMAL_TX], "baseline_days": 5},
            "user_input": json.dumps({"transactions": [NORMAL_TX, NORMAL_TX], "baseline_days": 30}),
        }
        r = TransactionParseNode().execute(state)
        assert r["cold_start"] is True
        assert len(from_json(r["transactions_batch"], [])) == 1

    def test_free_text_user_input_is_still_rejected(self):
        state = {"user_input": "not a batch"}
        assert TransactionParseNode().execute(state)["status"] == AgentStatus.ERROR


class TestAnomalyDetectNode:
    def test_statutory_flag_not_suppressed_by_cold_start(self):
        state = {"user_input": json.dumps({"transactions": [STATUTORY_TX], "aggregates": {}, "cold_start": True})}
        r = AnomalyDetectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        findings = from_json(r["risk_ranked_findings"], [])
        assert any(f["statutory_flag"] for f in findings)

    def test_void_abuse_detected(self):
        agg = {"register:R1": {"void_rate": 0.5, "refund_rate": 0.0, "mean_amount": 500, "stdev_amount": 10}}
        tx = {**NORMAL_TX, "is_void": True}
        state = {"user_input": json.dumps({"transactions": [tx], "aggregates": agg, "cold_start": False})}
        r = AnomalyDetectNode().execute(state)
        findings = from_json(r["risk_ranked_findings"], [])
        assert any(f["pattern"] == "void_abuse" for f in findings)

    def test_cold_start_suppresses_baseline_alerts(self):
        agg = {"register:R1": {"void_rate": 0.9, "refund_rate": 0.9, "mean_amount": 500, "stdev_amount": 10}}
        tx = {**NORMAL_TX, "is_void": True, "is_refund": True}
        state = {"user_input": json.dumps({"transactions": [tx], "aggregates": agg, "cold_start": True})}
        r = AnomalyDetectNode().execute(state)
        findings = from_json(r["risk_ranked_findings"], [])
        assert not any(f["pattern"] in ("void_abuse", "fraudulent_refund") for f in findings)

    def test_missing_batch_errors(self):
        assert AnomalyDetectNode().execute({"user_input": "{}"})["status"] == AgentStatus.ERROR


class TestReportGenerateNode:
    def test_success_masks_employee_id(self):
        findings = [{"pattern": "statutory_threshold", "register_id": "R1", "employee_id": "E1", "score": 1.0, "alert_code": "CREDIT-HOUHU-001", "statutory_flag": True}]
        r = ReportGenerateNode().execute({"risk_ranked_findings": to_json(findings)})
        assert r["status"] == AgentStatus.SUCCESS
        report = from_json(r["anomaly_report"], {})
        assert report["findings"][0]["employee_id"].startswith("EMP-")
        assert report["findings"][0]["employee_id"] != "E1"

    def test_upstream_error_short_circuits(self):
        assert ReportGenerateNode().execute({"status": AgentStatus.ERROR})["status"] == AgentStatus.ERROR

    def test_extra_gate_blocks_unmasked_id(self):
        """S-3 hook: report claiming to contain the raw (unmasked) employee_id must fail."""
        findings = [{"employee_id": "E1", "statutory_flag": False}]
        leaked_report = {"findings": [{"employee_id": "E1"}], "statutory_flag_count": 0}
        state = {"risk_ranked_findings": to_json(findings), "anomaly_report": to_json(leaked_report)}
        out = ReportGenerateNode()._extra_security_gate_output(state)
        assert out["status"] == AgentStatus.ERROR

    def test_extra_gate_blocks_dropped_statutory_flag(self):
        findings = [{"employee_id": "E1", "statutory_flag": True}]
        report_missing_flag = {"findings": [{"employee_id": "EMP-abc12345"}], "statutory_flag_count": 0}
        state = {"risk_ranked_findings": to_json(findings), "anomaly_report": to_json(report_missing_flag)}
        out = ReportGenerateNode()._extra_security_gate_output(state)
        assert out["status"] == AgentStatus.ERROR

    def test_extra_gate_passthrough_when_consistent(self):
        findings = [{"employee_id": "E1", "statutory_flag": True}]
        report_ok = {"findings": [{"employee_id": "EMP-abc12345"}], "statutory_flag_count": 1}
        state = {"risk_ranked_findings": to_json(findings), "anomaly_report": to_json(report_ok)}
        assert ReportGenerateNode()._extra_security_gate_output(state) is state
