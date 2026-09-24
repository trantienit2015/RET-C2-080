# RET-C2-080 — Retail POS Transaction Anomaly & Fraud Detection Agent

> **Category**: Cat 2 (orchestrates multiple steps to accomplish a specific use case)
> **Industry**: RET

## Overview

Scans a daily batch of point-of-sale transactions for fraud patterns and returns a risk-ranked
report. The transactions are passed in the invocation context as a transactions list (each
needs register_id and amount; employee_id, type, is_void, is_refund and hour are optional),
together with an optional baseline_days count; the input text itself is not used. Entries
missing register_id or amount are dropped, and an empty or malformed batch is rejected.

The agent normalises the batch and computes per-register and per-employee void rate, refund
rate, off-hours count and amount statistics. Any transaction of 200,000 yen or more is always
flagged as a statutory-threshold finding; this check cannot be suppressed. When at least 14
days of baseline history are declared, it also flags voids at registers with a void rate above
20%, refunds at registers with a refund rate above 15%, transactions before 6:00, and amounts
more than 2.5 standard deviations from the register mean. With less history only the threshold
check runs. Findings are sorted with statutory flags first and then by score.

The report lists every finding with employee IDs replaced by a one-way hash, the total count,
the number of statutory flags, and a recommended action per finding (escalate or monitor). No
language model and no knowledge base are used; all logic is rule-based.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | 3.11 or later |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specification
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
