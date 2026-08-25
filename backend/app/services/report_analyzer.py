"""Complete-run metacognitive coding and provisional report generation."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.time import utc_now_naive
from app.models.protocol import AssessmentRun, QuestionnaireResponse
from app.models.report import LearningSuggestion, MetacognitiveProfile
from app.models.research import CodingBatch, CodingUnit
from app.models.scale import ScaleItem
from app.services.questionnaire import CURRENT_QUESTIONNAIRE_SOURCE
from app.models.session import AssessmentSession, CodedSegment, TranscriptSegment
from app.services.analysis_agent import AnalysisSegment, analysis_agent
from app.services.method_templates import get_json_template, get_template
from app.services.runtime_model_config import load_runtime_model_settings

settings = get_settings()
RUBRIC_VERSION = "2026.1"
DIMENSIONS = ("monitoring", "controlDebugging", "evaluation")
DIMENSION_LABELS = {
    "monitoring": "监控",
    "controlDebugging": "控制/调试",
    "evaluation": "评估",
}
KEYWORD_RULES = {
    "monitoring": (
        "检查", "确认理解", "不确定", "困惑", "没明白", "发现", "注意到",
        "进度", "好像", "可能不", "矛盾", "看错",
    ),
    "controlDebugging": (
        "调整", "换一种", "换个", "改用", "重新", "纠正", "修正", "试试",
        "另一种", "先算", "改成", "不行的话",
    ),
    "evaluation": (
        "验证", "检验", "回顾", "总结", "合理", "比较方法", "检查结果",
        "最终确认", "是否正确", "结果对不对", "反思",
    ),
}
SUGGESTIONS = {
    "monitoring": (
        "建立过程检查点",
        "在解题前、中、后分别停顿一次，明确问题要求、当前进度和仍不确定的地方。",
        ["复述任务要求", "记录一个当前疑问", "每完成一步检查是否偏离目标"],
    ),
    "controlDebugging": (
        "练习策略切换",
        "当原方法停滞时，明确说出失败原因，再选择一种不同表示或计算方法。",
        ["列出两个可选方法", "为切换策略设置触发条件", "修正后说明改变了什么"],
    ),
    "evaluation": (
        "增加结果验证",
        "得到答案后，从合理性、计算过程和替代方法三个角度进行核验。",
        ["估算结果范围", "用另一种方法复核", "总结方法的适用条件"],
    ),
}


def _normalize(raw_score: float) -> float:
    return round(max(0.0, min(100.0, (raw_score - 1.0) / 6.0 * 100.0)), 1)


def _interpret(score: float, has_behavior: bool) -> str:
    suffix = "；包含出声思维行为证据" if has_behavior else "；当前主要依据任务后问卷"
    if score >= 85:
        return f"该维度表现突出{suffix}。"
    if score >= 70:
        return f"该维度表现较稳定{suffix}。"
    if score >= 50:
        return f"该维度处于发展阶段{suffix}。"
    return f"该维度尚需进一步练习{suffix}。"


def _rule_codes(segment: TranscriptSegment, scale_map: dict[str, str]) -> list[dict]:
    text = segment.text.strip()
    codes: list[dict] = []
    for dimension, keywords in KEYWORD_RULES.items():
        matches = [keyword for keyword in keywords if keyword in text]
        if not matches:
            continue
        score = min(7, 4 + min(3, len(matches)))
        confidence = min(0.9, 0.62 + len(matches) * 0.1)
        codes.append({
            "transcript": segment,
            "dimension": dimension,
            "score": score,
            "reason": f"片段出现可观察线索：{'、'.join(matches[:4])}。",
            "confidence": confidence,
            "scale_item_id": scale_map.get(dimension),
            "analysis_method": "rule",
        })
    return codes


async def _llm_codes(
    segments: list[TranscriptSegment],
    scale_map: dict[str, str],
    prompt_template: str,
) -> list[dict]:
    inputs = [
        AnalysisSegment(segment_id=item.id, text=item.text)
        for item in segments
    ]
    analyzed = await analysis_agent.code_segments(inputs, prompt_template)
    by_id = {item.id: item for item in segments}
    return [
        {
            "transcript": by_id[item.segment_id],
            "dimension": item.dimension,
            "score": item.score,
            "reason": item.reason,
            "confidence": item.confidence,
            "scale_item_id": scale_map.get(item.dimension),
            "analysis_method": "llm",
        }
        for item in analyzed
        if item.segment_id in by_id
    ]


async def _load_run(run_id: str, db: AsyncSession) -> AssessmentRun | None:
    result = await db.execute(
        select(AssessmentRun)
        .where(AssessmentRun.id == run_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(AssessmentRun.sessions).selectinload(
                AssessmentSession.transcript_segments
            ),
            selectinload(AssessmentRun.sessions).selectinload(
                AssessmentSession.transcript_versions
            ),
            selectinload(AssessmentRun.sessions).selectinload(
                AssessmentSession.asr_jobs
            ),
            selectinload(AssessmentRun.sessions).selectinload(
                AssessmentSession.coded_segments
            ),
            selectinload(AssessmentRun.questionnaire_responses),
        )
    )
    return result.scalar_one_or_none()


def _authoritative_transcripts(run: AssessmentRun) -> list[TranscriptSegment]:
    selected: list[TranscriptSegment] = []
    for session in run.sessions:
        authoritative = next(
            (
                version
                for version in session.transcript_versions
                if version.is_authoritative
                and version.status in {"ready", "approved"}
            ),
            None,
        )
        if authoritative is not None:
            selected.extend(
                transcript
                for transcript in session.transcript_segments
                if transcript.transcript_version_id == authoritative.id
                and transcript.is_final
                and transcript.text.strip()
            )
            continue
        if session.asr_jobs:
            raise ValueError("asr_not_ready")
        # 兼容引入服务端 ASR 之前已经完成的历史测评。
        selected.extend(
            transcript
            for transcript in session.transcript_segments
            if transcript.transcript_version_id is None
            and transcript.is_final
            and transcript.text.strip()
        )
    return sorted(
        selected,
        key=lambda item: (item.session_id, item.started_at_ms, item.id),
    )


async def analyze_transcripts(
    run: AssessmentRun,
    db: AsyncSession,
    reanalyze: bool = False,
) -> str:
    await load_runtime_model_settings(db, settings)
    session_ids = [session.id for session in run.sessions]
    transcripts = _authoritative_transcripts(run)
    authoritative_ids = {item.id for item in transcripts}
    existing = [
        code
        for session in run.sessions
        for code in session.coded_segments
        if code.transcript_segment_id
    ]
    existing_ids = {
        code.transcript_segment_id
        for code in existing
        if code.transcript_segment_id
    }
    source_changed = bool(existing) and not existing_ids.issubset(authoritative_ids)
    if (reanalyze or source_changed) and session_ids:
        await db.execute(
            delete(CodedSegment).where(
                CodedSegment.session_id.in_(session_ids),
                CodedSegment.transcript_segment_id.is_not(None),
            )
        )
        existing = []
    if existing:
        return "human_reviewed" if any(code.human_score for code in existing) else "existing"

    item_result = await db.execute(
        select(ScaleItem)
        .where(
            ScaleItem.source
            == (run.questionnaire_source or CURRENT_QUESTIONNAIRE_SOURCE)
        )
        .order_by(ScaleItem.display_order.asc())
    )
    scale_map: dict[str, str] = {}
    for item in item_result.scalars().all():
        scale_map.setdefault(item.dimension, item.id)

    rule_codes = [
        code
        for transcript in transcripts
        for code in _rule_codes(transcript, scale_map)
    ]
    coded_ids = {code["transcript"].id for code in rule_codes}
    ambiguous = [
        transcript for transcript in transcripts
        if transcript.id not in coded_ids
    ]
    coding_prompt, _ = await get_template(db, "coding_prompt")
    llm_codes = await _llm_codes(ambiguous, scale_map, coding_prompt)
    all_codes = rule_codes + llm_codes
    for code in all_codes:
        db.add(CodedSegment(
            session_id=code["transcript"].session_id,
            turn_id=None,
            transcript_segment_id=code["transcript"].id,
            segment=code["transcript"].text,
            dimension=code["dimension"],
            scale_item_id=code["scale_item_id"],
            score=code["score"],
            reason=code["reason"],
            confidence=code["confidence"],
            needs_review=code["confidence"] < 0.75,
            analysis_method=code["analysis_method"],
            rubric_version=RUBRIC_VERSION,
        ))
    await db.flush()
    if llm_codes and rule_codes:
        return "hybrid"
    if llm_codes:
        return "llm"
    return "rule_fallback" if settings.REPORT_USE_LLM and ambiguous else "rule"


async def generate_run_report(
    run_id: str,
    db: AsyncSession,
    reanalyze: bool = False,
) -> MetacognitiveProfile:
    run = await _load_run(run_id, db)
    if run is None:
        raise ValueError("run_not_found")
    if run.status != "completed":
        raise ValueError("run_not_completed")
    if len(run.sessions) < 2:
        raise ValueError("run_sessions_incomplete")

    analysis_method = await analyze_transcripts(run, db, reanalyze=reanalyze)
    await db.flush()
    run = await _load_run(run_id, db)
    assert run is not None

    item_result = await db.execute(
        select(ScaleItem).where(
            ScaleItem.source
            == (run.questionnaire_source or CURRENT_QUESTIONNAIRE_SOURCE)
        )
    )
    items = {item.id: item for item in item_result.scalars().all()}
    questionnaire: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
    for answer in run.questionnaire_responses:
        item = items.get(answer.item_id)
        if item and item.dimension in questionnaire:
            value = 8 - answer.value if item.reversed else answer.value
            questionnaire[item.dimension].append(float(value))

    session_ids = [session.id for session in run.sessions]
    code_result = await db.execute(
        select(CodedSegment)
        .where(
            CodedSegment.session_id.in_(session_ids),
            CodedSegment.transcript_segment_id.is_not(None),
        )
        .execution_options(populate_existing=True)
    )
    codes = [
        code
        for code in code_result.scalars().all()
        if (
            code.dimension in DIMENSIONS
            and (code.score is not None or code.human_score is not None)
        )
    ]
    coding_batch_result = await db.execute(
        select(CodingBatch)
        .join(CodingUnit, CodingUnit.batch_id == CodingBatch.id)
        .where(
            CodingUnit.run_id == run.id,
            CodingBatch.status == "completed",
        )
        .order_by(
            CodingBatch.completed_at.desc(),
            CodingBatch.created_at.desc(),
        )
        .limit(1)
    )
    completed_coding_batch = coding_batch_result.scalar_one_or_none()
    consensus_units: list[CodingUnit] = []
    if completed_coding_batch is not None:
        consensus_result = await db.execute(
            select(CodingUnit)
            .where(
                CodingUnit.batch_id == completed_coding_batch.id,
                CodingUnit.run_id == run.id,
                CodingUnit.status.in_(("agreed", "adjudicated")),
            )
            .order_by(
                CodingUnit.sequence_no.asc(),
                CodingUnit.started_at_ms.asc(),
                CodingUnit.id.asc(),
            )
        )
        consensus_units = list(consensus_result.scalars().all())
        analysis_method = "double_coder_consensus"
    behavioral: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
    consensus_dimension_map = {
        "MONITORING": "monitoring",
        "monitoring": "monitoring",
        "REGULATION": "controlDebugging",
        "regulation": "controlDebugging",
        "control_regulation": "controlDebugging",
        "control-debugging": "controlDebugging",
        "controlDebugging": "controlDebugging",
        "EVALUATION": "evaluation",
        "evaluation": "evaluation",
    }
    if consensus_units:
        for unit in consensus_units:
            mapped_dimension = consensus_dimension_map.get(unit.final_dimension or "")
            if mapped_dimension:
                behavioral[mapped_dimension].append(1.0)
    else:
        for code in codes:
            behavioral[code.dimension].append(float(code.human_score or code.score))

    scoring_standard, scoring_version = await get_json_template(db, "scoring_standard")
    def safe_float(value, default: float) -> float:
        try:
            return float(default if value is None or value == "" else value)
        except (TypeError, ValueError):
            return default

    behavior_weight = safe_float(scoring_standard.get("behavior_weight"), 0.6)
    questionnaire_weight = safe_float(scoring_standard.get("questionnaire_weight"), 0.4)
    weight_total = behavior_weight + questionnaire_weight
    if weight_total <= 0:
        behavior_weight, questionnaire_weight, weight_total = 0.6, 0.4, 1.0
    valid_transcript_count = len(_authoritative_transcripts(run))

    details: list[dict] = []
    for dimension in DIMENSIONS:
        behavioral_frequency = (
            len(behavioral[dimension]) / valid_transcript_count * 100.0
            if valid_transcript_count else None
        )
        questionnaire_raw = (
            sum(questionnaire[dimension]) / len(questionnaire[dimension])
            if questionnaire[dimension] else None
        )
        if behavioral_frequency is not None and questionnaire_raw is not None:
            score = (
                behavior_weight * behavioral_frequency
                + questionnaire_weight * _normalize(questionnaire_raw)
            ) / weight_total
        elif behavioral_frequency is not None:
            score = behavioral_frequency
        elif questionnaire_raw is not None:
            score = _normalize(questionnaire_raw)
        else:
            score = 0.0
        evidence_codes = sorted(
            [code for code in codes if code.dimension == dimension],
            key=lambda item: item.confidence,
            reverse=True,
        )[:5]
        evidence_units = [
            unit for unit in consensus_units
            if consensus_dimension_map.get(unit.final_dimension or "") == dimension
        ][:5]
        details.append({
            "dimension": dimension,
            "label": DIMENSION_LABELS[dimension],
            "score": round(score, 1),
            "percentile": None,
            "interpretation": _interpret(score, behavioral_frequency is not None),
            "behavioral_score": round(behavioral_frequency, 1) if behavioral_frequency is not None else None,
            "questionnaire_score": _normalize(questionnaire_raw) if questionnaire_raw is not None else None,
            "behavioral_count": len(behavioral[dimension]),
            "valid_segment_count": valid_transcript_count,
            "evidence": (
                [
                    {
                        "segmentId": unit.transcript_segment_id,
                        "excerpt": unit.segment[:180],
                        "scaleItemId": "",
                        "reason": (
                            "两名编码员独立编码一致"
                            if unit.final_source == "double_coder_consensus"
                            else "经指定第三方仲裁确认"
                        ),
                        "confidence": 1.0,
                        "needsReview": False,
                    }
                    for unit in evidence_units
                ]
                if consensus_units
                else [
                    {
                        "segmentId": code.id,
                        "excerpt": code.segment[:180],
                        "scaleItemId": code.scale_item_id or "",
                        "reason": code.reason,
                        "confidence": round(code.confidence, 2),
                        "needsReview": code.needs_review,
                    }
                    for code in evidence_codes
                ]
            ),
        })

    overall = round(sum(item["score"] for item in details) / len(details), 1)
    levels = sorted(
        scoring_standard.get("levels", []),
        key=lambda item: safe_float(item.get("min"), 0.0),
        reverse=True,
    )
    level = next(
        (str(item.get("label")) for item in levels if overall >= safe_float(item.get("min"), 0.0)),
        "待解释",
    )
    ordered = sorted(details, key=lambda item: item["score"], reverse=True)
    strengths = [item["label"] for item in ordered if item["score"] >= 70]
    weaknesses = [item["label"] for item in reversed(ordered) if item["score"] < 55]
    review_count = (
        0
        if consensus_units
        else sum(
            1 for code in codes
            if code.needs_review and code.human_score is None
        )
    )
    behavioral_count = len(codes)
    evidence_source = (
        f"{behavioral_count} 条可观察编码证据与任务后问卷"
        if run.questionnaire_enabled
        else f"{behavioral_count} 条可观察编码证据（本次协议未启用任务后问卷）"
    )
    summary = (
        f"本报告依据两项任务中的 {evidence_source} 生成。"
        f"当前综合表现为“{level}”。"
        "结果用于学习反馈，不等同于临床诊断或经常模验证的心理测量结论。"
    )

    profile_result = await db.execute(
        select(MetacognitiveProfile)
        .where(MetacognitiveProfile.run_id == run.id)
        .options(selectinload(MetacognitiveProfile.suggestions))
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        profile = MetacognitiveProfile(
            user_id=run.user_id,
            run_id=run.id,
            session_id=sorted(run.sessions, key=lambda item: item.sequence_no)[0].id,
            suggestions=[],
        )
        db.add(profile)
    else:
        profile.suggestions.clear()
    profile.overall_score = overall
    profile.level = level
    profile.summary = summary
    profile.dimension_details = details
    profile.strengths = json.dumps(strengths, ensure_ascii=False)
    profile.weaknesses = json.dumps(weaknesses, ensure_ascii=False)
    profile.analysis_method = analysis_method
    profile.rubric_version = RUBRIC_VERSION
    profile.requires_review_count = review_count
    profile.is_provisional = True
    profile.workflow_status = "review_pending" if review_count else (
        "reviewed"
        if consensus_units or any(code.human_score is not None for code in codes)
        else "draft"
    )
    profile.template_version = scoring_version
    profile.generated_at = utc_now_naive()

    intervention_templates, _ = await get_json_template(db, "intervention_templates")
    for detail in sorted(details, key=lambda item: item["score"])[:2]:
        configured = intervention_templates.get(detail["dimension"], {})
        fallback_title, fallback_description, fallback_practices = SUGGESTIONS[detail["dimension"]]
        title = str(configured.get("title", fallback_title))
        description = str(configured.get("description", fallback_description))
        practices = configured.get("practices", fallback_practices)
        profile.suggestions.append(LearningSuggestion(
            dimension=detail["dimension"],
            title=title,
            description=description,
            practices=json.dumps(practices, ensure_ascii=False),
            difficulty="medium",
        ))
    await db.flush()
    await db.refresh(profile)
    return profile
