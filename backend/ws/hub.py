from fastapi import WebSocket


class Hub:
    """维护前端 WebSocket 连接，向所有前端广播事件。"""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        dead: list[WebSocket] = []
        for client in list(self.clients):
            try:
                await client.send_json(event)
            except Exception:
                dead.append(client)
        for client in dead:
            self.disconnect(client)
