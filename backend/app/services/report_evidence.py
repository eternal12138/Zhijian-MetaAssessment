"""Report input is a frozen view of the SAME evidence used by all radar charts.

No ASR, extraction, coding or classifier is run here. Text is loaded only for a
single report; aggregate dashboard queries remain text-free.
"""
from hashlib import sha256
import json

from sqlalchemy import select
from app.core.time import utc_isoformat, utc_now_naive
from app.models.protocol import AssessmentRun, QuestionnaireResponse
from app.models.scale import ScaleItem
from app.models.task import AssessmentTask
from app.services.metacognition_evidence import load_session_evidence, aggregate_session_evidence
from app.services.metacognition_pattern import classify_metacognition_pattern

DIMENSIONS = {"monitoring": "监控", "controlDebugging": "调控", "evaluation": "评估"}
SOURCE_LABELS = {"admin_upload": "管理员上传校对", "expert_consensus": "专家共识或仲裁",
                 "production_model": "当前候选模型分类"}


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             default=str).encode()).hexdigest()


async def build_report_snapshot(run_id, db):
    run = await db.get(AssessmentRun, run_id)
    if run is None or run.status != "completed" or run.completed_at is None:
        raise ValueError("完整测评尚未结束，不能生成报告")
    sessions, resolved = await load_session_evidence([run_id], db, include_text=True)
    aggregate = aggregate_session_evidence(sessions, resolved)
    denominator = aggregate["effective_dialogue_count"]
    if not aggregate["score_available"]:
        raise ValueError("本轮暂无可用分类结果，请先完成候选分类或人工校对")
    # Do not disguise bad counts as plausible percentages by clipping/normalizing.
    if any(n < 0 or n > denominator for n in aggregate["counts"].values()):
        raise ValueError("标签命中数与最终有效对话数不一致，请核查数据后重试")
    task_ids = sorted({s.task_id for s in sessions})
    titles = dict((await db.execute(select(AssessmentTask.id, AssessmentTask.title).where(
        AssessmentTask.id.in_(task_ids)))).all())
    questionnaires = {d: [] for d in DIMENSIONS}
    questionnaire_rows = (await db.execute(select(QuestionnaireResponse, ScaleItem).join(
        ScaleItem, ScaleItem.id == QuestionnaireResponse.item_id).where(
        QuestionnaireResponse.run_id == run_id))).all() if run.questionnaire_enabled else []
    for answer, item in questionnaire_rows:
        if item.dimension in questionnaires:
            questionnaires[item.dimension].append(8 - answer.value if item.reversed else answer.value)
    records = []
    for session in sessions:
        for item in resolved[session.id]["evidence"]:
            records.append({**item, "session_id": session.id, "task_id": session.task_id})
    records.sort(key=lambda item: (item["session_id"], str(item["segmentId"])))
    incomplete = any(not resolved[s.id]["effective_dialogue_count"] for s in sessions)
    provisional = bool(aggregate["fallback_dialogue_count"] or aggregate["unclassified_count"]
                       or aggregate["retained_previous_count"] or incomplete)
    dimension_scores = {
        dimension: aggregate["counts"][dimension] / denominator
        for dimension in DIMENSIONS
    }
    metacognition_pattern = classify_metacognition_pattern(
        dimension_scores,
        denominator,
        source_is_provisional=provisional,
    )
    details = []
    for dimension, label in DIMENSIONS.items():
        score = aggregate["counts"][dimension] / denominator * 100
        values = questionnaires[dimension]
        details.append({
            "dimension": dimension, "label": label, "score": round(score, 1), "percentile": None,
            "interpretation": f"{aggregate['counts'][dimension]} / {denominator} 条，反映本轮言语证据占比，不代表能力等级或常模百分位。",
            "behavioral_score": round(score, 1), "behavioral_count": aggregate["counts"][dimension],
            "valid_segment_count": denominator,
            "questionnaire_score": round((sum(values)/len(values)-1)/6*100, 1) if values else None,
            "evidence": [{**item, "excerpt": item["excerpt"][:1500], "scaleItemId": "",
                          "reason": SOURCE_LABELS.get(item["source"], item["source"]),
                          "confidence": None} for item in records if item["dimension"] == dimension][:5],
        })
    snapshot = {
        "schema_version": 1, "run_id": run.id, "user_id": run.user_id,
        "session_ids": [s.id for s in sessions], "task_ids": task_ids,
        "task_names": [titles.get(t, t) for t in task_ids],
        "measurement_data_version": aggregate["data_version"],
        "counts": aggregate["counts"], "effective_dialogue_count": denominator,
        "denominator_breakdown": aggregate["denominator_breakdown"],
        "fallback_dialogue_count": aggregate["fallback_dialogue_count"],
        "unclassified_count": aggregate["unclassified_count"],
        "retained_previous_count": aggregate["retained_previous_count"],
        "session_states": aggregate["session_states"], "source": aggregate["primary_source"],
        "is_provisional": provisional, "incomplete_sessions": incomplete,
        "metacognition_pattern": metacognition_pattern,
        "dimension_details": details, "questionnaire_enabled": run.questionnaire_enabled,
        "completed_at": utc_isoformat(run.completed_at),
        # Full selected text hash detects edits even if labels/counts did not change.
        "evidence_hash": fingerprint(records), "questionnaire_hash": fingerprint(questionnaires),
    }
    snapshot["data_version"] = "report-evidence-v1:" + fingerprint(snapshot)
    snapshot["captured_at"] = utc_isoformat(utc_now_naive())
    return snapshot


def snapshot_measurement(snapshot):
    if not snapshot:
        return None
    keys = {"monitoring": "monitoring", "control_debugging": "controlDebugging", "evaluation": "evaluation"}
    denominator = snapshot["effective_dialogue_count"]
    return {
        "id": snapshot["data_version"], "run_id": snapshot["run_id"], "user_id": snapshot["user_id"],
        "scope_type": "run", "scope_key": "run", "task_id": None, "task_name": None,
        "task_ids": snapshot["task_ids"], "task_names": snapshot["task_names"],
        "effective_dialogue_count": denominator,
        "dimension_counts": {out: snapshot["counts"][key] for out, key in keys.items()},
        "dimension_scores": {out: snapshot["counts"][key]/denominator for out, key in keys.items()},
        "score_available": True, "source": snapshot["source"], "data_version": snapshot["data_version"],
        "denominator_breakdown": snapshot["denominator_breakdown"],
        "fallback_dialogue_count": snapshot["fallback_dialogue_count"],
        "unclassified_count": snapshot["unclassified_count"],
        "retained_previous_count": snapshot["retained_previous_count"],
        "session_states": snapshot["session_states"],
        "calculated_at": snapshot["captured_at"], "completed_at": snapshot["completed_at"],
    }
