"""业务服务：对比、采购依据、验收汇总。"""
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .calc import assign_overlap_groups, plan_quote
from .deviation import chain_deviation
from .models import (Acceptance, PurchaseDecision, Quote, StandardProduct,
                     YieldRate)


def get_yield_rate(db: Session, product_id: int, from_state: str | None):
    """取该标准品在报价加工状态下的出成率；净菜->净菜默认 1。"""
    if not from_state:
        return None
    if from_state == "净菜":
        return YieldRate(product_id=product_id, from_state="净菜", to_state="净菜",
                         lower=1.0, upper=1.0, evidence="净菜无需换算")
    return (db.query(YieldRate)
            .filter_by(product_id=product_id, from_state=from_state)
            .order_by(YieldRate.id.desc()).first())


def compare_quotes(db: Session, product_id: int, need_type: str, need_qty: float,
                   grade=None, origin=None, deliverable_by=None, today=None):
    today = today or date.today()
    product = db.get(StandardProduct, product_id)
    if not product:
        raise HTTPException(404, "标准品不存在")
    quotes = (db.query(Quote)
              .filter(Quote.product_id == product_id, Quote.is_latest.is_(True))
              .order_by(Quote.id).all())
    # 未映射但候选含本品的报价：列入排除项说明，不参与排名
    pending_candidates = (db.query(Quote)
                          .filter(Quote.mapping_status == "pending",
                                  Quote.is_latest.is_(True),
                                  Quote.product_id.is_(None))
                          .order_by(Quote.id).all())

    filtered_out = 0
    results, excluded = [], []
    for q in pending_candidates:
        cand_ids = [c.get("product_id") for c in (q.mapping_candidates or [])]
        if product_id in cand_ids:
            excluded.append({
                "quote_id": q.id, "source_name": q.source_name,
                "revision": q.revision, "grade": q.grade, "origin": q.origin,
                "processing_status": q.processing_status,
                "price_per_unit": q.price_per_unit, "unit_raw": q.unit_raw,
                "reasons": (q.pending_reasons or []) + ["商品名未映射（仅候选，待审核）"],
            })
    for q in quotes:
        # 用户限定条件严格生效，不为补齐报价而取消
        if grade and q.grade != grade:
            filtered_out += 1
            continue
        if origin and q.origin != origin:
            filtered_out += 1
            continue
        yr = get_yield_rate(db, product_id, q.processing_status)
        plan = plan_quote(q, yr, need_type, need_qty, today=today,
                          deliverable_by=deliverable_by)
        item = {
            "quote_id": q.id,
            "source_name": q.source_name,
            "revision": q.revision,
            "grade": q.grade,
            "origin": q.origin,
            "processing_status": q.processing_status,
            "delivery_mode": q.delivery_mode,
            "lead_days": q.lead_days,
            "valid_to": q.valid_to.isoformat() if q.valid_to else None,
            "price_per_unit": q.price_per_unit,
            "unit_raw": q.unit_raw,
        }
        if not plan.get("eligible"):
            excluded.append({**item, "reasons": plan["reasons"]})
        else:
            item.update({k: v for k, v in plan.items()
                         if k not in ("eligible", "quote_id")})
            yr_info = None
            if yr and yr.from_state != "净菜":
                yr_info = {"lower": yr.lower, "upper": yr.upper,
                           "evidence": yr.evidence, "from_state": yr.from_state}
            item["yield_rate"] = yr_info
            results.append(item)

    results = assign_overlap_groups(results)
    ranked = [r for r in results if r.get("convertible")]
    for i, r in enumerate(ranked):
        r["rank_hint"] = None if r.get("overlapped") else i + 1
    return {
        "product": {"id": product.id, "name": product.name},
        "need_type": need_type,
        "need_quantity": need_qty,
        "filters": {"grade": grade, "origin": origin,
                    "deliverable_by": deliverable_by.isoformat() if deliverable_by else None},
        "results": results,
        "excluded": excluded,
        "filtered_out_count": filtered_out,
        "note": "区间重叠的报价不强制排名；缺出成率实测的报价按原价展示，不参与排名。",
    }


def _decision_snapshot(quote: Quote, plan: dict, yr: YieldRate | None,
                       need_type: str, need_qty: float) -> dict:
    terms = {
        "quote_id": quote.id,
        "quote_revision": quote.revision,
        "external_id": quote.external_id,
        "source_name": quote.source_name,
        "unit": quote.unit,
        "unit_raw": quote.unit_raw,
        "net_weight_per_unit_kg": quote.net_weight_per_unit_kg,
        "gross_weight_per_unit_kg": quote.gross_weight_per_unit_kg
        or quote.net_weight_per_unit_kg,
        "price_per_unit": quote.price_per_unit,
        "tax_included": quote.tax_included,
        "tax_rate": quote.tax_rate,
        "delivery_mode": quote.delivery_mode,
        "lead_days": quote.lead_days,
        "fee_rules": quote.fee_rules,
        "moq_quantity": quote.moq_quantity,
        "moq_unit": quote.moq_unit,
        "valid_to": quote.valid_to.isoformat() if quote.valid_to else None,
        "zero_price_basis": quote.zero_price_basis,
        "grade": quote.grade,
        "origin": quote.origin,
        "processing_status": quote.processing_status,
    }
    planned = {
        "need_type": need_type,
        "need_quantity": need_qty,
        "units": plan["units"],
        "price_per_unit": quote.price_per_unit,
        "yield_used": plan.get("yield_lower", 1.0),
        "yield_upper": plan.get("yield_upper"),
        "freight_weight_kg": plan["freight_weight_kg"],
        "usable_kg_planned": plan.get("usable_kg_lower")
        or plan["purchase_kg"] * (plan.get("yield_lower") or 1.0),
        "total_cost": plan["total_cost"],
        "breakdown": {k: plan[k] for k in
                      ("goods_amount", "tax_amount", "freight", "freight_desc",
                       "alloc_fees", "alloc_items", "cost_per_gross_kg",
                       "cost_per_usable_kg_lower", "cost_per_usable_kg_upper",
                       "surplus_kg") if k in plan},
    }
    return {
        "terms": terms,
        "planned": planned,
        "yield_rate": ({"lower": yr.lower, "upper": yr.upper, "evidence": yr.evidence}
                       if yr and yr.from_state != "净菜" else None),
        "frozen_at": datetime.utcnow().isoformat(),
    }


