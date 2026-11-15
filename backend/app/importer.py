"""导入：CSV / JSON / 市场快照。

- 逐行处理、逐行落库：坏行单列，中断后按原文件（file_hash）续接；
- 列名表/单位表可换：重解析生成新 revision 批次试算，已选采购仍指向旧依据；
- 同号换值：同来源同报价编号、条款变化 -> 新 revision，旧记录保留；
- 名称相似只提候选，经审核的映射才归到标准品。
"""
import csv
import difflib
import hashlib
import io
import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from .models import (ImportBatch, ImportRow, MarketSnapshot, NameMapping,
                     Quote, StandardProduct)

DEFAULT_COLUMN_MAP = {
    "报价编号": "external_id",
    "来源": "source_name",
    "商品名": "raw_product_name",
    "等级": "grade",
    "产地": "origin",
    "适用区域": "region",
    "包装": "package_desc",
    "单位": "unit",
    "单件净重kg": "net_weight_per_unit_kg",
    "单件毛重kg": "gross_weight_per_unit_kg",
    "加工状态": "processing_status",
    "单价": "price_per_unit",
    "是否含税": "tax_included",
    "税率": "tax_rate",
    "有效期起": "valid_from",
    "有效期止": "valid_to",
    "起订量": "moq_quantity",
    "起订单位": "moq_unit",
    "交付方式": "delivery_mode",
    "到货天数": "lead_days",
    "费用规则": "fee_rules",
    "零价依据": "zero_price_basis",
}

DEFAULT_UNIT_TABLE = {"箱": "box", "盒": "box", "筐": "box", "公斤": "kg", "千克": "kg", "kg": "kg", "KG": "kg"}

SNAPSHOT_COLUMN_MAP = {
    "卖方": "seller",
    "商品名": "raw_product_name",
    "等级": "grade",
    "加工状态": "processing_status",
    "公斤价": "price_per_kg",
    "采集日期": "captured_at",
    "来源": "source_name",
    "转载自": "repost_of",
}

REQUIRED_FIELDS = ["source_name", "raw_product_name"]


