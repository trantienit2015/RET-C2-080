"""AgentCore Platform v1.0 - RET-C2-080 outer graph (Cat 2).

Cat 2: outer AgentBaseGraph with the fixed 5-node backbone. Domain complexity is
encapsulated in AnomalyGraphNode (the `main` slot), which wraps the inner
AnomalyWorkflowGraph. Do NOT override add_edges().

Backbone: initialize -> pre_process(TransactionParse) -> main(GraphNode) -> post_process(ReportGenerate) -> finalize

AnomalyGraphNode lives here (not under src/nodes/) - the PB-6 invoke-order test
only discovers BaseNode subclasses under src/nodes/, and a GraphNode's __call__
intentionally skips the standard S-2/S-4/S-3 lifecycle (gating is delegated to the
inner subgraph).
"""

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.post_process_node import ReportGenerateNode
from src.nodes.pre_process_node import TransactionParseNode
from src.schemas.state import State


class AnomalyGraphNode(GraphNode):
    """Wraps the inner POS transaction anomaly-detection workflow (Cat 2 composition)."""

    # S-1: outer main-slot GraphNode is the first boundary that receives caller
    # input - declared explicitly, matching config/agent.yaml's agent-level default.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    # "propagate": re-raise inner errors as SubgraphError (fail fast - default).
    error_strategy: ClassVar[str] = "propagate"
    # No HITL in this template.
    propagate_hitl: ClassVar[bool] = False

    def get_subgraph(self) -> Any:
        from src.graph.domain_workflow_graph import AnomalyWorkflowGraph

        sg = AnomalyWorkflowGraph(config=self._parent_config())
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        emit_trace_event("anomaly_workflow_dispatched", {"correlation_id": state.get("correlation_id", "")}, state)
        return cast(str, state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "anomaly_workflow_completed",
            {"correlation_id": state.get("correlation_id", ""), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            "risk_ranked_findings": sub_result.get("risk_ranked_findings"),
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {}


class POSTransactionAnomalyGraph(AgentBaseGraph):
    """RET-C2-080 - Retail POS Transaction Anomaly & Fraud Detection Agent (Cat 2)."""

    @property
    def name(self) -> str:
        return "ret-c2-080"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        self._nodes["pre_process"] = TransactionParseNode()
        self._nodes["main"] = AnomalyGraphNode()
        self._nodes["post_process"] = ReportGenerateNode()

    # add_edges() is NOT overridden - backbone wiring belongs to the framework.


# Alias for agent.yaml module:"src.graph" resolution (AgentRegistry / api/server.py).
Graph = POSTransactionAnomalyGraph
