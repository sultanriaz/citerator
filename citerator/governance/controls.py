"""Compliance-framework mapping.

Each control has a check function that inspects the current state of the
system and returns pass / partial / fail. The endpoint GET /governance/controls
runs all checks and returns a status report keyed by framework.

The framework mapping (EU AI Act, ISO 42001, NIST AI RMF, SOC 2) is not
exhaustive -- it covers the controls that a mid-size bank's compliance
function will look for when evaluating an AML Q&A tool. Additional
frameworks (DORA, PSD2, local regulators) can be added by extending
FRAMEWORK_MAP without touching check logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from citerator.config import Settings, get_settings
from citerator.governance import audit, classification
from citerator.governance.store import connect


Status = str  # "pass" | "partial" | "fail" | "not_applicable"


@dataclass
class Control:
    id: str
    title: str
    description: str
    check: Callable[[Settings], tuple[Status, str]]


@dataclass
class FrameworkRef:
    framework: str
    reference: str


FRAMEWORK_MAP: dict[str, list[FrameworkRef]] = {
    "audit_chain_integrity": [
        FrameworkRef("EU_AI_ACT", "Art. 12 (record-keeping)"),
        FrameworkRef("ISO_42001", "A.6.2.6 (audit logs)"),
        FrameworkRef("NIST_AI_RMF", "MEASURE 2.5"),
        FrameworkRef("SOC_2", "CC7.2 (monitoring)"),
    ],
    "audit_chain_fresh": [
        FrameworkRef("EU_AI_ACT", "Art. 12"),
        FrameworkRef("SOC_2", "CC7.2"),
    ],
    "human_oversight": [
        FrameworkRef("EU_AI_ACT", "Art. 14"),
        FrameworkRef("ISO_42001", "A.6.2.4"),
        FrameworkRef("NIST_AI_RMF", "GOVERN 3.2"),
    ],
    "confidence_gating": [
        FrameworkRef("EU_AI_ACT", "Art. 15 (accuracy / robustness)"),
        FrameworkRef("ISO_42001", "A.8.3"),
        FrameworkRef("NIST_AI_RMF", "MEASURE 2.6"),
    ],
    "data_classification": [
        FrameworkRef("EU_AI_ACT", "Art. 10 (data governance)"),
        FrameworkRef("ISO_42001", "A.7.2"),
        FrameworkRef("NIST_AI_RMF", "MAP 2.3"),
        FrameworkRef("SOC_2", "CC6.1 (logical access)"),
    ],
    "retention_policy": [
        FrameworkRef("EU_AI_ACT", "Art. 10"),
        FrameworkRef("ISO_42001", "A.7.5"),
        FrameworkRef("SOC_2", "CC6.5"),
    ],
    "erasure_capability": [
        FrameworkRef("GDPR", "Art. 17"),
        FrameworkRef("ISO_42001", "A.7.4"),
    ],
    "model_provenance": [
        FrameworkRef("EU_AI_ACT", "Art. 13 (transparency)"),
        FrameworkRef("ISO_42001", "A.8.2"),
        FrameworkRef("NIST_AI_RMF", "MEASURE 2.7"),
    ],
    "evaluation_fresh": [
        FrameworkRef("EU_AI_ACT", "Art. 9 (risk management)"),
        FrameworkRef("ISO_42001", "A.5.4"),
        FrameworkRef("NIST_AI_RMF", "MEASURE 2.2"),
    ],
}


def _check_audit_chain_integrity(settings: Settings) -> tuple[Status, str]:
    try:
        result = audit.verify(settings=settings)
    except Exception as exc:
        return ("fail", f"verification raised: {exc}")
    if result.total_records == 0:
        return ("partial", "no audit records yet")
    if result.ok:
        return ("pass", f"{result.total_records} records verified")
    return (
        "fail",
        f"tampering detected at sequence {result.first_bad_sequence}: {result.error}",
    )


def _check_audit_chain_fresh(settings: Settings) -> tuple[Status, str]:
    conn = connect(settings.governance_db_path)
    try:
        row = conn.execute(
            "SELECT timestamp FROM audit_chain ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ("partial", "no audit records yet")
    try:
        last = datetime.fromisoformat(row["timestamp"])
    except Exception:
        return ("fail", "malformed timestamp on latest record")
    age = datetime.now(timezone.utc) - last
    if age < timedelta(hours=24):
        return ("pass", f"last record {age.seconds // 60} minutes old")
    if age < timedelta(days=7):
        return ("partial", f"last record {age.days} days old")
    return ("fail", f"no audit activity for {age.days} days")


def _check_human_oversight(settings: Settings) -> tuple[Status, str]:
    conn = connect(settings.governance_db_path)
    try:
        pass
    finally:
        conn.close()
    try:
        from citerator.observability import store as obs_store

        rows = obs_store.list_escalations(limit=1)
    except Exception:
        rows = []
    if settings.escalation_webhook_url or rows:
        return ("pass", "escalation path configured and exercised")
    return (
        "partial",
        "no escalation webhook configured and no escalations recorded",
    )


def _check_confidence_gating(settings: Settings) -> tuple[Status, str]:
    if settings.confidence_floor <= 0.0:
        return ("fail", "confidence_floor is zero; no floor is enforced")
    if settings.confidence_threshold <= settings.confidence_floor:
        return (
            "fail",
            "confidence_threshold must be greater than confidence_floor",
        )
    return (
        "pass",
        f"floor={settings.confidence_floor:.2f} threshold={settings.confidence_threshold:.2f}",
    )


def _check_data_classification(settings: Settings) -> tuple[Status, str]:
    try:
        from citerator.documents import registry

        docs = registry.list_documents(limit=None)
    except Exception as exc:
        return ("fail", f"could not load registry: {exc}")
    if not docs:
        return ("partial", "no documents indexed")
    conn = connect(settings.governance_db_path)
    try:
        classified = conn.execute(
            "SELECT COUNT(DISTINCT doc_id) AS n FROM document_classification"
        ).fetchone()
    finally:
        conn.close()
    n = int(classified["n"]) if classified else 0
    total = len(docs)
    if n == 0:
        return ("fail", f"0/{total} documents have a classification record")
    if n < total:
        return ("partial", f"{n}/{total} documents classified")
    return ("pass", f"{n}/{total} documents classified")


def _check_retention_policy(settings: Settings) -> tuple[Status, str]:
    conn = connect(settings.governance_db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM document_classification
            WHERE retention_days IS NOT NULL
            """
        ).fetchone()
    finally:
        conn.close()
    n = int(row["n"]) if row else 0
    if n == 0:
        return (
            "partial",
            "no retention windows set; documents are kept indefinitely",
        )
    return ("pass", f"{n} documents have an explicit retention window")


