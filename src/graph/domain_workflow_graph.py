"""AgentCore Platform v1.0 - RET-C2-080 inner domain workflow graph.

Cat 2 inner graph: fraud/anomaly detection over the normalized transaction batch.
Instantiated by AnomalyGraphNode.get_subgraph() in graph.py.

Pipeline (single inner step - the architect's two non-suppressible gates are
implemented as re-checks within TransactionParse/AnomalyDetect/ReportGenerate per
the node-consolidation design decision, not as separate graph nodes):
    START -> anomaly_detect -> END
"""

from typing import Any
from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.anomaly_detect_node import AnomalyDetectNode
from src.schemas.state import State


class AnomalyWorkflowGraph(BaseGraph):
    """Inner graph for the RET-C2-080 POS transaction anomaly-detection workflow."""

    @property
    def name(self) -> str:
        return "pos-anomaly-detection-workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config - detection is fully deterministic (rule + Z-score).
        pass

    def register_nodes(self) -> None:
        # No super() - BaseGraph.register_nodes() is abstract.
        self._nodes["anomaly_detect"] = AnomalyDetectNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "anomaly_detect")
        self._sg.add_edge("anomaly_detect", END)

    @staticmethod
    def _is_error(state: AgentState) -> bool:
        return state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value)

    def route(self, state: AgentState) -> str:
        return END

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "risk_ranked_findings": state.get("risk_ranked_findings"),
            "output": state.get("risk_ranked_findings"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
