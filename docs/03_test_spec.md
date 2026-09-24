# RET-C2-080 — Test Specification

## Test Strategy

Fully deterministic (rule + Z-score) — the full suite runs offline with no injected fakes needed.

## Unit Tests (`tests/unit/test_nodes.py`)

| Node | Cases |
|---|---|
| TransactionParseNode | success; empty/malformed batch→ERROR; cold-start flag set on insufficient baseline_days |
| AnomalyDetectNode | statutory threshold flagged even during cold_start (non-suppressible); void/refund/off-hours/card-structuring detection; missing batch→ERROR |
| ReportGenerateNode | success with masked employee IDs; upstream error short-circuit; `_extra_security_gate_output` blocks unmasked ID; blocks dropped statutory flag |

## Integration Tests (`tests/integration/test_graph.py`)

| ID | Test | Expected |
|---|---|---|
| I-1 | mixed batch (normal + statutory-threshold transaction) | SUCCESS; ≥5 nodes; statutory_flag_count ≥1; employee IDs masked (EMP- prefix, not raw) |
| I-2 | cold-start batch with statutory transaction | statutory flag still present despite cold_start |
| I-3 | empty batch | error/cancelled |

## Proof-of-Boundary Tests (`tests/proof_of_boundary/`)

| PB | File | Verifies |
|---|---|---|
| PB-2 | `test_state_safety.py` | state holds only JSON-serializable primitives |
| PB-4 | `test_import_isolation.py` | no agenticstar / mediator / other-agent imports |
| PB-6 | `test_pb_invoke_order.py` | S-1 → node_start → S-2 → execute → S-3 → node_complete per node under src/nodes/ |

## Non-suppressible gate tests (critical)

- Statutory threshold gate fires regardless of `cold_start` (unit + I-2).
- Employee-ID masking is re-verified independently at the S-3 hook, not trusted from `execute()`
  output alone (unit `test_extra_gate_blocks_unmasked_id`).
