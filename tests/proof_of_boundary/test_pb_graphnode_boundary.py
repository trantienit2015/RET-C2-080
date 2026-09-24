# PB-6-bis: GraphNode boundary test (proactive review-and-fix audit).
# PB-6 (test_pb_invoke_order.py) only discovers BaseNode subclasses under src/nodes/.
# AnomalyGraphNode lives in src/graph/graph.py (correct Cat 2 placement - keeps the
# self-discovery probe from pulling the inner subgraph), but that placement does not
# exempt it from boundary testing: it is the outer main-slot GraphNode, the first
# security boundary that receives caller input. This file probes it directly.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import AnomalyGraphNode

NORMAL_TX = {"register_id": "R1", "employee_id": "E1", "amount": 500, "type": "sale", "hour": 14}


class TestGraphNodeS1TrustGate:
    def test_insufficient_trust_denied_before_execute(self):
        node = AnomalyGraphNode()
        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
            "validated_input": json.dumps({"transactions": [NORMAL_TX], "aggregates": {}, "cold_start": False}),
        }
        out = node(state)
        assert out["status"] == AgentStatus.ERROR.value
        assert any("S-1 trust gate denied" in e for e in out.get("error_log", []))

    def test_sufficient_trust_dispatches_to_subgraph(self):
        node = AnomalyGraphNode()
        state = {
            "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
            "validated_input": json.dumps({"transactions": [NORMAL_TX], "aggregates": {}, "cold_start": False}),
            # InvocationContext.from_state() indexes these directly - required for
            # a direct node() call outside the full graph (InitializeNode normally sets them).
            "correlation_id": "corr-pb6bis",
            "session_id": "sess-pb6bis",
            "thread_id": "thread-pb6bis",
            "trace_id": "trace-pb6bis",
        }
        out = node(state)
        assert out["status"] == AgentStatus.SUCCESS.value


class TestGraphNodeBoundaryMapping:
    def test_extract_input_returns_only_validated_input(self):
        node = AnomalyGraphNode()
        state = {
            "validated_input": "the-real-payload",
            "user_input": "raw-caller-text-not-expected-here",
            "some_unrelated_field": "must-not-leak",
        }
        extracted = node.extract_input(state)
        assert extracted == "the-real-payload"

    def test_extract_input_falls_back_to_user_input(self):
        node = AnomalyGraphNode()
        state = {"user_input": "fallback-payload"}
        assert node.extract_input(state) == "fallback-payload"

    def test_merge_output_maps_fields_explicitly_no_raw_passthrough(self):
        # criterion #9: merge_output must map fields explicitly, not pass through the
        # raw subgraph result dict wholesale.
        node = AnomalyGraphNode()
        state = {"correlation_id": "corr-1"}
        sub_result = {
            "risk_ranked_findings": '[{"pattern": "void_abuse"}]',
            "output": '{"total_findings": 1}',
            "status": AgentStatus.SUCCESS.value,
            "node_history": ["AnomalyDetectNode"],  # internal subgraph detail - must NOT leak
            "execution_time": {"AnomalyDetectNode": 0.01},  # internal subgraph detail - must NOT leak
        }
        merged = node.merge_output(state, sub_result)
        assert merged == {
            "risk_ranked_findings": sub_result["risk_ranked_findings"],
            "result": sub_result["output"],
            "status": sub_result["status"],
        }
        assert "node_history" not in merged
        assert "execution_time" not in merged


class TestGraphNodeDelegatesGatingToInnerSubgraph:
    def test_inner_entry_node_declares_its_own_trust_level(self):
        # Design note (not a PB-6 workaround): GraphNode.__call__() intentionally skips
        # the standard S-2/S-4/S-3 lifecycle (see framework/nodes/graph_node.py) -
        # gating for the anomaly-detection payload is delegated to the inner subgraph's
        # own entry node, which is a regular FunctionNode covered by PB-6.
        from src.nodes.anomaly_detect_node import AnomalyDetectNode

        assert AnomalyDetectNode.required_trust_level in (
            TrustLevel.ANONYMOUS,
            TrustLevel.VERIFIED_EXTERNAL,
            TrustLevel.INTERNAL,
        )
