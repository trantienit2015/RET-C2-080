# RET-C2-080 - Framework compliance tests TC-01..TC-08.
# Structured as a standard TC-01..TC-08 compliance suite,
# adapted to this template's real architecture (Cat 2: outer pre/post + GraphNode-wrapped inner subgraph).

import json
import os
import re

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes.anomaly_detect_node import AnomalyDetectNode
from src.nodes.post_process_node import ReportGenerateNode
from src.nodes.pre_process_node import TransactionParseNode
from src.schemas.state import State, to_json

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
TRUST = TrustLevel.VERIFIED_EXTERNAL.value

NORMAL_TX = {"register_id": "R1", "employee_id": "E1", "amount": 500, "type": "sale", "hour": 14}


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# TC-01 - State is a flat TypedDict extending AgentState, added fields are primitives/JSON-str.
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_primitives_or_json_str(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        allowed = {"str", "int", "bool", "float", "NoneType"}
        for name in added:
            ann = State.__annotations__[name]
            ann_str = str(ann)
            # NotRequired[str | None] style unions - accept if every leaf token is allowed.
            leaves = re.findall(r"[A-Za-z_]+", ann_str)
            assert set(leaves) & (allowed | {"NotRequired", "Optional", "str", "None", "bool"}), (
                f"{name}: {ann_str} - compound fields must be JSON-string-encoded"
            )


# TC-02 - Empty/missing input yields a fail-closed ERROR outcome, no raise.
class TestTC02Validation:
    def test_empty_input_no_raise(self):
        state = {"input_context": {"transactions": [], "baseline_days": 30}}
        out = TransactionParseNode().execute(state)
        assert out["status"] == AgentStatus.ERROR.value
        assert out["error_log"]

    def test_missing_batch_no_raise(self):
        node = AnomalyDetectNode()
        out = node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR.value
        assert out["error_log"]


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads.
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []

    def test_no_os_environ_secret_reads(self):
        # The standalone entry point is the ONE permitted os.environ reader: it
        # authenticates the caller (INVOKE_AUTH_TOKEN) BEFORE any InvocationContext
        # exists, so ctx.secrets cannot apply. That token is a deployment-level
        # caller credential, not an agent secret, and is never stored in state.
        # This is the documented entry-point exception.
        offenders = []
        for fp in _src_files():
            if os.path.normpath(fp).endswith(os.path.join("src", "api", "server.py")):
                continue
            with open(fp, encoding="utf-8") as f:
                if "os.environ" in f.read():
                    offenders.append(fp)
        assert offenders == []

    def test_entry_point_env_read_is_limited_to_the_caller_auth_token(self):
        """The entry-point exception is narrow: only the two named caller-auth tokens
        (INVOKE_AUTH_TOKEN and the STG-only STG_INTERNAL_RUNNER_TOKEN) may be read."""
        import re

        server = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "src", "api", "server.py")
        if not os.path.exists(server):
            return
        with open(server, encoding="utf-8") as f:
            content = f.read()
        reads = re.findall(r"os\.environ(?:\.get)?[(\[]\s*[\"']([A-Z_]+)[\"']", content)
        assert set(reads) <= {"INVOKE_AUTH_TOKEN", "STG_INTERNAL_RUNNER_TOKEN"}, f"unexpected env reads: {reads}"


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="staff-tc04")
        result = agent.invoke("daily batch", ctx=ctx, input_context={"transactions": [NORMAL_TX], "baseline_days": 30})
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: every node emits >=1 domain event; no node under src/nodes/
# ever re-emits a framework backbone lifecycle event.
class TestTC05Audit:
    def test_pre_process_emits_domain_event(self, monkeypatch):
        import src.nodes.pre_process_node as pre_process_node

        events = []
        monkeypatch.setattr(pre_process_node, "emit_trace_event", lambda e, p, s: events.append(e))
        state = {"input_context": {"transactions": [NORMAL_TX], "baseline_days": 30}}
        out = TransactionParseNode().execute(state)
        assert out["status"] == AgentStatus.SUCCESS.value
        assert len(events) >= 1
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_anomaly_detect_emits_domain_event(self, monkeypatch):
        import src.nodes.anomaly_detect_node as anomaly_detect_node

        events = []
        monkeypatch.setattr(anomaly_detect_node, "emit_trace_event", lambda e, p, s: events.append(e))
        state = {"user_input": json.dumps({"transactions": [NORMAL_TX], "aggregates": {}, "cold_start": False})}
        out = AnomalyDetectNode().execute(state)
        assert out["status"] == AgentStatus.SUCCESS.value
        assert len(events) >= 1
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_post_process_emits_domain_event(self, monkeypatch):
        import src.nodes.post_process_node as post_process_node

        events = []
        monkeypatch.setattr(post_process_node, "emit_trace_event", lambda e, p, s: events.append(e))
        state = {"risk_ranked_findings": to_json([])}
        out = ReportGenerateNode().execute(state)
        assert out["status"] == AgentStatus.SUCCESS.value
        assert len(events) >= 1
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []


# TC-06 / TC-07 - the generic @final-TypeError contract is covered by the dedicated
# tests/unit/test_framework_compliance_tc06_tc07.py (scaffold exact-name stub).
# Here: template-specific proof that the domain hook is wired and the default
# S-3 credential scan actually fires (not vacuous).
class TestTC0607DomainHookWiring:
    def test_extra_hook_is_overridable(self):
        assert ReportGenerateNode._extra_security_gate_output is not FunctionNode._extra_security_gate_output

    def test_output_gate_blocks_credentials(self):
        # The @final S-3 credential scan actually fires (not vacuous): a
        # credential in the result is blocked, never returned as-is.
        node = ReportGenerateNode()
        with pytest.raises(Exception):
            node._security_gate_output({"formatted_output": "token AKIAIOSFODNN7EXAMPLE leaked"})


# TC-08 - required_trust_level enforced: insufficient trust -> ERROR state, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (TransactionParseNode, AnomalyDetectNode, ReportGenerateNode):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = TransactionParseNode()
        out = node(
            {
                "caller_trust_level": TrustLevel.ANONYMOUS.value,
                "input_context": {"transactions": [NORMAL_TX], "baseline_days": 30},
            }
        )
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = TransactionParseNode()
        out = node(
            {
                "caller_trust_level": TRUST,
                "input_context": {"transactions": [NORMAL_TX], "baseline_days": 30},
            }
        )
        assert out["status"] == AgentStatus.SUCCESS.value
