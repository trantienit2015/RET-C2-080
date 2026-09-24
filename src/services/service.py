"""AgentCore Platform v1.0 - RET-C2-080 domain service layer.

Deterministic domain logic for the POS transaction anomaly & fraud detection agent:
  - batch parsing/normalization + per-register/per-employee aggregation
  - cold-start baseline guard
  - Z-score + rule-based anomaly detection across 5 fraud patterns
  - the non-suppressible 割賦販売法 (installment sales law) statutory threshold gate
  - risk ranking
  - employee-ID masking (個人情報保護法) with a non-suppressible re-check

No agenticstar imports. No business logic lives in nodes - nodes call these
pure functions and own only the FunctionNode/state/security plumbing.
"""

from __future__ import annotations

from typing import Any, cast
import hashlib
import statistics

COLD_START_MIN_BASELINE_DAYS = 14

# 割賦販売法 statutory threshold (illustrative; a real deployment sources this from
# config per the current legal threshold). Any transaction meeting/exceeding this
# is ALWAYS flagged regardless of anomaly score - this is the non-suppressible gate.
CREDIT_HOUHU_THRESHOLD_JPY = 200_000

_Z_SCORE_THRESHOLD = 2.5

# Aggregates are serialized into validated_input, which the inner subgraph receives
# as user_input and the framework S-2 gate PII-scans. Unrounded floats such as
# 0.3333333333333333 or 946.337971105226 carry 12-16 digit runs that match the
# credit-card / My Number detectors, get masked, and corrupt the JSON envelope.
# Four decimals keep every statistic well below those digit-run lengths.
_AGG_DECIMALS = 4


