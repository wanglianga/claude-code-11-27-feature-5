from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import Acceptance, PurchaseDecision, Quote, User
from ..schemas import AcceptanceIn, CompareIn, CorrectIn, DecisionIn
from ..services import (compare_quotes, create_decision, decision_deviation,
                        summarize_acceptances)

router = APIRouter(prefix="/api", tags=["compare-decisions"])


@router.post("/compare")
def compare(body: CompareIn, db: Session = Depends(get_db)):
    return compare_quotes(db, body.product_id, body.need_type, body.need_quantity,
                          grade=body.grade, origin=body.origin,
                          deliverable_by=body.deliverable_by)


def _decision_out(d: PurchaseDecision, db: Session):
    quote = db.get(Quote, d.quote_id)
    return {
        "id": d.id, "quote_id": d.quote_id, "product_id": d.product_id,
        "need_type": d.need_type, "need_quantity": d.need_quantity,
        "units": d.units, "status": d.status, "revision": d.revision,
        "corrects_id": d.corrects_id, "created_by": d.created_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "source_name": quote.source_name if quote else None,
        "external_id": quote.external_id if quote else None,
        "terms_hash": d.terms_hash,
        "terms_hash_current": quote.terms_hash if quote else None,
        "terms_still_valid": bool(quote and quote.terms_hash == d.terms_hash
                                  and quote.is_latest),
    }


@router.post("/decisions")
def make_decision(body: DecisionIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("buyer"))):
    d = create_decision(db, body.quote_id, body.need_type, body.need_quantity,
                        created_by=user.username)
    return _decision_out(d, db)


@router.get("/decisions")
def list_decisions(db: Session = Depends(get_db)):
    ds = db.query(PurchaseDecision).order_by(PurchaseDecision.id.desc()).all()
    return [_decision_out(d, db) for d in ds]


@router.get("/decisions/{decision_id}")
def decision_detail(decision_id: int, db: Session = Depends(get_db)):
    d = db.get(PurchaseDecision, decision_id)
    if not d:
        raise HTTPException(404, "采购依据不存在")
    out = _decision_out(d, db)
    out["snapshot"] = d.snapshot
    summary = summarize_acceptances(db, d)
    out["acceptance_summary"] = {k: v for k, v in summary.items() if k != "acceptances"}
    out["acceptances"] = [
        {"id": a.id, "trip_no": a.trip_no,
         "received_weight_kg": a.received_weight_kg,
         "actual_unit_price": a.actual_unit_price,
         "actual_grade": a.actual_grade,
         "returned_weight_kg": a.returned_weight_kg,
         "grade_rejected_weight_kg": a.grade_rejected_weight_kg,
         "actual_yield": a.actual_yield, "note": a.note,
         "created_by": a.created_by,
         "created_at": a.created_at.isoformat() if a.created_at else None}
        for a in summary["acceptances"]
    ]
    return out


@router.post("/decisions/{decision_id}/correct")
def correct_decision(decision_id: int, body: CorrectIn,
                     db: Session = Depends(get_db),
                     user: User = Depends(require_roles("buyer"))):
    """人员明确采用新修订后，才生成更正（旧依据保留为 superseded）。"""
    old = db.get(PurchaseDecision, decision_id)
    if not old:
        raise HTTPException(404, "采购依据不存在")
    if old.status != "active":
        raise HTTPException(409, "该依据已被更正，请基于最新依据操作")
    d = create_decision(db, body.new_quote_id, old.need_type, old.need_quantity,
                        created_by=user.username, corrects=old)
    return _decision_out(d, db)


@router.post("/decisions/{decision_id}/acceptances")
def add_acceptance(decision_id: int, body: AcceptanceIn,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_roles("checker"))):
    d = db.get(PurchaseDecision, decision_id)
    if not d:
        raise HTTPException(404, "采购依据不存在")
    a = Acceptance(decision_id=decision_id, trip_no=body.trip_no,
                   received_weight_kg=body.received_weight_kg,
                   actual_unit_price=body.actual_unit_price,
                   actual_grade=body.actual_grade,
                   returned_weight_kg=body.returned_weight_kg,
                   grade_rejected_weight_kg=body.grade_rejected_weight_kg,
                   actual_yield=body.actual_yield, note=body.note,
                   created_by=user.username)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id}


@router.get("/decisions/{decision_id}/deviation")
def deviation(decision_id: int, db: Session = Depends(get_db)):
    d = db.get(PurchaseDecision, decision_id)
    if not d:
        raise HTTPException(404, "采购依据不存在")
    return decision_deviation(db, d)
