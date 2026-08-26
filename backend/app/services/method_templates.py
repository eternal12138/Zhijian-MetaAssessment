"""可替换的方法模板。当前内容为开发期占位标准，不代表正式量表结论。"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research import MethodTemplate


DEFAULT_TEMPLATES: dict[str, dict] = {
    "report_prompt": {
        "kind": "prompt",
        "version": "report-profile-v1.0",
        "content": """你是 AI 元认知测评与干预专家。请依据被试的元认知三分类评估结果（监控 monitoring、控制/调试 controlDebugging、评估 evaluation）与关键证据，生成结构化元认知画像报告与干预策略。

【评估数据输入】
综合得分：{overall_score}
维度详情与关键证据：
{dimension_results}

【输出格式要求】
必须严格返回单个合法 JSON 对象（不得输出 Markdown 标记或多余文字），必须包含以下字段：
{
  "level": "表现等级（在 '表现突出' / '表现较稳定' / '发展中' / '需要练习' 中四选一）",
  "summary": "综合画像诊断（150-200字，客观评价其监控、调控与评估表现特征）",
  "strengths": ["优势维度名称，无则返回 []"],
  "weaknesses": ["待提升维度名称，无则返回 []"],
  "suggestions": [
    {
      "dimension": "维度标识（monitoring / controlDebugging / evaluation）",
      "title": "干预策略标题（15字以内）",
      "description": "策略指导说明（50-80字）",
      "practices": ["行动建议1", "行动建议2", "行动建议3"]
    }
  ]
}""",
    },
    "metacognitive_extractor": {
        "kind": "prompt",
        "version": "extractor-1.0",
        "content": """目标：从权威 ASR 转录中高召回抽取“可能包含元认知活动”的原话证据。
边界：不得判断维度、不得评分、不得给出最终编码；不确定片段也应保留供人工复核。
清洗：clean_text 仅删除明显语气词、重复词与无语义停顿，不得改写、概括或补充。
证据：original_text 必须逐字连续出现在对应 segment_id 的 text 中。
输出：仅返回 JSON 对象 {"candidates":[{"segment_id":"...","original_text":"...","clean_text":"..."}]}。
权威转录片段：
{segments}""",
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
