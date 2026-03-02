"""WebSocket endpoint."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.manager import ws_manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Optional: handle client messages (e.g. subscribe to match_id)
            # For now we only broadcast from backend on match/odds updates
            await websocket.send_json({"type": "pong", "data": data})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
