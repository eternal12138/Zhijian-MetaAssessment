"""可替换的方法模板。当前内容为开发期占位标准，不代表正式量表结论。"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research import MethodTemplate


DEFAULT_TEMPLATES: dict[str, dict] = {
    "metacognitive_extractor": {
        "kind": "prompt",
        "version": "extractor-1.0",
        "content": """目标：从权威 ASR 转录中高召回抽取“可能包含元认知活动”的原话证据。
边界：你不得判断监控、调节或评价维度，不得评分，不得给出最终编码。
保留：不确定片段也应保留，交由人工复核；不要因口语不完整而删除。
清洗：clean_text 只可删除明显语气词、重复词和无语义停顿，不得改写、概括或补充。
证据：original_text 必须逐字连续出现在对应 segment_id 的 text 中。
输出：仅返回 JSON 对象 {\"candidates\":[{\"segment_id\":\"...\",\"original_text\":\"...\",\"clean_text\":\"...\"}]}。
不得输出 dimension、score、reason、confidence 等最终判断字段。
权威转录片段：{segments}""",
    },
    "coding_prompt": {
        "kind": "prompt",
        "version": "draft-1",
        "content": """你是元认知行为编码员。只依据被试原话进行可观察编码。
维度：monitoring=检查理解/进度/困惑；controlDebugging=调整或纠正策略；
evaluation=验证结果/比较方法/回顾过程。没有明确证据时返回 null。
输出严格 JSON 数组，字段为 segment_id、dimension、score、reason、confidence。
score 暂按 1-7 开发模板评分，不输出思维链。
片段：{segments}""",
    },
    "scoring_standard": {
        "kind": "scoring",
        "version": "draft-1",
        "content": json.dumps({
            "status": "draft",
            "behavior_method": "dimension_frequency_over_valid_segments",
            "behavior_weight": 0.6,
            "questionnaire_weight": 0.4,
            "levels": [
                {"min": 85, "label": "表现突出"},
                {"min": 70, "label": "表现较稳定"},
                {"min": 50, "label": "发展中"},
                {"min": 0, "label": "需要练习"},
            ],
            "notice": "开发期占位标准，正式评分标准完成后整体替换本模板。",
        }, ensure_ascii=False),
    },
    "intervention_templates": {
        "kind": "intervention",
        "version": "draft-1",
        "content": json.dumps({
            "monitoring": {
                "title": "建立过程检查点",
                "description": "在解题前、中、后分别确认任务要求、当前进度和疑问。",
                "practices": ["复述任务要求", "记录一个当前疑问", "完成一步后检查目标"],
            },
            "controlDebugging": {
                "title": "练习策略切换",
                "description": "原方法停滞时先说明原因，再尝试一种不同方法。",
                "practices": ["列出两个候选方法", "设置切换条件", "说明修正了什么"],
            },
            "evaluation": {
                "title": "增加结果验证",
                "description": "从合理性、计算过程和替代方法三个角度核验答案。",
                "practices": ["估算结果范围", "换一种方法复核", "总结适用条件"],
            },
        }, ensure_ascii=False),
    },
}


async def get_template(db: AsyncSession, template_key: str) -> tuple[str, str]:
    result = await db.execute(
        select(MethodTemplate)
        .where(
            MethodTemplate.template_key == template_key,
            MethodTemplate.is_active.is_(True),
        )
        .order_by(MethodTemplate.created_at.desc())
    )
    template = result.scalars().first()
    if template:
        return template.content, template.version
    default = DEFAULT_TEMPLATES[template_key]
    return str(default["content"]), str(default["version"])


async def get_json_template(db: AsyncSession, template_key: str) -> tuple[dict, str]:
    content, version = await get_template(db, template_key)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = json.loads(DEFAULT_TEMPLATES[template_key]["content"])
        version = str(DEFAULT_TEMPLATES[template_key]["version"])
    return parsed, version
