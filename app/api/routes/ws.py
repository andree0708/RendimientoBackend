"""WebSocket endpoint — authenticated real-time channel.

Flow:
1. Client connects to /ws?token=<jwt>
2. Server validates the JWT and accepts the connection
3. The ConnectionManager registers the user's socket
4. Server pushes structured, versioned events to the client
5. Client can send ping messages; server responds with pong
6. On disconnect, the manager cleans up the socket
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.security import decode_token
from app.models.user import User
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


def get_ws_session() -> Session:
    """Return a database session for the WebSocket endpoint.

    This indirection allows tests to override the session factory.
    """
    return SessionLocal()


async def _authenticate_ws(token: str | None, db: Session) -> User | None:
    """Validate the JWT sent as a query parameter and return the user."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.is_active:
        return user
    return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint.  Requires a valid access token via query param."""
    token = websocket.query_params.get("token")
    db = get_ws_session()
    user = None
    try:
        user = await _authenticate_ws(token, db)
        if user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await ws_manager.connect(user.id, websocket)

        # Main message loop — client can send pings or control messages
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = msg.get("type", "")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "subscribe":
                # Client confirms which channels it wants — acknowledge
                channels = msg.get("channels", ["user"])
                await websocket.send_text(
                    json.dumps(
                        {"type": "ack", "message": f"Subscribed to channels: {channels}"}
                    )
                )
            elif msg_type == "event_ack":
                # Client acknowledges receipt of an event — log if needed
                logger.debug("Event ack: %s", msg.get("event_id"))
            else:
                await websocket.send_text(
                    json.dumps({"type": "error", "message": f"Unknown message type: {msg_type}"})
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        # ws_manager.disconnect needs the websocket; we pass user.id if we have it
        if user is not None:
            await ws_manager.disconnect(user.id, websocket)
        db.close()
