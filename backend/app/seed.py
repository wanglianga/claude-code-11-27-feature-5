"""种子数据：标准品、出成率、已审核映射、测试账号、随题样例导入、演示用采购依据。

样例覆盖：整箱舍入、阶梯运费、同名异等级、到货后可用率降低（演示验收）。
"""
import os
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from .importer import create_batch, process_batch
from .models import (Acceptance, NameMapping, Quote, StandardProduct, User,
                     YieldRate)
from .services import create_decision

SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", Path(__file__).resolve().parents[2] / "samples"))


def seed_if_empty(db: Session):
    if db.query(User).first():
        return False

    db.add_all([
        User(username="admin", password="admin123", display_name="系统管理员", role="admin"),
        User(username="buyer01", password="buyer123", display_name="采购员小王", role="buyer"),
        User(username="checker01", password="check123", display_name="验收员小李", role="checker"),
    ])

    products = {
        "土豆": StandardProduct(name="土豆", category="根茎类", note="标准品：土豆"),
        "西红柿": StandardProduct(name="西红柿", category="茄果类"),
        "大白菜": StandardProduct(name="大白菜", category="叶菜类"),
        "胡萝卜": StandardProduct(name="胡萝卜", category="根茎类"),
    }
    db.add_all(products.values())
    db.flush()

    db.add_all([
        YieldRate(product_id=products["土豆"].id, from_state="带泥毛菜", to_state="净菜",
                  lower=0.78, upper=0.85, evidence="2026-10 食堂实测 3 批次去泥去皮"),
        YieldRate(product_id=products["大白菜"].id, from_state="带根毛菜", to_state="净菜",
                  lower=0.70, upper=0.80, evidence="2026-10 实测去根去老叶"),
        YieldRate(product_id=products["胡萝卜"].id, from_state="带泥毛菜", to_state="净菜",
                  lower=0.80, upper=0.88, evidence="2026-09 实测"),
        # 西红柿缺测：演示“缺出成率实测 -> 展示原价而不猜净菜率”
    ])

    # 已审核映射（“洋芋”故意留待审核，演示候选流程）
    for raw, prod in [("土豆", "土豆"), ("马铃薯", "土豆"), ("西红柿", "西红柿"),
                      ("大白菜", "大白菜"), ("胡萝卜", "胡萝卜")]:
        db.add(NameMapping(raw_name=raw, product_id=products[prod].id,
                           status="approved", revision=1, reviewed_by="admin"))
    db.commit()

    for fname in ("quotes_supplier_a.csv", "quotes_supplier_b.json", "market_snapshot.json"):
        content = (SAMPLES_DIR / fname).read_text(encoding="utf-8")
        kind = "csv" if fname.endswith(".csv") else ("snapshot" if "snapshot" in fname else "json")
        batch = create_batch(db, fname, content, kind)
        process_batch(db, batch)

    _seed_demo_decision(db, products["土豆"].id)
    db.commit()
    return True


def _seed_demo_decision(db: Session, potato_id: int):
    """演示：采用宏发箱装土豆 -> 验收时单价上涨、短装、出成率降低。"""
    quote = (db.query(Quote)
             .filter(Quote.external_id == "Q-A-001", Quote.is_latest.is_(True))
             .first())
    if not quote:
        return
    decision = create_decision(db, quote.id, "net", 100, created_by="buyer01",
                               today=date(2026, 11, 10))
    db.add(Acceptance(
        decision_id=decision.id, trip_no="鲁Q·D1234",
        received_weight_kg=135, actual_unit_price=36, actual_grade="一级",
        returned_weight_kg=3, grade_rejected_weight_kg=2,
        actual_yield=0.74,
        note="到货后可用率降低：泥占比高，实测出成率 0.74 低于计划区间下界 0.78",
        created_by="checker01",
    ))
    db.commit()
