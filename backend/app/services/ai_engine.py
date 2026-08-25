"""AI 角色组合入口。

测评过程和测评后分析使用两个相互独立的智能体：
- protocol_agent：确定性的标准化主试，不调用 LLM。
- analysis_agent：测评结束后的结构化元认知编码。
"""
from app.services.analysis_agent import AnalysisAgent, analysis_agent
from app.services.protocol_agent import ProtocolAgent, protocol_agent

__all__ = [
    "AnalysisAgent",
    "ProtocolAgent",
    "analysis_agent",
    "protocol_agent",
]
