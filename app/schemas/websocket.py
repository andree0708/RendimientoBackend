"""WebSocket event schemas — versioned, structured events for real-time updates."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# Event version schema
EVENT_VERSION = "1.0"


class WSEvent(BaseModel):
    """A single structured, versioned WebSocket event.

    Every event carries a unique id, a type, a version, a timestamp, the
    owning user, an optional session id, and a payload dict.
    """

    event_id: str
    event_type: str
    version: str = EVENT_VERSION
    timestamp: datetime
    user_id: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class WSEnvelope(BaseModel):
    """Wrapper for sending an event to the client."""

    type: str = "event"
    data: WSEvent
