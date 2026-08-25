"""Canonical narration slots and helpers for protocol snapshots."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.narration import NarrationAsset
from app.models.task import AssessmentTask


INSTRUCTION_NARRATION = (
    "任务进行时，请专注于任务本身，把你脑海中正在发生的想法直接说出来。"
    "如果沉默超过十五秒，系统会提醒你继续说出想法。"
    "全程自动录音仅用于记录你的想法，结束后自动保存。"
    "出声思维操作规范。"
    "第一，任务进行时，请同步口述你看到的页面内容、脑中浮现的所有念头、计算推演步骤与每一次选择判断。"
    "第二，请直接说出脑海原生想法，使用日常口语自然表达，完整呈现当下实时思绪。"
    "第三，全程保持连贯口述思维内容。"
    "第四，若出现连续十五秒未出声的情况，系统将通过文字、语音双重提示，引导您继续分享思考。"
    "第五，任务启动同步开启录音，任务结束后系统自动停止并保存本次口述记录。"
)
PRACTICE_NARRATION = (
    "为了考察甲、乙两地小麦的长势，分别从中抽出 10 株苗，测得苗高如表 1 所示，单位厘米。"
    "表 1 为甲乙两地小麦苗高。"
    "试问哪个地的小麦长得比较整齐。"
    "请持续口头说出你脑海中实时产生的所有想法，包括你的思考过程与答案。"
)
QUESTIONNAIRE_NARRATION = (
    "下面共有24道量表题，最后还有一道姓名确认题。"
    "请回忆你刚刚完成两项问题解决任务时的真实体验与实际行为。"
    "请如实选择，问卷没有对错之分，请根据你的真实情况，"
    "按1（强烈不同意）到7（强烈同意）作答。"
    "完成量表后，请填写您的姓名或参加本次实验时使用的微信名等标识。"
)
SILENCE_REMINDERS = (
    "继续大声思考。",
    "你可以大声思考吗？",
    "请继续说。",
    "你现在在做什么？",
)


@dataclass(frozen=True)
class NarrationSlot:
    key: str
    label: str
    source_text: str
    category: str


def narration_slots(tasks: list[AssessmentTask]) -> list[NarrationSlot]:
    slots = [
        NarrationSlot(
            key="instructions",
            label="出声思维指导语",
            source_text=INSTRUCTION_NARRATION,
            category="instruction",
        ),
        NarrationSlot(
            key="practice",
            label="练习题",
            source_text=PRACTICE_NARRATION,
            category="practice",
        ),
        NarrationSlot(
            key="questionnaire",
            label="问卷填写指导语",
            source_text=QUESTIONNAIRE_NARRATION,
            category="questionnaire",
        ),
    ]
    slots.extend(
        NarrationSlot(
            key=f"task:{task.id}",
            label=f"正式题目：{task.title}",
            source_text=f"现在开始正式任务。题目：{task.title}。{task.scenario}",
            category="task",
        )
        for task in tasks
    )
    slots.extend(
        NarrationSlot(
            key=f"silence:{index}",
            label=f"静默提醒 {index + 1}",
            source_text=text,
            category="silence",
        )
        for index, text in enumerate(SILENCE_REMINDERS)
    )
    return slots


async def active_narration_assets(
    db: AsyncSession,
) -> dict[str, NarrationAsset]:
    result = await db.execute(
        select(NarrationAsset).where(NarrationAsset.is_active.is_(True))
    )
    return {asset.slot_key: asset for asset in result.scalars().all()}


async def narration_snapshot(db: AsyncSession) -> dict[str, str]:
    return {
        slot_key: asset.id
        for slot_key, asset in (await active_narration_assets(db)).items()
    }


async def assets_for_snapshot(
    db: AsyncSession,
    snapshot: dict | None,
) -> list[NarrationAsset]:
    asset_ids = [
        value for value in (snapshot or {}).values()
        if isinstance(value, str) and value
    ]
    if not asset_ids:
        return list((await active_narration_assets(db)).values())
    result = await db.execute(
        select(NarrationAsset).where(NarrationAsset.id.in_(asset_ids))
    )
    return list(result.scalars().all())
