# RET-C2-080 - Integration test: full graph compile + invoke (Cat 2 outer + inner).

import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph

STATUTORY_TX = {"register_id": "R1", "employee_id": "E1", "amount": 250000, "type": "sale", "hour": 14}
NORMAL_TX = {"register_id": "R1", "employee_id": "E2", "amount": 500, "type": "sale", "hour": 14}


def _payload(result):
    out = result.get("output")
    if isinstance(out, str):
        return json.loads(out) if out else {}
    return out or {}


class TestAgentIntegration:
    def test_mixed_batch_statutory_flag_and_masking(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-1", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="ops")
        result = agent.invoke(
            "daily batch", ctx=ctx,
            input_context={"transactions": [STATUTORY_TX, NORMAL_TX], "baseline_days": 30},
        )
        assert result["status"] == "success"
        assert len(result.get("node_history", [])) >= 5
        payload = _payload(result)
        assert payload["statutory_flag_count"] >= 1
        for f in payload["findings"]:
            assert f["employee_id"].startswith("EMP-")
            assert f["employee_id"] not in ("E1", "E2")

    def test_cold_start_statutory_flag_persists(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-2", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="ops")
        result = agent.invoke(
            "daily batch", ctx=ctx,
            input_context={"transactions": [STATUTORY_TX], "baseline_days": 2},
        )
        payload = _payload(result)
        assert payload["statutory_flag_count"] == 1

    def test_json_batch_via_user_input_with_repeating_fraction_aggregates(self):
        # Standalone /invoke path: the batch arrives as the JSON `input` string, and
        # 1-of-3 voids yields void_rate 1/3 - unrounded, its digit run matched the
        # framework S-2 credit-card detector and corrupted the inner envelope.
        batch = {
            "transactions": [
                {"register_id": "R1", "employee_id": "E1", "amount": 3200, "type": "sale", "hour": 10},
                {"register_id": "R1", "employee_id": "E1", "amount": 4100, "type": "sale", "hour": 11},
                {"register_id": "R1", "employee_id": "E2", "amount": 1800, "type": "sale", "is_void": True, "hour": 13},
                STATUTORY_TX,
            ],
            "baseline_days": 30,
        }
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-4", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="ops")
        result = agent.invoke(json.dumps(batch), ctx=ctx)
        assert result["status"] == "success"
        payload = _payload(result)
        assert payload["statutory_flag_count"] == 1

    def test_empty_batch_error(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-3", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="ops")
        result = agent.invoke("daily batch", ctx=ctx, input_context={"transactions": [], "baseline_days": 30})
        assert result["status"] in ("error", "cancelled")
