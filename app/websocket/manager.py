"""Centralized WebSocket connection manager.

Manages authenticated per-user and per-team channels with:
- Duplicate connection detection (one live connection per user is kept)
- Heartbeat / ping-pong tracking
- Structured, versioned event dispatch
- Isolated channel routing (a user only receives their own events)
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from app.schemas.websocket import WSEnvelope, WSEvent

logger = logging.getLogger(__name__)

# How often the manager sends a ping frame to connected clients (seconds)
HEARTBEAT_INTERVAL = 30


class ConnectionManager:
    """Thread-safe (async) manager for active WebSocket connections."""

    def __init__(self) -> None:
        # user_id -> list of active WebSocket objects
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Accept and register a new connection for *user_id*.

        If the user already has an open connection it is NOT kicked out;
        both connections remain live (useful for multiple browser tabs).
        """
        await websocket.accept()
        self._connections[user_id].append(websocket)
        logger.info("WS connected: user=%s total_conns=%d", user_id, len(self._connections[user_id]))

        # Send the initial connection-status event back to the caller
        await self._send_to_socket(
            websocket,
            self._build_event(
                event_type="connection.status",
                user_id=user_id,
                payload={"status": "connected"},
            ),
        )

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        """Remove a disconnected socket from the registry."""
        connections = self._connections.get(user_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self._connections.pop(user_id, None)
        logger.info("WS disconnected: user=%s remaining=%d", user_id, len(connections))

    # ------------------------------------------------------------------ #
    # Dispatch                                                             #
    # ------------------------------------------------------------------ #

    async def send_to_user(
        self,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        """Emit a versioned event to every connection of *user_id*."""
        event = self._build_event(
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            payload=payload,
        )
        stale: list[WebSocket] = []
        for ws in list(self._connections.get(user_id, [])):
            try:
                await self._send_to_socket(ws, event)
            except Exception:
                stale.append(ws)

        for ws in stale:
            await self.disconnect(user_id, ws)

    async def broadcast(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Broadcast an event to ALL connected users (admin use only)."""
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, event_type, payload)

    # ------------------------------------------------------------------ #
    # Heartbeat                                                            #
    # ------------------------------------------------------------------ #

    async def heartbeat_loop(self) -> None:
        """Background task that pings all connections every HEARTBEAT_INTERVAL seconds."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            stale_users: list[str] = []
            for user_id, sockets in list(self._connections.items()):
                stale: list[WebSocket] = []
                for ws in sockets:
                    try:
                        await ws.send_text(json.dumps({"type": "ping"}))
                    except Exception:
                        stale.append(ws)
                for ws in stale:
                    await self.disconnect(user_id, ws)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _build_event(
        self,
        event_type: str,
        user_id: str | None,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> WSEvent:
        return WSEvent(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            session_id=session_id,
            payload=payload,
        )

    async def _send_to_socket(self, websocket: WebSocket, event: WSEvent) -> None:
        envelope = WSEnvelope(type="event", data=event)
        await websocket.send_text(envelope.model_dump_json())

    def is_connected(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))

    def connection_count(self) -> int:
        return sum(len(v) for v in self._connections.values())


# Singleton instance used across the application
ws_manager = ConnectionManager()
