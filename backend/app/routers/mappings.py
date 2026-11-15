from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import NameMapping, Quote, StandardProduct, User
from ..schemas import MappingApproveIn, MappingRejectIn

router = APIRouter(prefix="/api/mappings", tags=["mappings"])


def _mapping_out(m: NameMapping, db: Session):
    product = db.get(StandardProduct, m.product_id) if m.product_id else None
    pending_quotes = (db.query(Quote)
                      .filter(Quote.raw_product_name == m.raw_name,
                              Quote.is_latest.is_(True)).count())
    return {
        "id": m.id, "raw_name": m.raw_name, "status": m.status,
        "product_id": m.product_id,
        "product_name": product.name if product else None,
        "candidates": m.candidates, "revision": m.revision, "note": m.note,
        "quote_count": pending_quotes,
        "reviewed_by": m.reviewed_by,
        "reviewed_at": m.reviewed_at.isoformat() if m.reviewed_at else None,
    }


@router.get("")
def list_mappings(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(NameMapping).order_by(NameMapping.id.desc())
    if status:
        q = q.filter(NameMapping.status == status)
    return [_mapping_out(m, db) for m in q.all()]


@router.post("/{mapping_id}/approve")
def approve(mapping_id: int, body: MappingApproveIn,
            db: Session = Depends(get_db),
            user: User = Depends(require_roles("buyer"))):
    """审核通过：报价归到标准品。映射修订不改变已生成的采购依据。"""
    m = db.get(NameMapping, mapping_id)
    if not m:
        raise HTTPException(404, "映射不存在")
    product = db.get(StandardProduct, body.product_id)
    if not product:
        raise HTTPException(404, "标准品不存在")
    revised = m.status == "approved" and m.product_id != body.product_id
    m.product_id = body.product_id
    m.status = "approved"
    m.note = body.note
    m.reviewed_at = datetime.utcnow()
    m.reviewed_by = user.username
    if revised:
        m.revision += 1
    # 同步该商品名的最新报价；旧采购依据存的是快照，不受影响
    quotes = (db.query(Quote)
              .filter(Quote.raw_product_name == m.raw_name,
                      Quote.is_latest.is_(True)).all())
    for q in quotes:
        q.product_id = body.product_id
        q.mapping_status = "mapped"
        reasons = [r for r in (q.pending_reasons or []) if r != "商品名未映射"]
        q.pending_reasons = reasons
        q.review_status = "pending" if reasons else "ok"
    db.commit()
    return _mapping_out(m, db)


@router.post("/{mapping_id}/reject")
def reject(mapping_id: int, body: MappingRejectIn,
           db: Session = Depends(get_db),
           user: User = Depends(require_roles("buyer"))):
    m = db.get(NameMapping, mapping_id)
    if not m:
        raise HTTPException(404, "映射不存在")
    m.status = "rejected"
    m.note = body.note
    m.reviewed_at = datetime.utcnow()
    m.reviewed_by = user.username
    db.commit()
    return _mapping_out(m, db)
