"""Shared API schema behavior."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.time import utc_isoformat


class ApiModel(BaseModel):
    """Serialize database DATETIME values as explicit UTC timestamps."""

    model_config = ConfigDict(
        json_encoders={datetime: utc_isoformat},
    )