def _check_erasure_capability(settings: Settings) -> tuple[Status, str]:
    try:
        from citerator.governance import erasure

        erasure.find_matches("zzz_never_matches_zzz")
    except Exception as exc:
        return ("fail", f"erasure subsystem unavailable: {exc}")
    return ("pass", "erasure path executable")


def _check_model_provenance(settings: Settings) -> tuple[Status, str]:
    conn = connect(settings.governance_db_path)
    try:
        row = conn.execute(
            """
            SELECT payload FROM audit_chain
            WHERE event_type = 'query'
            ORDER BY sequence DESC LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ("partial", "no query audit records to inspect")
    import json

    try:
        payload = json.loads(row["payload"])
    except Exception:
        return ("fail", "malformed audit payload")
    if payload.get("model") and payload.get("prompt_version"):
        return (
            "pass",
            f"latest query recorded model={payload['model']} prompt={payload['prompt_version']}",
        )
    return ("fail", "audit record is missing model or prompt_version")


def _check_evaluation_fresh(settings: Settings) -> tuple[Status, str]:
    try:
        from citerator.evaluation import store as eval_store

        runs = eval_store.list_runs(limit=1, status="completed")
    except Exception as exc:
        return ("fail", f"eval store unavailable: {exc}")
    if not runs:
        return ("partial", "no completed evaluation runs")
    try:
        ts = datetime.fromisoformat(runs[0]["created_at"])
    except Exception:
        return ("fail", "malformed run timestamp")
    age = datetime.now(timezone.utc) - ts
    if age < timedelta(days=7):
        return ("pass", f"latest completed run {age.days} days old")
    if age < timedelta(days=30):
        return ("partial", f"latest completed run {age.days} days old")
    return ("fail", f"no completed evaluation in {age.days} days")


CONTROLS: list[Control] = [
    Control(
        id="audit_chain_integrity",
        title="Audit chain integrity",
        description="Every audit record hashes the previous one; tampering is detectable.",
        check=_check_audit_chain_integrity,
    ),
    Control(
        id="audit_chain_fresh",
        title="Audit chain freshness",
        description="Recent activity exists in the audit chain.",
        check=_check_audit_chain_fresh,
    ),
    Control(
        id="human_oversight",
        title="Human oversight",
        description="A path exists for humans to review and resolve system output.",
        check=_check_human_oversight,
    ),
    Control(
        id="confidence_gating",
        title="Confidence gating",
        description="Low-confidence queries are refused rather than answered.",
        check=_check_confidence_gating,
    ),
    Control(
        id="data_classification",
        title="Data classification",
        description="Every indexed document carries a classification label.",
        check=_check_data_classification,
    ),
    Control(
        id="retention_policy",
        title="Retention policy",
        description="Documents have explicit retention windows, not indefinite storage.",
        check=_check_retention_policy,
    ),
    Control(
        id="erasure_capability",
        title="Erasure capability",
        description="Right-to-erasure requests can be executed.",
        check=_check_erasure_capability,
    ),
    Control(
        id="model_provenance",
        title="Model provenance",
        description="Each query records the model and prompt template used.",
        check=_check_model_provenance,
    ),
    Control(
        id="evaluation_fresh",
        title="Evaluation freshness",
        description="The evaluation harness has been run recently.",
        check=_check_evaluation_fresh,
    ),
]


def evaluate_all(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    results: list[dict[str, Any]] = []
    for c in CONTROLS:
        try:
            status, evidence = c.check(s)
        except Exception as exc:
            status, evidence = ("fail", f"check raised: {exc}")
        results.append(
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "status": status,
                "evidence": evidence,
                "frameworks": [
                    {"framework": r.framework, "reference": r.reference}
                    for r in FRAMEWORK_MAP.get(c.id, [])
                ],
            }
        )

    by_framework: dict[str, dict[str, Any]] = {}
    for r in results:
        for fw in r["frameworks"]:
            bucket = by_framework.setdefault(
                fw["framework"], {"controls": [], "summary": {"pass": 0, "partial": 0, "fail": 0, "not_applicable": 0}}
            )
            bucket["controls"].append(
                {
                    "id": r["id"],
                    "reference": fw["reference"],
                    "status": r["status"],
                }
            )
            bucket["summary"][r["status"]] = bucket["summary"].get(r["status"], 0) + 1

    overall = "pass"
    for r in results:
        if r["status"] == "fail":
            overall = "fail"
            break
        if r["status"] == "partial":
            overall = "partial"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "controls": results,
        "frameworks": by_framework,
    }