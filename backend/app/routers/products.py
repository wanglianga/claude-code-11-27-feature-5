from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import StandardProduct, User, YieldRate
from ..schemas import YieldRateIn

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
def list_products(db: Session = Depends(get_db)):
    products = db.query(StandardProduct).order_by(StandardProduct.id).all()
    return [
        {"id": p.id, "name": p.name, "category": p.category,
         "base_unit": p.base_unit, "note": p.note,
         "yield_rates": [
             {"id": y.id, "from_state": y.from_state, "to_state": y.to_state,
              "lower": y.lower, "upper": y.upper, "evidence": y.evidence}
             for y in p.yield_rates
         ]}
        for p in products
    ]


@router.post("/yield-rates")
def add_yield_rate(body: YieldRateIn, db: Session = Depends(get_db),
                   _: User = Depends(require_roles("buyer"))):
    if body.lower > body.upper:
        raise HTTPException(400, "出成率下界不能大于上界")
    if not db.get(StandardProduct, body.product_id):
        raise HTTPException(404, "标准品不存在")
    y = YieldRate(**body.model_dump())
    db.add(y)
    db.commit()
    db.refresh(y)
    return {"id": y.id}
