# RET-C2-080 — Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `POSTransactionAnomalyGraph` (module `src.graph`, alias `Graph`) — inherits `AgentBaseGraph` (L1 direct)
- **L1 Base Type**: `AgentBaseGraph` (L1 direct inheritance — no L2 base class)
- **Category**: Cat 2 — batch POS-transaction fraud-detection pipeline
- **Pattern**: DocGenerationAgent; Cat 2 composition = outer `AgentBaseGraph` + `GraphNode`(main) + inner `BaseGraph`
- **Industry**: RET
- **Trust level (agent default)**: `VERIFIED_EXTERNAL`

## Cat 2 Composition

```
OUTER (AgentBaseGraph - src/graph/graph.py):
  initialize -> pre_process(TransactionParse) -> main(AnomalyGraphNode) -> post_process(ReportGenerate) -> finalize

INNER (BaseGraph - src/graph/domain_workflow_graph.py):
  START -> anomaly_detect -> END
```

`AnomalyGraphNode` lives in `graph.py`, not `src/nodes/` (PB-6 safety). Per the
node-consolidation design decision, the architect's two non-suppressible gates (CreditHouhuThresholdGate,
EmployeeIDMaskingGate) are NOT separate graph nodes — they run as unconditional checks inside
`AnomalyDetectNode` and `ReportGenerateNode` respectively, each re-verified at the framework S-hook
boundary.

## State Schema (`src/schemas/state.py`)

`class State(AgentState)` — flat, all agent-specific fields `NotRequired`. Fields:
`transactions_batch`, `aggregates`, `cold_start`, `findings`, `risk_ranked_findings`,
`anomaly_report`.

## Nodes

| Slot / step | Node | Responsibility |
|---|---|---|
| outer pre_process | `TransactionParseNode` | Parse/normalize batch; per-register/per-employee aggregates; cold-start guard; S-1 VERIFIED_EXTERNAL + S-2 empty/malformed rejection |
| inner | `AnomalyDetectNode` | Rule + Z-score detection (5 patterns); **CreditHouhuThresholdGate** (非suppressible 割賦販売法 threshold) runs unconditionally regardless of cold_start; risk-rank |
| outer post_process | `ReportGenerateNode` | **EmployeeIDMaskingGate** (S-3 non-suppressible): mask employee IDs, re-verify no unmasked ID/dropped statutory flag at the S-3 hook; compile report |

## Non-Suppressible Gates (critical invariant)

1. **CreditHouhuThresholdGate** (`detect_anomalies()` in `service.py`): runs on every transaction
   before the `cold_start` early-continue — the statutory check is never gated by cold-start
   suppression or any other config.
2. **EmployeeIDMaskingGate** (`ReportGenerateNode`): masking happens in `execute()`; the S-3 hook
   (`_extra_security_gate_output`) independently re-derives whether any raw ID leaked or any
   statutory flag was dropped, and fails loudly rather than trusting the execute() output.

## Security

- **S-1**: `required_trust_level = VERIFIED_EXTERNAL` (standard business operation).
- **S-2**: empty/malformed batch → `status=ERROR` at `TransactionParseNode`.
- **S-3**: employee-ID masking + statutory-flag-count non-suppressible re-check.
- **S-4**: `emit_trace_event()` in every node's `execute()`; GraphNode wrapper emits via `extract_input`/`merge_output`.
- **S-5**: no credentials in source; fully deterministic detection (no external secrets required).

## Dependencies

Fully deterministic-core (rule + Z-score) — no external LLM/KB dependency. `dependencies = []`
(framework from wheel).
