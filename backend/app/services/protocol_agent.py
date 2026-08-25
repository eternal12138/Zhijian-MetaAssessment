"""标准化测评主试。

ProtocolAgent 只执行测评协议允许的确定性行为，不连接大语言模型，
也不根据实时元认知编码结果改变正式任务中的提示内容。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


NEUTRAL_PROMPTS = (
    "继续大声思考。",
    "你可以大声思考吗？",
    "请继续说。",
    "你现在在做什么？",
)


class ProtocolEvent(StrEnum):
    PARTICIPANT_TURN = "participant_turn"
    SILENCE_REMINDER = "silence_reminder"


@dataclass(frozen=True, slots=True)
class ProtocolDecision:
    event: ProtocolEvent
    should_respond: bool
    message: str | None = None
    prompt_index: int | None = None


class ProtocolAgent:
    """根据固定实验协议决定测评主试是否可以发言。"""

    neutral_prompts = NEUTRAL_PROMPTS

    def handle(
        self,
        event: ProtocolEvent | str,
        *,
        reminder_index: int = 0,
    ) -> ProtocolDecision:
        normalized_event = ProtocolEvent(event)
        if normalized_event is ProtocolEvent.PARTICIPANT_TURN:
            return ProtocolDecision(
                event=normalized_event,
                should_respond=False,
            )

        normalized_index = max(0, reminder_index) % len(self.neutral_prompts)
        return ProtocolDecision(
            event=normalized_event,
            should_respond=True,
            message=self.neutral_prompts[normalized_index],
            prompt_index=normalized_index,
        )

    def is_allowed_formal_task_message(self, message: str) -> bool:
        """正式任务中，主试只能输出版本化的四种中性提示。"""
        return message.strip() in self.neutral_prompts


protocol_agent = ProtocolAgent()
