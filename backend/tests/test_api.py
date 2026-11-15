"""API 级测试：市场参考价、映射审核、采购依据与验收。"""
from datetime import date

from app.models import (ImportBatch, MarketSnapshot, NameMapping, Quote,
                        StandardProduct, YieldRate)


def ensure_batch(db):
    batch = db.query(ImportBatch).first()
    if not batch:
        batch = ImportBatch(filename="test", file_hash="h", kind="csv",
                            status="completed", file_content="")
        db.add(batch)
        db.commit()
    return batch


def seed_product(db, name="土豆"):
    p = StandardProduct(name=name)
    db.add(p)
    db.flush()
    db.add(NameMapping(raw_name=name, product_id=p.id, status="approved"))
    db.commit()
    return p


def add_snapshot(db, product_id, seller, price, repost_of=None, grade="一级",
                 state="净菜"):
    batch = ensure_batch(db)
    db.add(MarketSnapshot(batch_id=batch.id, seller=seller, product_id=product_id,
                          grade=grade, processing_status=state,
                          price_per_kg=price, captured_at=date(2026, 11, 10),
                          repost_of=repost_of))
    db.commit()


def test_market_reference_median_and_repost(client, db):
    p = seed_product(db)
    add_snapshot(db, p.id, "甲", 2.0)
    add_snapshot(db, p.id, "甲", 2.4)
    add_snapshot(db, p.id, "乙", 3.0)
    add_snapshot(db, p.id, "丙转载", 9.9, repost_of=1)
    r = client.get(f"/api/market/reference?product_id={p.id}&grade=一级&processing_status=净菜")
    assert r.status_code == 200
    data = r.json()
    # 甲中位数 2.2，乙 3.0 -> 参考中位数 2.6；转载不计
    assert data["seller_count"] == 2
    assert data["reference_median"] == 2.6


def add_quote(db, product_id, **kw):
    batch = ensure_batch(db)
    defaults = dict(
        batch_id=batch.id, row_no=1, source_name="供应商A", raw_product_name="土豆",
        product_id=product_id, mapping_status="mapped", grade="一级",
        unit="box", unit_raw="箱", net_weight_per_unit_kg=20.0,
        gross_weight_per_unit_kg=21.0, processing_status="带泥毛菜",
        price_per_unit=35.0, tax_included=True, valid_from=date(2026, 11, 1),
        valid_to=date(2026, 12, 31), moq_quantity=5, moq_unit="箱",
        delivery_mode="配送", lead_days=1, review_status="ok",
        pending_reasons=[], is_latest=True, revision=1,
        fee_rules={"freight": {"min_fee": 20, "tiers": [
            {"max_kg": 100, "fee": 30}, {"max_kg": None, "per_kg": 0.3}]}},
        terms_hash="h1",
    )
    defaults.update(kw)
    q = Quote(**defaults)
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def test_compare_and_decision_flow(client, db, buyer_headers, checker_headers):
    p = seed_product(db)
    db.add(YieldRate(product_id=p.id, from_state="带泥毛菜", to_state="净菜",
                     lower=0.78, upper=0.85, evidence="实测"))
    db.commit()
    q = add_quote(db, p.id)

    r = client.post("/api/compare", json={
        "product_id": p.id, "need_type": "net", "need_quantity": 100})
    assert r.status_code == 200
    res = r.json()["results"]
    assert len(res) == 1 and res[0]["units"] == 7

    r = client.post("/api/decisions", json={
        "quote_id": q.id, "need_type": "net", "need_quantity": 100},
        headers=buyer_headers)
    assert r.status_code == 200, r.text
    decision_id = r.json()["id"]
    assert r.json()["units"] == 7

    # 验收：短装 + 出成率降低
    r = client.post(f"/api/decisions/{decision_id}/acceptances", json={
        "trip_no": "车A", "received_weight_kg": 135, "actual_unit_price": 36,
        "actual_yield": 0.74, "returned_weight_kg": 3,
        "grade_rejected_weight_kg": 2}, headers=checker_headers)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/decisions/{decision_id}/deviation")
    data = r.json()
    assert data["available"]
    assert data["consistent"]
    assert data["summary"]["short_kg"] == 12.0
    assert data["summary"]["returned_kg"] == 3.0
    assert data["summary"]["grade_rejected_kg"] == 2.0
    # 未验收部分不提前算损耗
    assert data["summary"]["unaccepted_kg"] == 12.0


def test_decision_rejected_when_terms_invalid(client, db, buyer_headers):
    p = seed_product(db)
    q = add_quote(db, p.id, valid_to=date(2026, 10, 1))  # 已过期
    r = client.post("/api/decisions", json={
        "quote_id": q.id, "need_type": "gross", "need_quantity": 100},
        headers=buyer_headers)
    assert r.status_code == 409


def test_decision_requires_role(client, db):
    p = seed_product(db)
    q = add_quote(db, p.id)
    r = client.post("/api/decisions", json={
        "quote_id": q.id, "need_type": "gross", "need_quantity": 100})
    assert r.status_code == 401


def test_mapping_approve_updates_quotes(client, db, buyer_headers):
    p = seed_product(db)
    q = add_quote(db, None, raw_product_name="洋芋",
                  mapping_status="pending", review_status="pending",
                  pending_reasons=["商品名未映射"])
    mapping = db.query(NameMapping).filter_by(raw_name="洋芋").first()
    if not mapping:
        mapping = NameMapping(raw_name="洋芋", status="pending")
        db.add(mapping)
        db.commit()
    r = client.post(f"/api/mappings/{mapping.id}/approve",
                    json={"product_id": p.id}, headers=buyer_headers)
    assert r.status_code == 200
    db.refresh(q)
    assert q.product_id == p.id
    assert q.review_status == "ok"
