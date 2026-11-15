from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class CompareIn(BaseModel):
    product_id: int
    need_type: str = Field(pattern="^(gross|net)$")
    need_quantity: float = Field(gt=0)
    grade: Optional[str] = None
    origin: Optional[str] = None
    deliverable_by: Optional[date] = None


class DecisionIn(BaseModel):
    quote_id: int
    need_type: str = Field(pattern="^(gross|net)$")
    need_quantity: float = Field(gt=0)


class CorrectIn(BaseModel):
    new_quote_id: int


class AcceptanceIn(BaseModel):
    trip_no: str
    received_weight_kg: float = Field(ge=0)
    actual_unit_price: Optional[float] = None
    actual_grade: Optional[str] = None
    returned_weight_kg: float = 0
    grade_rejected_weight_kg: float = 0
    actual_yield: Optional[float] = Field(default=None, ge=0, le=1)
    note: Optional[str] = None


class MappingApproveIn(BaseModel):
    product_id: int
    note: Optional[str] = None


class MappingRejectIn(BaseModel):
    note: Optional[str] = None


class ReparseIn(BaseModel):
    column_mapping: Optional[dict[str, str]] = None
    unit_table: Optional[dict[str, str]] = None


class YieldRateIn(BaseModel):
    product_id: int
    from_state: str
    to_state: str = "净菜"
    lower: float = Field(gt=0, le=1)
    upper: float = Field(gt=0, le=1)
    evidence: Optional[str] = None


class ImportOut(BaseModel):
    id: int
    filename: Optional[str]
    kind: str
    status: str
    total_rows: int
    ok_rows: int
    bad_rows: int
    revision: int
    parent_batch_id: Optional[int]

    class Config:
        from_attributes = True


# ---- feature-5 食谱成本事实域 ----

class DishIn(BaseModel):
    code: str
    name: str
    category: str = "热菜"
    region: str = "中央厨房"
    note: Optional[str] = None


class RecipeItemIn(BaseModel):
    ingredient_name: str
    net_qty: Optional[float] = Field(default=None, description="缺失传 null，不可用默认值补齐")
    net_unit: Optional[str] = None
    note: Optional[str] = None


class RecipeVersionIn(BaseModel):
    meal_period: str
    servings: float = Field(gt=0)
    effective_from: date
    items: list[RecipeItemIn]
    source_ref: Optional[str] = None
    note: Optional[str] = None


class MappingIn(BaseModel):
    ingredient_name: str
    product_id: Optional[int] = None
    effective_from: date
    grade: Optional[str] = None
    processing_status: Optional[str] = None
    purchase_code: Optional[str] = None
    composition_code: Optional[str] = None
    allergen_tags: list[str] = []
    conversion: Optional[dict[str, Any]] = None
    allergen_mapped: bool = False
    note: Optional[str] = None


class YieldEvidenceIn(BaseModel):
    product_id: int
    grade: str
    processing_status: str
    evidence_kind: str = Field(pattern="^(measured|estimated|missing)$")
    lower: Optional[float] = Field(default=None, ge=0, le=1)
    upper: Optional[float] = Field(default=None, ge=0, le=1)
    point: Optional[float] = Field(default=None, ge=0, le=1)
    sample_batch: Optional[str] = None
    measured_at: Optional[date] = None
    note: Optional[str] = None


class MeasuredYieldIn(BaseModel):
    product_id: int
    grade: str
    processing_status: str
    point: float = Field(gt=0, le=1)
    sample_batch: str
    measured_at: date
    note: Optional[str] = None


class SnapshotIn(BaseModel):
    dish_id: int
    serving_date: date
    meal_period: str
    published: bool = False


class ConflictResolveIn(BaseModel):
    choice: str = Field(pattern="^(a|b)$")


class BridgeIn(BaseModel):
    base_snapshot_id: int
    target_snapshot_id: int
