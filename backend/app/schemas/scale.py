"""量表相关 schemas"""
from pydantic import BaseModel


class ScaleItemOut(BaseModel):
    id: str
    dimension: str
    self_report_text: str
    observation_text: str
    keywords: list[str]
    scale_min: int
    scale_max: int
    scoring_rubric: str
    source: str
    reversed: bool
    display_order: int

    model_config = {"from_attributes": True}


class ScaleGroupOut(BaseModel):
    id: str
    dimension: str
    label: str
    description: str
    items: list[ScaleItemOut] = []

    model_config = {"from_attributes": True}
