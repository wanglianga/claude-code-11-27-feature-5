"""导入测试：坏行单列、待核、同号换值、续接、重解析。"""
import json

from app.importer import (DEFAULT_COLUMN_MAP, DEFAULT_UNIT_TABLE, create_batch,
                          process_batch, reparse_batch, validate_quote_fields)
from app.models import ImportBatch, ImportRow, Quote


def test_validate_missing_price_is_bad():
    fields = {"source_name": "s", "raw_product_name": "土豆", "price_per_unit": None}
    try:
        validate_quote_fields(fields, DEFAULT_UNIT_TABLE)
        assert False, "应抛错"
    except ValueError as e:
        assert "价格缺失" in str(e)


def test_validate_zero_price_needs_basis():
    fields = {"source_name": "s", "raw_product_name": "土豆", "price_per_unit": 0,
              "unit": "公斤", "tax_included": "是"}
    _, pending = validate_quote_fields(fields, DEFAULT_UNIT_TABLE)
    assert any("零价" in p for p in pending)


def test_validate_missing_unit_and_grade_pending():
    fields = {"source_name": "s", "raw_product_name": "土豆", "price_per_unit": 2,
              "tax_included": "是"}
    clean, pending = validate_quote_fields(fields, DEFAULT_UNIT_TABLE)
    assert clean["unit"] is None
    assert "缺单位" in pending and "缺等级" in pending


def test_validate_missing_tax_field_pending():
    fields = {"source_name": "s", "raw_product_name": "土豆", "price_per_unit": 2,
              "unit": "公斤", "grade": "一级"}
    _, pending = validate_quote_fields(fields, DEFAULT_UNIT_TABLE)
    assert any("税费" in p for p in pending)


CSV = """报价编号,来源,商品名,等级,单位,单价,是否含税,有效期止
Q-1,供应商A,土豆,一级,公斤,2.0,是,2026-12-31
Q-2,供应商A,土豆,一级,公斤,,是,2026-12-31
Q-3,供应商A,土豆,一级,公斤,2.2,是,2026-12-31
"""


def test_import_bad_rows_listed(db):
    batch = create_batch(db, "t.csv", CSV, "csv")
    process_batch(db, batch)
    assert batch.status == "completed"
    assert batch.ok_rows == 2 and batch.bad_rows == 1
    bad = db.query(ImportRow).filter_by(batch_id=batch.id, status="bad").one()
    assert bad.row_no == 3  # 第 2 条数据行（含表头行号 3）
    assert "价格缺失" in bad.error


def test_import_resume_idempotent(db):
    batch = create_batch(db, "t.csv", CSV, "csv")
    process_batch(db, batch)
    n_quotes = db.query(Quote).count()
    # 同文件再次导入 -> 幂等，不产生新报价
    batch2 = create_batch(db, "t.csv", CSV, "csv")
    assert batch2.id == batch.id
    process_batch(db, batch2)
    assert db.query(Quote).count() == n_quotes


def test_same_external_id_new_values_keeps_revision(db):
    batch = create_batch(db, "t.csv", CSV, "csv")
    process_batch(db, batch)
    changed = CSV.replace("Q-1,供应商A,土豆,一级,公斤,2.0", "Q-1,供应商A,土豆,一级,公斤,2.5")
    batch2 = create_batch(db, "t2.csv", changed, "csv")
    process_batch(db, batch2)
    q1 = db.query(Quote).filter_by(external_id="Q-1", is_latest=False).one()
    q2 = db.query(Quote).filter_by(external_id="Q-1", is_latest=True).one()
    assert q1.price_per_unit == 2.0 and q2.price_per_unit == 2.5
    assert q2.revision == q1.revision + 1
    assert q2.supersedes_id == q1.id


def test_reparse_creates_new_revision_batch(db):
    batch = create_batch(db, "t.csv", CSV, "csv")
    process_batch(db, batch)
    new_map = dict(DEFAULT_COLUMN_MAP)
    new_map["货源"] = "source_name"
    new_batch = reparse_batch(db, batch, column_mapping=new_map)
    assert new_batch.revision == batch.revision + 1
    assert new_batch.parent_batch_id == batch.id
    assert new_batch.status == "completed"


def test_reparse_trial_does_not_touch_live_chain(db):
    """重解析试算只生成试算记录，不改变实时报价链。"""
    batch = create_batch(db, "t.csv", CSV, "csv")
    process_batch(db, batch)
    live_before = {q.external_id: q.id for q in db.query(Quote).filter_by(is_latest=True)}
    new_batch = reparse_batch(db, batch, unit_table={"箱": "box", "公斤": "kg"})
    live_after = {q.external_id: q.id for q in db.query(Quote).filter_by(is_latest=True)}
    assert live_before == live_after  # 实时链未变
    trial_quotes = (db.query(Quote)
                    .filter(Quote.batch_id == new_batch.id, Quote.is_latest.is_(False))
                    .all())
    assert len(trial_quotes) == 2  # 试算记录保留在批次下可查
    assert all(q.parse_revision == new_batch.revision for q in trial_quotes)


def test_json_import_and_pending_queue(db):
    from app.models import NameMapping, StandardProduct
    p = StandardProduct(name="土豆")
    db.add(p)
    db.flush()
    db.add(NameMapping(raw_name="土豆", product_id=p.id, status="approved"))
    db.commit()
    payload = json.dumps({"quotes": [
        {"报价编号": "J-1", "来源": "B", "商品名": "土豆", "等级": "一级",
         "单位": "公斤", "单价": 2.0, "是否含税": "是"},
        {"报价编号": "J-2", "来源": "B", "商品名": "洋芋", "等级": "一级",
         "单位": "公斤", "单价": 2.0, "是否含税": "是"},
    ]}, ensure_ascii=False)
    batch = create_batch(db, "t.json", payload, "json")
    process_batch(db, batch)
    assert batch.ok_rows == 2
    pending = db.query(Quote).filter_by(review_status="pending").all()
    assert len(pending) == 1 and pending[0].raw_product_name == "洋芋"
