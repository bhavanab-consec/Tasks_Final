from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Dict


class Event(BaseModel):
    user_id: int = Field(..., description="Unique integer ID of the user")
    timestamp: datetime = Field(..., description="ISO‑8601 timestamp")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary nested JSON payload",
    )