def create_decision(db: Session, quote_id: int, need_type: str, need_qty: float,
                    created_by: str, corrects: PurchaseDecision | None = None,
                    today=None) -> PurchaseDecision:
    """采用报价生成只读采购依据；确认时检查所选条款仍有效。"""
    today = today or date.today()
    quote = db.get(Quote, quote_id)
    if not quote:
        raise HTTPException(404, "报价不存在")
    if not quote.is_latest:
        raise HTTPException(409, f"报价已有新修订（当前为第 {quote.revision} 版），请改用最新报价")
    if quote.mapping_status != "mapped" or not quote.product_id:
        raise HTTPException(409, "报价未完成标准品映射，不能采用")
    yr = get_yield_rate(db, quote.product_id, quote.processing_status)
    plan = plan_quote(quote, yr, need_type, need_qty, today=today)
    if not plan.get("eligible"):
        raise HTTPException(409, {"detail": "条款已失效，不能采用", "reasons": plan["reasons"]})
    if not plan.get("convertible"):
        raise HTTPException(409, plan.get("note", "报价不可换算，不能采用"))

    snapshot = _decision_snapshot(quote, plan, yr, need_type, need_qty)
    decision = PurchaseDecision(
        quote_id=quote.id, product_id=quote.product_id, need_type=need_type,
        need_quantity=need_qty, units=plan["units"], snapshot=snapshot,
        terms_hash=quote.terms_hash, created_by=created_by,
        revision=(corrects.revision + 1) if corrects else 1,
        corrects_id=corrects.id if corrects else None,
    )
    if corrects:
        corrects.status = "superseded"
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def summarize_acceptances(db: Session, decision: PurchaseDecision):
    """汇总验收：短装/退货/等级拒收分列；未验收部分不提前算损耗。"""
    accs = (db.query(Acceptance).filter_by(decision_id=decision.id)
            .order_by(Acceptance.id).all())
    terms = decision.snapshot["terms"]
    planned = decision.snapshot["planned"]
    gross_per_unit = terms["gross_weight_per_unit_kg"] or terms["net_weight_per_unit_kg"]
    planned_gross = planned["units"] * (gross_per_unit or 1.0)

    received = sum(a.received_weight_kg for a in accs)
    returned = sum(a.returned_weight_kg or 0 for a in accs)
    rejected = sum(a.grade_rejected_weight_kg or 0 for a in accs)
    # 加权平均单价与出成率（按到货重量）
    price_num = sum((a.actual_unit_price or planned["price_per_unit"]) * a.received_weight_kg
                    for a in accs)
    price_avg = price_num / received if received else None
    y_num = sum(a.actual_yield * a.received_weight_kg for a in accs
                if a.actual_yield is not None)
    y_den = sum(a.received_weight_kg for a in accs if a.actual_yield is not None)
    yield_avg = y_num / y_den if y_den else None

    unaccepted = max(planned_gross - received, 0.0)
    return {
        "acceptances": accs,
        "planned_gross_kg": round(planned_gross, 2),
        "received_kg": round(received, 2),
        "short_kg": round(max(planned_gross - received, 0.0), 2),
        "returned_kg": round(returned, 2),
        "grade_rejected_kg": round(rejected, 2),
        "unaccepted_kg": round(unaccepted, 2),
        "unaccepted_note": "未验收部分不提前算成损耗" if unaccepted > 0 else None,
        "actual_unit_price_avg": round(price_avg, 4) if price_avg else None,
        "actual_yield_avg": round(yield_avg, 4) if yield_avg is not None else None,
    }


def decision_deviation(db: Session, decision: PurchaseDecision):
    summary = summarize_acceptances(db, decision)
    if not summary["received_kg"]:
        return {"available": False, "reason": "尚无验收记录", "summary": _pub_summary(summary)}
    actual = {
        "actual_unit_price": summary["actual_unit_price_avg"],
        "received_weight_kg": summary["received_kg"],
        "actual_yield": summary["actual_yield_avg"],
    }
    result = chain_deviation(decision.snapshot, actual)
    result["available"] = True
    result["summary"] = _pub_summary(summary)
    return result


def _pub_summary(s):
    return {k: v for k, v in s.items() if k != "acceptances"}
