"""市场参考价：同等级、同状态、同时间范围内统计；
以独立卖方为单位先归并（卖方内取中位数），再对卖方中位数取中位数；
转载（repost_of 非空）不增加权重。
"""
import statistics
from datetime import date

from sqlalchemy.orm import Session

from .models import MarketSnapshot


def market_reference(db: Session, product_id: int, grade: str | None = None,
                     processing_status: str | None = None,
                     date_from: date | None = None, date_to: date | None = None):
    q = db.query(MarketSnapshot).filter(
        MarketSnapshot.product_id == product_id,
        MarketSnapshot.repost_of.is_(None),  # 转载不计入
    )
    if grade:
        q = q.filter(MarketSnapshot.grade == grade)
    if processing_status:
        q = q.filter(MarketSnapshot.processing_status == processing_status)
    if date_from:
        q = q.filter(MarketSnapshot.captured_at >= date_from)
    if date_to:
        q = q.filter(MarketSnapshot.captured_at <= date_to)
    snaps = q.all()

    by_seller: dict[str, list[float]] = {}
    for s in snaps:
        by_seller.setdefault(s.seller, []).append(s.price_per_kg)
    seller_medians = [
        {"seller": seller, "median": round(statistics.median(prices), 4), "samples": len(prices)}
        for seller, prices in sorted(by_seller.items())
    ]
    medians = [sm["median"] for sm in seller_medians]
    return {
        "product_id": product_id,
        "grade": grade,
        "processing_status": processing_status,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "seller_count": len(seller_medians),
        "sample_count": len(snaps),
        "seller_medians": seller_medians,
        "reference_median": round(statistics.median(medians), 4) if medians else None,
        "note": "以独立卖方为单位先归并再取中位数；转载不增加权重。",
    }