def file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def terms_hash_of(fields: dict) -> str:
    keys = ["price_per_unit", "tax_included", "tax_rate", "fee_rules", "moq_quantity",
            "moq_unit", "valid_to", "unit", "net_weight_per_unit_kg",
            "gross_weight_per_unit_kg", "delivery_mode", "lead_days"]
    payload = json.dumps({k: fields.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def parse_bool(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip()
    if s in ("是", "true", "True", "1", "Y", "y"):
        return True
    if s in ("否", "false", "False", "0", "N", "n"):
        return False
    return None


def parse_float(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"数值无法解析: {v!r}")


def parse_date(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日期无法解析: {v!r}")


def normalize_row(raw: dict, column_map: dict) -> dict:
    """按列名表把原始行映射为标准字段；未映射列保留在 raw 中。"""
    fields = {}
    for col, val in (raw or {}).items():
        key = column_map.get(col)
        if key:
            fields[key] = val
    return fields


def validate_quote_fields(fields: dict, unit_table: dict):
    """返回 (clean_fields, pending_reasons)。解析失败抛 ValueError -> 坏行。"""
    clean = {}
    pending = []
    for req in REQUIRED_FIELDS:
        if not fields.get(req):
            raise ValueError(f"缺少必填字段: {req}")
    clean["source_name"] = str(fields["source_name"]).strip()
    clean["raw_product_name"] = str(fields["raw_product_name"]).strip()
    clean["external_id"] = (str(fields["external_id"]).strip()
                            if fields.get("external_id") else None)
    clean["grade"] = (str(fields["grade"]).strip() or None) if fields.get("grade") not in (None, "") else None
    if not clean["grade"]:
        pending.append("缺等级")
    clean["origin"] = fields.get("origin") or None
    clean["region"] = fields.get("region") or None
    clean["package_desc"] = fields.get("package") or fields.get("package_desc") or None
    clean["processing_status"] = fields.get("processing_status") or None

    unit_raw = (str(fields["unit"]).strip() if fields.get("unit") not in (None, "") else None)
    clean["unit_raw"] = unit_raw
    if not unit_raw:
        clean["unit"] = None
        pending.append("缺单位")
    elif unit_raw in unit_table:
        clean["unit"] = unit_table[unit_raw]
    else:
        clean["unit"] = None
        pending.append(f"单位无法识别: {unit_raw}")

    clean["net_weight_per_unit_kg"] = parse_float(fields.get("net_weight_per_unit_kg"))
    clean["gross_weight_per_unit_kg"] = parse_float(fields.get("gross_weight_per_unit_kg"))

    price = parse_float(fields.get("price_per_unit"))
    if price is None:
        raise ValueError("价格缺失（空值不能当零）")
    clean["price_per_unit"] = price

    clean["tax_included"] = parse_bool(fields.get("tax_included"))
    clean["tax_rate"] = parse_float(fields.get("tax_rate"))
    if clean["tax_included"] is None:
        pending.append("税费是否已含未声明，待补")

    clean["valid_from"] = parse_date(fields.get("valid_from"))
    clean["valid_to"] = parse_date(fields.get("valid_to"))
    clean["moq_quantity"] = parse_float(fields.get("moq_quantity"))
    clean["moq_unit"] = fields.get("moq_unit") or None
    clean["delivery_mode"] = fields.get("delivery_mode") or "配送"
    lead = fields.get("lead_days")
    clean["lead_days"] = int(parse_float(lead) or 0)

    fee_rules = fields.get("fee_rules")
    if isinstance(fee_rules, str) and fee_rules.strip():
        try:
            fee_rules = json.loads(fee_rules)
        except json.JSONDecodeError as e:
            raise ValueError(f"费用规则 JSON 无法解析: {e}")
    clean["fee_rules"] = fee_rules if isinstance(fee_rules, dict) else None

    clean["zero_price_basis"] = fields.get("zero_price_basis") or None
    if price == 0 and not clean["zero_price_basis"]:
        pending.append("零价缺免费依据")
    return clean, pending


def find_candidates(db: Session, raw_name: str):
    names = [p.name for p in db.query(StandardProduct).all()]
    matched = difflib.get_close_matches(raw_name, names, n=3, cutoff=0.3)
    products = {p.name: p for p in db.query(StandardProduct).all()}
    return [{"product_id": products[m].id, "name": m} for m in matched]


def get_or_create_mapping(db: Session, raw_name: str):
    mapping = db.query(NameMapping).filter_by(raw_name=raw_name).first()
    if not mapping:
        mapping = NameMapping(raw_name=raw_name, status="pending",
                              candidates=find_candidates(db, raw_name))
        db.add(mapping)
        db.flush()
    return mapping


def upsert_quote(db: Session, batch: ImportBatch, row_no: int, raw: dict,
                 clean: dict, pending: list, trial: bool = False) -> Quote:
    """同号换值 -> 新 revision；条款不变 -> 复用最新记录。
    trial=True（重解析试算）：只生成试算记录（is_latest=False），不动实时报价链。
    """
    mapping = get_or_create_mapping(db, clean["raw_product_name"])
    if mapping and mapping.status == "approved" and mapping.product_id:
        product_id, mapping_status = mapping.product_id, "mapped"
    else:
        product_id, mapping_status = None, "pending"
        if "商品名未映射" not in pending:
            pending.append("商品名未映射")

    clean["terms_hash"] = terms_hash_of(clean)
    clean["review_status"] = "pending" if pending else "ok"
    clean["pending_reasons"] = pending

    existing = None
    if clean.get("external_id") and not trial:
        existing = (db.query(Quote)
                    .filter_by(source_name=clean["source_name"],
                               external_id=clean["external_id"], is_latest=True)
                    .order_by(Quote.revision.desc()).first())
    if existing and existing.terms_hash == clean["terms_hash"]:
        return existing  # 幂等：同文件续接/重复导入不产生新记录

    quote = Quote(
        batch_id=batch.id, row_no=row_no, raw=raw,
        product_id=product_id, mapping_status=mapping_status,
        mapping_candidates=(mapping.candidates if mapping else None),
        parse_revision=batch.revision,
        is_latest=not trial,
        **clean,
    )
    if existing:
        existing.is_latest = False
        quote.revision = existing.revision + 1
        quote.supersedes_id = existing.id
    db.add(quote)
    db.flush()
    return quote


def parse_rows(kind: str, content: str):
    """把文件内容解析为 (row_no, raw_dict) 序列。"""
    if kind == "csv":
        reader = csv.DictReader(io.StringIO(content))
        return [(i + 2, dict(r)) for i, r in enumerate(reader)]  # 行号含表头
    data = json.loads(content)
    if kind == "snapshot":
        items = data.get("snapshots", data) if isinstance(data, dict) else data
    else:
        items = data.get("quotes", data) if isinstance(data, dict) else data
    return [(i + 1, item) for i, item in enumerate(items)]


def process_batch(db: Session, batch: ImportBatch, only_pending=True):
    """处理批次中未完成的行；逐行提交，中断可按原文件续接。"""
    rows = parse_rows(batch.kind, batch.file_content)
    done = {r.row_no for r in db.query(ImportRow).filter_by(batch_id=batch.id).all()
            if r.status == "ok"} if only_pending else set()
    column_map = batch.column_mapping or (SNAPSHOT_COLUMN_MAP if batch.kind == "snapshot"
                                          else DEFAULT_COLUMN_MAP)
    unit_table = batch.unit_table or DEFAULT_UNIT_TABLE
    trial = (batch.revision or 1) > 1  # 重解析批次只试算，不进实时链

    for row_no, raw in rows:
        if row_no in done:
            continue
        try:
            fields = normalize_row(raw, column_map)
            if batch.kind == "snapshot":
                snap = _import_snapshot_row(db, batch, fields)
                db.add(ImportRow(batch_id=batch.id, row_no=row_no, status="ok",
                                 raw=raw))
            else:
                clean, pending = validate_quote_fields(fields, unit_table)
                quote = upsert_quote(db, batch, row_no, raw, clean, pending,
                                     trial=trial)
                db.add(ImportRow(batch_id=batch.id, row_no=row_no, status="ok",
                                 raw=raw, quote_id=quote.id))
        except Exception as e:  # 坏行单列，不中断整批
            db.add(ImportRow(batch_id=batch.id, row_no=row_no, status="bad",
                             raw=raw, error=str(e)[:500]))
        db.commit()  # 逐行提交：中断后可续接
    _refresh_batch_status(db, batch)


def _import_snapshot_row(db: Session, batch: ImportBatch, fields: dict):
    if not fields.get("seller"):
        raise ValueError("缺少卖方")
    price = parse_float(fields.get("price_per_kg"))
    if price is None:
        raise ValueError("快照价格缺失")
    product_id = None
    raw_name = fields.get("raw_product_name")
    if raw_name:
        mapping = db.query(NameMapping).filter_by(
            raw_name=str(raw_name).strip(), status="approved").first()
        product_id = mapping.product_id if mapping else None
    repost_of = None
    if fields.get("repost_of") not in (None, ""):
        repost_of = int(parse_float(fields.get("repost_of")))
    snap = MarketSnapshot(
        batch_id=batch.id,
        seller=str(fields["seller"]).strip(),
        raw_product_name=raw_name,
        product_id=product_id,
        grade=fields.get("grade") or None,
        processing_status=fields.get("processing_status") or None,
        price_per_kg=price,
        captured_at=parse_date(fields.get("captured_at")) or date.today(),
        source_name=fields.get("source_name") or None,
        repost_of=repost_of,
    )
    db.add(snap)
    db.flush()
    return snap


def _refresh_batch_status(db: Session, batch: ImportBatch):
    rows = db.query(ImportRow).filter_by(batch_id=batch.id).all()
    batch.ok_rows = sum(1 for r in rows if r.status == "ok")
    batch.bad_rows = sum(1 for r in rows if r.status == "bad")
    batch.total_rows = batch.ok_rows + batch.bad_rows
    expected = len(parse_rows(batch.kind, batch.file_content))
    batch.status = "completed" if batch.total_rows >= expected else "partial"
    db.commit()


def create_batch(db: Session, filename: str, content: str, kind: str,
                 column_mapping=None, unit_table=None) -> ImportBatch:
    h = file_hash(content)
    existing = (db.query(ImportBatch).filter_by(file_hash=h)
                .order_by(ImportBatch.revision.desc()).first())
    if existing and existing.status == "completed":
        return existing  # 同文件已完成 -> 幂等返回
    if existing:
        return existing  # 未完成 -> 由 resume 续接
    batch = ImportBatch(filename=filename, file_hash=h, kind=kind,
                        column_mapping=column_mapping, unit_table=unit_table,
                        file_content=content, status="processing")
    db.add(batch)
    db.commit()
    return batch


def reparse_batch(db: Session, batch: ImportBatch, column_mapping=None,
                  unit_table=None) -> ImportBatch:
    """列名表/单位表变更后重新解析试算：生成新 revision 批次，旧批次与旧依据不动。"""
    new_batch = ImportBatch(
        filename=batch.filename, file_hash=batch.file_hash, kind=batch.kind,
        column_mapping=column_mapping or batch.column_mapping,
        unit_table=unit_table or batch.unit_table,
        revision=batch.revision + 1, parent_batch_id=batch.id,
        file_content=batch.file_content, status="processing",
    )
    db.add(new_batch)
    db.commit()
    process_batch(db, new_batch, only_pending=False)
    return new_batch
