from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..market import market_reference

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/reference")
def reference(product_id: int, grade: str | None = None,
              processing_status: str | None = None,
              date_from: date | None = None, date_to: date | None = None,
              db: Session = Depends(get_db)):
    return market_reference(db, product_id, grade, processing_status,
                            date_from, date_to)