def parse_transactions(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Validate + normalize the transaction batch. Empty/malformed -> []."""
    if not raw or not isinstance(raw, list):
        return []
    normalized = []
    for t in raw:
        if not isinstance(t, dict) or "register_id" not in t or "amount" not in t:
            continue
        normalized.append(
            {
                "register_id": str(t.get("register_id", "")),
                "employee_id": str(t.get("employee_id", "")),
                "amount": float(t.get("amount", 0)),
                "type": str(t.get("type", "sale")),
                "is_void": bool(t.get("is_void", False)),
                "is_refund": bool(t.get("is_refund", False)),
                "hour": int(t.get("hour", 12)),
            }
        )
    return normalized


def compute_aggregates(transactions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-register and per-employee aggregates: void rate, refund rate, off-hours count."""
    by_key: dict[str, dict[str, Any]] = {}
    for t in transactions:
        for key in (f"register:{t['register_id']}", f"employee:{t['employee_id']}"):
            if not key.endswith(":"):
                agg = by_key.setdefault(key, {"total": 0, "voids": 0, "refunds": 0, "off_hours": 0, "amounts": []})
                agg["total"] += 1
                agg["voids"] += 1 if t["is_void"] else 0
                agg["refunds"] += 1 if t["is_refund"] else 0
                agg["off_hours"] += 1 if t["hour"] < 6 or t["hour"] > 23 else 0
                agg["amounts"].append(t["amount"])
    result = {}
    for key, agg in by_key.items():
        total = agg["total"] or 1
        result[key] = {
            "void_rate": round(agg["voids"] / total, _AGG_DECIMALS),
            "refund_rate": round(agg["refunds"] / total, _AGG_DECIMALS),
            "off_hours_count": agg["off_hours"],
            "transaction_count": agg["total"],
            "mean_amount": round(statistics.mean(agg["amounts"]), _AGG_DECIMALS) if agg["amounts"] else 0.0,
            "stdev_amount": round(statistics.pstdev(agg["amounts"]), _AGG_DECIMALS) if len(agg["amounts"]) > 1 else 0.0,
        }
    return result


def is_cold_start(baseline_days: int, min_baseline_days: int = COLD_START_MIN_BASELINE_DAYS) -> bool:
    """True when insufficient baseline history is available - suppress baseline-relative alerts."""
    return baseline_days < min_baseline_days


def detect_anomalies(
    transactions: list[dict[str, Any]], aggregates: dict[str, dict[str, Any]], cold_start: bool
) -> list[dict[str, Any]]:
    """Rule + Z-score detection across fraud patterns, plus the non-suppressible statutory gate.

    The 割賦販売法 threshold check is NEVER gated by cold_start or any other
    suppression condition - it always runs on every transaction.
    """
    findings = []
    for t in transactions:
        reg_agg = aggregates.get(f"register:{t['register_id']}", {})

        # Non-suppressible: statutory threshold gate runs unconditionally.
        if t["amount"] >= CREDIT_HOUHU_THRESHOLD_JPY:
            findings.append(
                {
                    "pattern": "statutory_threshold",
                    "register_id": t["register_id"],
                    "employee_id": t["employee_id"],
                    "score": 1.0,
                    "alert_code": "CREDIT-HOUHU-001",
                    "statutory_flag": True,
                }
            )

        if cold_start:
            continue  # baseline-relative checks below are suppressed during cold start

        if t.get("is_void") and reg_agg.get("void_rate", 0) > 0.2:
            findings.append(_finding("void_abuse", t, reg_agg.get("void_rate", 0), "VOID-002"))
        if t.get("is_refund") and reg_agg.get("refund_rate", 0) > 0.15:
            findings.append(_finding("fraudulent_refund", t, reg_agg.get("refund_rate", 0), "REFUND-003"))
        if t.get("hour", 12) < 6 or t.get("hour", 12) > 23:
            findings.append(_finding("off_hours", t, 1.0, "OFFHOURS-004"))

        stdev = reg_agg.get("stdev_amount", 0)
        mean = reg_agg.get("mean_amount", 0)
        if stdev > 0:
            z = abs(t.get("amount", 0) - mean) / stdev
            if z > _Z_SCORE_THRESHOLD:
                findings.append(_finding("card_structuring", t, z, "CARD-005"))

    return findings


def _finding(pattern: str, t: dict[str, Any], score: float, alert_code: str) -> dict[str, Any]:
    return {
        "pattern": pattern,
        "register_id": t["register_id"],
        "employee_id": t["employee_id"],
        "score": score,
        "alert_code": alert_code,
        "statutory_flag": False,
    }


def rank_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Risk-rank findings descending by score; statutory flags always sort first."""
    return sorted(findings, key=lambda f: (not f.get("statutory_flag", False), -f.get("score", 0)))


def mask_employee_id(employee_id: str) -> str:
    """Deterministic, non-reversible employee-ID masking (個人情報保護法)."""
    if not employee_id:
        return ""
    digest = hashlib.sha256(employee_id.encode("utf-8")).hexdigest()[:8]
    return f"EMP-{digest}"


def build_anomaly_report(ranked_findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the final report with employee IDs masked."""
    masked = [{**f, "employee_id": mask_employee_id(f.get("employee_id", ""))} for f in ranked_findings]
    return {
        "findings": masked,
        "total_findings": len(masked),
        "statutory_flag_count": sum(1 for f in masked if f.get("statutory_flag")),
        "recommended_actions": [
            "escalate to loss-prevention" if f.get("statutory_flag") or f.get("score", 0) > 3 else "monitor"
            for f in masked
        ],
    }


def has_unmasked_employee_id(report: dict[str, Any], raw_employee_ids: list[str]) -> bool:
    """Non-suppressible re-check: verify no raw employee_id leaked into the report."""
    findings = report.get("findings", [])
    masked_ids = {f.get("employee_id", "") for f in findings}
    return any(raw_id and raw_id in masked_ids for raw_id in raw_employee_ids)


def dropped_statutory_flag(report: dict[str, Any], expected_statutory_count: int) -> bool:
    """Non-suppressible re-check: verify no statutory-threshold flag was dropped."""
    return cast(bool, report.get("statutory_flag_count", 0) < expected_statutory_count)
