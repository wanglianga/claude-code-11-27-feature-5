from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (ImportBatch, NameMapping, PurchaseDecision, Quote,
                      StandardProduct)

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


def _quote_out(q: Quote, today=None):
    today = today or date.today()
    expired = bool(q.valid_to and q.valid_to < today)
    earliest = today + timedelta(days=q.lead_days or 0)
    return {
        "id": q.id,
        "external_id": q.external_id,
        "revision": q.revision,
        "is_latest": q.is_latest,
        "source_name": q.source_name,
        "source_type": q.source_type,
        "raw_product_name": q.raw_product_name,
        "product_id": q.product_id,
        "mapping_status": q.mapping_status,
        "grade": q.grade,
        "origin": q.origin,
        "region": q.region,
        "package_desc": q.package_desc,
        "unit": q.unit,
        "unit_raw": q.unit_raw,
        "net_weight_per_unit_kg": q.net_weight_per_unit_kg,
        "gross_weight_per_unit_kg": q.gross_weight_per_unit_kg,
        "processing_status": q.processing_status,
        "price_per_unit": q.price_per_unit,
        "tax_included": q.tax_included,
        "tax_rate": q.tax_rate,
        "valid_from": q.valid_from.isoformat() if q.valid_from else None,
        "valid_to": q.valid_to.isoformat() if q.valid_to else None,
        "expired": expired,
        "earliest_delivery": earliest.isoformat(),
        "moq_quantity": q.moq_quantity,
        "moq_unit": q.moq_unit,
        "delivery_mode": q.delivery_mode,
        "lead_days": q.lead_days,
        "zero_price_basis": q.zero_price_basis,
        "review_status": q.review_status,
        "pending_reasons": q.pending_reasons or [],
        "created_at": q.created_at.isoformat() if q.created_at else None,
    }


@router.get("")
def list_quotes(product_id: int | None = None, grade: str | None = None,
                origin: str | None = None, deliverable_by: date | None = None,
                db: Session = Depends(get_db)):
    q = db.query(Quote).filter(Quote.is_latest.is_(True))
    if product_id:
        q = q.filter(Quote.product_id == product_id)
    if grade:
        q = q.filter(Quote.grade == grade)
    if origin:
        q = q.filter(Quote.origin == origin)
    quotes = q.order_by(Quote.id.desc()).all()
    today = date.today()
    out = []
    for quote in quotes:
        item = _quote_out(quote, today)
        if deliverable_by and item["earliest_delivery"] > deliverable_by.isoformat():
            continue  # 用户限定严格生效
        out.append(item)
    return out


@router.get("/pending")
def pending_quotes(db: Session = Depends(get_db)):
    quotes = (db.query(Quote)
              .filter(Quote.is_latest.is_(True), Quote.review_status == "pending")
              .order_by(Quote.id.desc()).all())
    return [_quote_out(q) for q in quotes]


@router.get("/{quote_id}")
def quote_detail(quote_id: int, db: Session = Depends(get_db)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "报价不存在")
    out = _quote_out(q)
    product = db.get(StandardProduct, q.product_id) if q.product_id else None
    out["product_name"] = product.name if product else None
    out["raw"] = q.raw
    out["fee_rules"] = q.fee_rules
    out["batch_id"] = q.batch_id
    out["row_no"] = q.row_no
    out["parse_revision"] = q.parse_revision
    out["mapping_candidates"] = q.mapping_candidates
    batch = db.get(ImportBatch, q.batch_id)
    out["batch"] = ({"id": batch.id, "filename": batch.filename, "revision": batch.revision}
                    if batch else None)
    mapping = db.query(NameMapping).filter_by(raw_name=q.raw_product_name).first()
    out["mapping"] = ({"id": mapping.id, "status": mapping.status,
                       "revision": mapping.revision} if mapping else None)
    # 同号换值修订链
    chain = []
    if q.external_id:
        siblings = (db.query(Quote)
                    .filter(Quote.source_name == q.source_name,
                            Quote.external_id == q.external_id)
                    .order_by(Quote.revision).all())
        chain = [{"id": s.id, "revision": s.revision, "is_latest": s.is_latest,
                  "price_per_unit": s.price_per_unit,
                  "valid_to": s.valid_to.isoformat() if s.valid_to else None}
                 for s in siblings if s.id != q.id]
    out["revision_chain"] = chain
    decisions = (db.query(PurchaseDecision).filter_by(quote_id=q.id)
                 .order_by(PurchaseDecision.id).all())
    out["decisions"] = [{"id": d.id, "need_type": d.need_type,
                         "need_quantity": d.need_quantity, "units": d.units,
                         "status": d.status,
                         "created_at": d.created_at.isoformat()} for d in decisions]
    return out
