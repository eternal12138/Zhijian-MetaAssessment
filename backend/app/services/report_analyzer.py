"""Complete-run metacognitive coding and provisional report generation."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.time import as_utc, utc_now_naive
from app.models.protocol import AssessmentRun, QuestionnaireResponse
from app.models.report import LearningSuggestion, MetacognitiveProfile
from app.models.research import CodingBatch, CodingUnit
from app.models.scale import ScaleItem
from app.services.questionnaire import CURRENT_QUESTIONNAIRE_SOURCE
from app.models.session import AssessmentSession, CodedSegment, TranscriptSegment
from app.services.analysis_agent import AnalysisSegment, analysis_agent
from app.services.method_templates import get_json_template, get_template
from app.services.protocol_config import load_protocol_config
from app.services.runtime_model_config import load_runtime_model_settings

settings = get_settings()
RUBRIC_VERSION = "2026.1"
DIMENSIONS = ("monitoring", "controlDebugging", "evaluation")
STRATEGY_DIMENSIONS = (*DIMENSIONS, "integrated")
PRACTICE_PREFIXES = ("立即尝试：", "练习安排：", "效果检查：")


class ReportReadOnlyError(ValueError):
    """Published/archived content is frozen, including automatic regeneration."""


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


def _fallback_behavior_score(code: CodedSegment) -> float | None:
    """Return the AI score used before a fixed blinded batch is completed.

    ``human_score`` belongs to the retired single-review workflow.  Keeping this
    choice in one named function makes it harder to accidentally reintroduce
    legacy scores into report generation.
    """
    return float(code.score) if code.score is not None else None


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
        return "existing"

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


async def prepare_report(run_id, db, *, report_only=False, expected_generated_at=None):
    """Short read phase. Worker closes the transaction before remote AI I/O."""
    from app.services.report_evidence import build_report_snapshot
    existing = await db.scalar(select(MetacognitiveProfile).where(
        MetacognitiveProfile.run_id == run_id))
    if existing and (existing.workflow_status not in {"draft", "review_pending", "reviewed"}
                     or existing.published_at is not None):
        raise ReportReadOnlyError("已发布或已归档报告不能重新分析")
    if report_only and (not existing or expected_generated_at is None
                        or as_utc(expected_generated_at) != as_utc(existing.generated_at)):
        raise ValueError("报告已更新，请刷新并选择最新草稿后重试")
    await load_runtime_model_settings(db, settings)
    if not settings.REPORT_USE_LLM:
        raise ValueError("AI 报告服务未启用；原草稿已保留，请检查模型服务配置")
    snapshot = await build_report_snapshot(run_id, db)
    prompt, prompt_version = await get_template(db, "report_prompt")
    from app.core.time import utc_isoformat
    from app.services.report_evidence import fingerprint
    from urllib.parse import urlsplit
    service = {"model": settings.LLM_MODEL, "provider_host": urlsplit(settings.LLM_BASE_URL).hostname,
               "max_tokens": settings.LLM_MAX_TOKENS, "temperature": settings.LLM_TEMPERATURE,
               "top_p": settings.LLM_TOP_P, "timeout_seconds": settings.REPORT_LLM_TIMEOUT_SECONDS}
    service["config_revision"] = fingerprint(service)
    return {"snapshot": snapshot, "prompt": prompt, "prompt_version": prompt_version,
            "service": service,
            "expected_version": existing.version_no if existing else None,
            "expected_time": utc_isoformat(existing.generated_at) if existing else None}


def validate_report_output(value):
    """Validate the student-facing recommendation contract.

    Legacy descriptive fields remain optional so an already-active prompt can be
    rolled forward without breaking drafts.  New prompts only need to generate
    prioritized practice suggestions; radar values come from the frozen snapshot.
    """
    if not isinstance(value, dict):
        raise ValueError("AI 报告调用失败或返回内容不完整；原草稿已保留")
    suggestions = value.get("suggestions")
    if not isinstance(suggestions, list) or not 1 <= len(suggestions) <= 3:
        raise ValueError("AI 报告必须提供一至三项优先提升策略；原草稿已保留")
    dimensions = [s.get("dimension") for s in suggestions if isinstance(s, dict)]
    if len(dimensions) != len(suggestions) or len(set(dimensions)) != len(dimensions) or any(
        dimension not in STRATEGY_DIMENSIONS for dimension in dimensions
    ):
        raise ValueError("AI 报告策略维度无效或重复；原草稿已保留")
    for item in suggestions:
        practices = item.get("practices")
        if any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("title", "description")) or not (
            isinstance(practices, list) and len(practices) == len(PRACTICE_PREFIXES)
            and all(
                isinstance(practice, str) and practice.strip().startswith(prefix)
                and practice.strip()[len(prefix):].strip()
                for practice, prefix in zip(practices, PRACTICE_PREFIXES)
            )
        ):
            raise ValueError("AI 报告提升策略内容不完整；原草稿已保留")
    normalized = {"suggestions": suggestions}
    for key in ("summary", "level"):
        if isinstance(value.get(key), str) and value[key].strip():
            normalized[key] = value[key].strip()
    for key in ("strengths", "weaknesses"):
        items = value.get(key)
        if isinstance(items, list) and all(isinstance(item, str) and item.strip() for item in items):
            normalized[key] = [item.strip() for item in items]
    return normalized


async def call_report_ai(prepared, agent=None):
    # A fresh agent per job avoids leaking request metadata/settings between jobs.
    from app.services.analysis_agent import AnalysisAgent
    agent = agent or AnalysisAgent(settings.model_copy(deep=True))
    snapshot = prepared["snapshot"]
    value = await agent.generate_metacognitive_profile(
        overall_score=0, dimension_results=snapshot["dimension_details"],
        prompt_template=prepared["prompt"], report_context=snapshot)
    value = validate_report_output(value)
    return value, getattr(agent, "last_report_metadata", {})


async def save_report(prepared, value, metadata, db):
    """Short atomic compare-and-swap. Failed/stale work never erases the draft."""
    from app.services.report_evidence import build_report_snapshot
    from app.models.report import ReportRevision
    from app.core.time import utc_isoformat
    value = validate_report_output(value)
    snapshot = prepared["snapshot"]
    # A run row also serializes first creation when there is no profile yet.
    await db.scalar(select(AssessmentRun).where(AssessmentRun.id == snapshot["run_id"]).with_for_update())
    profile = await db.scalar(select(MetacognitiveProfile).where(
        MetacognitiveProfile.run_id == snapshot["run_id"]).options(selectinload(MetacognitiveProfile.suggestions))
        .execution_options(populate_existing=True).with_for_update())
    if profile and (profile.workflow_status not in {"draft", "review_pending", "reviewed"} or profile.published_at):
        raise ReportReadOnlyError("报告已发布或归档；本次生成结果未覆盖原稿")
    if (profile.version_no if profile else None) != prepared["expected_version"] or (
        utc_isoformat(profile.generated_at) if profile else None) != prepared["expected_time"]:
        raise ValueError("报告版本已变化；本次结果未覆盖原稿，请刷新重试")
    current = await build_report_snapshot(snapshot["run_id"], db)
    if current["data_version"] != snapshot["data_version"]:
        raise ValueError("生成期间数据已更新；原草稿已保留，请重新生成")

    def revision_content(p):
        return {"summary": p.summary, "level": p.level, "overall_score": p.overall_score,
                "dimension_details": p.dimension_details, "strengths": p.strengths, "weaknesses": p.weaknesses,
                "evidence_snapshot": p.evidence_snapshot, "generation_metadata": p.generation_metadata,
                "template_version": p.template_version, "generated_at": utc_isoformat(p.generated_at),
                "suggestions": [{"dimension": s.dimension, "title": s.title, "description": s.description,
                                 "practices": s.practices} for s in p.suggestions]}

    if profile:
        if not await db.scalar(select(ReportRevision.id).where(
            ReportRevision.profile_id == profile.id, ReportRevision.version_no == profile.version_no)):
            db.add(ReportRevision(profile_id=profile.id, version_no=profile.version_no, content=revision_content(profile)))
        profile.version_no += 1
        profile.suggestions.clear()
    else:
        profile = MetacognitiveProfile(user_id=snapshot["user_id"], run_id=snapshot["run_id"],
                                      session_id=snapshot["session_ids"][0], suggestions=[], version_no=1)
        db.add(profile)
    # Legacy numeric field retained for DB/API compatibility, explicitly unavailable.
    # A mean of three proportions is NOT an ability score.
    profile.overall_score = 0
    profile.level = "暂定学习反馈" if snapshot["is_provisional"] else "学习反馈"
    profile.summary = value.get("summary") or (
        f"本轮共记录 {snapshot['effective_dialogue_count']} 条最终有效对话；"
        "三维画像展示各类言语证据占比，提升策略依据本轮模式与证据生成。"
    )
    profile.dimension_details = snapshot["dimension_details"]
    profile.strengths = json.dumps(value.get("strengths", []), ensure_ascii=False)
    profile.weaknesses = json.dumps(value.get("weaknesses", []), ensure_ascii=False)
    profile.analysis_method = "unified_evidence"
    profile.rubric_version = "evidence-v1"
    profile.requires_review_count = snapshot["unclassified_count"]
    profile.is_provisional = True  # Every newly generated draft must be reviewed.
    profile.workflow_status = "review_pending"
    profile.template_version = prepared["prompt_version"]
    profile.generated_at = utc_now_naive()
    profile.evidence_snapshot = snapshot
    profile.generation_metadata = {**prepared.get("service", {}), **metadata, "status": "ai_success",
        "prompt_version": prepared["prompt_version"], "prompt_snapshot": prepared["prompt"],
        "data_version": snapshot["data_version"]}
    for item in value["suggestions"]:
        profile.suggestions.append(LearningSuggestion(dimension=item["dimension"], title=item["title"][:128],
            description=item["description"], practices=json.dumps(item["practices"], ensure_ascii=False),
            difficulty="medium"))
    await db.flush()
    db.add(ReportRevision(profile_id=profile.id, version_no=profile.version_no, content=revision_content(profile)))
    await db.flush()
    return profile


async def generate_run_report(run_id, db, reanalyze=False, *, report_only=False, expected_generated_at=None):
    """Compatibility helper for controlled callers; production uses the job worker.

    This path never re-codes transcripts and never silently substitutes rule text.
    """
    if reanalyze:
        raise ValueError("报告生成不再重新编码原文，请使用候选复核与 AI 评估")
    prepared = await prepare_report(run_id, db, report_only=report_only, expected_generated_at=expected_generated_at)
    value, metadata = await call_report_ai(prepared)
    return await save_report(prepared, value, metadata, db)
