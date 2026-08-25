"""
WebSocket 连接管理器 —— 测评对话实时通道
"""
from fastapi import WebSocket


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接"""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self._connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self._connections.pop(session_id, None)

    async def send(self, session_id: str, data: dict):
        """向指定会话推送消息"""
        ws = self._connections.get(session_id)
        if ws:
            await ws.send_json(data)

    @property
    def active_sessions(self) -> list[str]:
        return list(self._connections.keys())


manager = ConnectionManager()
