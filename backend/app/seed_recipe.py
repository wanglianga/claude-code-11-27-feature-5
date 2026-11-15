"""feature-5 种子数据：食谱成本事实关联与变化解释。

覆盖题目要求的五类验收样例：
1. 配方改版：酸辣土豆丝 V1(2026-11-01) -> V2(2026-11-10)，份量与净用量调整；
2. 单位换算缺失：农家炖菜的「秘制酱料」食谱单位为「坛」，映射无换算依据；
3. 等级失配：清炒白菜心要求一级大白菜，系统只有二级带根毛菜的出成率证据，
   且存在一级毛重包装报价 -> 不计算可用成本，登记质量事件；
4. 迟到出成率：番茄炒蛋的西红柿 V1 餐期只有历史估计出成率，报表发布后补传抽样实测，
   生成引用原餐期快照的影响版本；
5. 同名原料误映射：「山药」V1 映射到土豆（同名误映射），V2 改映射到真正的山药标准品，
   且 V1/V2 生效边界同为 2026-11-10，构造同一生效时刻冲突，保留双候选待确认。

所有报价/标准品/出成率均显式登记，不依赖隐式默认值。
"""
from datetime import date

from sqlalchemy.orm import Session

from .models import (Dish, IngredientMapping, Quote, StandardProduct,
                     YieldEvidence)
from .recipe import (bridge_costs, build_meal_snapshot, create_mapping,
                     create_recipe_version, register_measured_yield)

# 统一使用的加工状态与区域
REGION = "中央厨房"


def seed_recipe_domain(db: Session):
    if db.query(Dish).first():
        return False

    products = {p.name: p for p in db.query(StandardProduct).all()}
    potato = products["土豆"]
    tomato = products["西红柿"]
    cabbage = products["大白菜"]
    carrot = products["胡萝卜"]
    # 新增标准品：山药（与土豆区分，用于同名误映射修订）、鸡蛋（含过敏原）
    yam = StandardProduct(name="山药", category="根茎类",
                          note="标准品：山药；历史上“山药”曾被误映射到土豆")
    egg_product = StandardProduct(name="鸡蛋", category="禽蛋类",
                                  note="标准品：鸡蛋，含蛋类过敏原")
    db.add_all([yam, egg_product])
    db.flush()

    # ------------------------------------------------------------------ 菜品
    dishes = {
        "potato": Dish(code="DISH-PT-01", name="酸辣土豆丝", region=REGION,
                       note="演示配方改版"),
        "stew": Dish(code="DISH-ST-01", name="农家炖菜", region=REGION,
                     note="演示单位换算缺失"),
        "cabbage": Dish(code="DISH-CB-01", name="清炒白菜心", region=REGION,
                        note="演示等级失配"),
        "egg": Dish(code="DISH-EG-01", name="番茄炒蛋", region=REGION,
                    note="演示迟到出成率"),
        "yam": Dish(code="DISH-YM-01", name="蓝莓山药泥", region=REGION,
                    note="演示同名原料误映射与生效时刻冲突"),
    }
    db.add_all(dishes.values())
    db.flush()

    # ------------------------------------------------------- 补充演示用报价
    _add_feature_quotes(db, potato, tomato, cabbage, yam, egg_product)
    # ------------------------------------------------------- 出成率证据账
    _add_yield_evidences(db, potato, tomato, cabbage, yam, carrot)
    # ------------------------------------------------------- 原料语义映射
    _add_ingredient_mappings(db, potato, tomato, cabbage, yam, egg_product, carrot)
    # ------------------------------------------------------------- 食谱版本
    _add_recipes(db, dishes)
    db.commit()

    # ------------------------------------------------------- 装配餐期快照
    snaps = _build_snapshots(db, dishes)
    # ------------------------------------------------------- 成本桥（固定顺序分解）
    # 土豆丝 V1->V2：份量/单份净用量变化；番茄炒蛋 V1->V2：仅西红柿报价上涨
    bridge_costs(db, snaps["potato_v1"].id, snaps["potato_v2"].id)
    bridge_costs(db, snaps["egg_v1"].id, snaps["egg_v2"].id)
    # ------------------------------------------------------- 迟到证据影响版本
    _late_yield_impact(db, tomato, snaps["egg_v1"])
    db.commit()
    return True


def _add_feature_quotes(db, potato, tomato, cabbage, yam, egg_product):
    """在既有随题报价之外，登记 feature-5 需要的等级/区域/净菜报价。"""
    base = dict(
        batch_id=_ensure_batch(db).id, row_no=1, source_name="中央厨房采购组",
        mapping_status="mapped", is_latest=True, revision=1, review_status="ok",
        pending_reasons=[], tax_included=True, delivery_mode="配送", lead_days=0,
        fee_rules=None,
    )
    rows = [
        # 土豆 一级 净菜（中央厨房区域），供酸辣土豆丝选价
        dict(external_id="Q-R-PT-N1", product_id=potato.id, raw_product_name="土豆",
             grade="一级", processing_status="净菜", unit="kg", unit_raw="公斤",
             price_per_unit=2.28, valid_from=date(2026, 11, 1),
             valid_to=date(2026, 12, 31), region=REGION),
        # 土豆 一级 带泥毛菜 箱装（报价上涨：V2 餐期价格更高）
        dict(external_id="Q-R-PT-G2", product_id=potato.id, raw_product_name="土豆",
             grade="一级", processing_status="带泥毛菜", unit="box", unit_raw="箱",
             net_weight_per_unit_kg=20.0, gross_weight_per_unit_kg=21.0,
             price_per_unit=35.0, valid_from=date(2026, 11, 1),
             valid_to=date(2026, 11, 9), region=REGION),
        dict(external_id="Q-R-PT-G3", product_id=potato.id, raw_product_name="土豆",
             grade="一级", processing_status="带泥毛菜", unit="box", unit_raw="箱",
             net_weight_per_unit_kg=20.0, gross_weight_per_unit_kg=21.0,
             price_per_unit=38.5, valid_from=date(2026, 11, 10),
             valid_to=date(2026, 12, 31), region=REGION),
        # 西红柿 一级 带泥毛菜（粗加工），演示估计/实测出成率；两版报价演示价格上涨
        dict(external_id="Q-R-TM-G1", product_id=tomato.id, raw_product_name="西红柿",
             grade="一级", processing_status="带泥毛菜", unit="box", unit_raw="箱",
             net_weight_per_unit_kg=15.0, gross_weight_per_unit_kg=16.0,
             price_per_unit=45.0, valid_from=date(2026, 11, 1),
             valid_to=date(2026, 11, 9), region=REGION),
        dict(external_id="Q-R-TM-G2", product_id=tomato.id, raw_product_name="西红柿",
             grade="一级", processing_status="带泥毛菜", unit="box", unit_raw="箱",
             net_weight_per_unit_kg=15.0, gross_weight_per_unit_kg=16.0,
             price_per_unit=49.5, valid_from=date(2026, 11, 10),
             valid_to=date(2026, 12, 31), region=REGION),
        # 大白菜 一级 带根毛菜 箱装（一级报价存在，但一级出成率证据缺失）
        dict(external_id="Q-R-CB-G1", product_id=cabbage.id, raw_product_name="大白菜",
             grade="一级", processing_status="带根毛菜", unit="box", unit_raw="筐",
             net_weight_per_unit_kg=15.0, gross_weight_per_unit_kg=16.0,
             price_per_unit=18.0, valid_from=date(2026, 11, 1),
             valid_to=date(2026, 12, 31), region=REGION),
        # 山药 一级 净菜
        dict(external_id="Q-R-YM-N1", product_id=yam.id, raw_product_name="山药",
             grade="一级", processing_status="净菜", unit="kg", unit_raw="公斤",
             price_per_unit=5.6, valid_from=date(2026, 11, 1),
             valid_to=date(2026, 12, 31), region=REGION),
        # 鸡蛋 一级 净菜（含蛋类过敏原，已在映射标注）
        dict(external_id="Q-R-EG-N1", product_id=egg_product.id, raw_product_name="鸡蛋",
             grade="一级", processing_status="净菜", unit="kg", unit_raw="公斤",
             price_per_unit=9.8, valid_from=date(2026, 11, 1),
             valid_to=date(2026, 12, 31), region=REGION),
    ]
    for kw in rows:
        db.add(Quote(**{**base, **kw}))
    db.flush()


def _ensure_batch(db):
    from .models import ImportBatch
    batch = (db.query(ImportBatch)
             .filter(ImportBatch.filename == "feature5_recipe_seed").first())
    if not batch:
        batch = ImportBatch(filename="feature5_recipe_seed",
                            file_hash="feature5-recipe-seed", kind="json",
                            status="completed", total_rows=0, ok_rows=0,
                            bad_rows=0, file_content="")
        db.add(batch)
        db.flush()
    return batch


def _add_yield_evidences(db, potato, tomato, cabbage, yam, carrot):
    # 土豆 一级 带泥毛菜：历史估计（标注非验收事实）+ 较早抽样实测
    db.add_all([
        YieldEvidence(product_id=potato.id, grade="一级",
                      processing_status="带泥毛菜", evidence_kind="estimated",
                      lower=0.78, upper=0.85,
                      note="历史估计（非验收实测，不得伪装成验收事实）"),
        YieldEvidence(product_id=potato.id, grade="一级",
                      processing_status="带泥毛菜", evidence_kind="measured",
                      point=0.8, lower=0.8, upper=0.8,
                      sample_batch="YP-202610-03", measured_at=date(2026, 10, 20),
                      note="2026-10 抽样实测 3 批次"),
        # 西红柿 一级 带泥毛菜：先只有历史估计（迟到实测在快照发布后补传）
        YieldEvidence(product_id=tomato.id, grade="一级",
                      processing_status="带泥毛菜", evidence_kind="estimated",
                      lower=0.72, upper=0.8,
                      note="历史估计（等待验收实测补传）"),
        # 大白菜：只有二级带根毛菜证据，一级证据缺失 -> 一级要求触发等级失配
        YieldEvidence(product_id=cabbage.id, grade="二级",
                      processing_status="带根毛菜", evidence_kind="measured",
                      point=0.7, lower=0.7, upper=0.7,
                      sample_batch="YP-202610-CB2", measured_at=date(2026, 10, 18),
                      note="二级大白菜抽样实测；一级证据缺失"),
        # 胡萝卜 一级 带泥毛菜：历史估计（保证炖菜除酱料外可计价）
        YieldEvidence(product_id=carrot.id, grade="一级",
                      processing_status="带泥毛菜", evidence_kind="estimated",
                      lower=0.8, upper=0.88,
                      note="历史估计（2026-09 实测区间沿用）"),
        # 山药/鸡蛋 净菜无需出成率
    ])
    db.flush()


def _add_ingredient_mappings(db, potato, tomato, cabbage, yam, egg_product, carrot):
    d0, d1 = date(2026, 11, 1), date(2026, 11, 10)
    kg = {"to_kg": {"kg": 1.0, "g": 0.001}, "basis": "公制标准换算"}

    # 土豆丝：土豆（一级净菜），完整映射；桥接主要演示份量/配方结构变化
    create_mapping(db, "土豆丝用料", potato.id, d0, grade="一级",
                   processing_status="净菜", purchase_code="PUR-PT-01",
                   composition_code="COMP-VEG-01", allergen_tags=[],
                   conversion=kg, allergen_mapped=True,
                   note="土豆标准语义映射（净菜口径）")
    # 炖菜：土豆/胡萝卜（带泥毛菜，需要出成率）
    create_mapping(db, "炖菜土豆", potato.id, d0, grade="一级",
                   processing_status="带泥毛菜", purchase_code="PUR-PT-01",
                   composition_code="COMP-VEG-01", allergen_tags=[],
                   conversion=kg, allergen_mapped=True)
    create_mapping(db, "炖菜胡萝卜", carrot.id, d0, grade="一级",
                   processing_status="带泥毛菜", purchase_code="PUR-CR-01",
                   composition_code="COMP-VEG-02", allergen_tags=[],
                   conversion=kg, allergen_mapped=True)
    # 秘制酱料：单位「坛」且无换算依据 -> 单位换算缺失样例；过敏原也未映射
    create_mapping(db, "秘制酱料", None, d0, grade=None,
                   processing_status=None, purchase_code=None,
                   composition_code="COMP-SAUCE-99", allergen_tags=[],
                   conversion=None, allergen_mapped=False,
                   note="供应商配方保密，单位坛与kg的换算依据缺失")
    # 白菜心：一级 带根毛菜（证据只有二级 -> 等级失配）
    create_mapping(db, "白菜心", cabbage.id, d0, grade="一级",
                   processing_status="带根毛菜", purchase_code="PUR-CB-01",
                   composition_code="COMP-VEG-02", allergen_tags=[],
                   conversion=kg, allergen_mapped=True)
    # 番茄炒蛋：西红柿 带泥毛菜 + 鸡蛋（净菜，含过敏原）
    create_mapping(db, "番茄", tomato.id, d0, grade="一级",
                   processing_status="带泥毛菜", purchase_code="PUR-TM-01",
                   composition_code="COMP-VEG-03", allergen_tags=[],
                   conversion=kg, allergen_mapped=True)
    create_mapping(db, "鸡蛋", egg_product.id, d0, grade="一级",
                   processing_status="净菜", purchase_code="PUR-EG-01",
                   composition_code="COMP-EG-01", allergen_tags=["蛋类"],
                   conversion=kg, allergen_mapped=True,
                   note="鸡蛋含蛋类过敏原，已标注")

    # 山药：V1 误映射到土豆（effective 11-01 起），V2 改映射到山药
    # 两版边界同为 11-10 -> 同一生效时刻冲突，build 时保留双候选
    create_mapping(db, "山药", potato.id, d0, grade="一级",
                   processing_status="净菜", purchase_code="PUR-PT-01",
                   composition_code="COMP-VEG-01", allergen_tags=[],
                   conversion=kg, allergen_mapped=True,
                   note="【误映射】山药被错误指向土豆标准品")
    create_mapping(db, "山药", yam.id, d1, grade="一级",
                   processing_status="净菜", purchase_code="PUR-YM-01",
                   composition_code="COMP-VEG-YM", allergen_tags=[],
                   conversion=kg, allergen_mapped=True,
                   note="修订：山药正确指向山药标准品")


def _add_recipes(db, dishes):
    d0, d1 = date(2026, 11, 1), date(2026, 11, 10)

    # 1) 酸辣土豆丝：V1 -> V2 配方改版（份数 100 -> 120，土豆净用量调整；两版均可完整解释）
    create_recipe_version(
        db, dishes["potato"].id, "2026-11 上旬午餐", 100, d0,
        [{"ingredient_name": "土豆丝用料", "net_qty": 15.0, "net_unit": "kg"}],
        source_ref="RCP-PT-V1", note="V1 初版")
    create_recipe_version(
        db, dishes["potato"].id, "2026-11 中旬午餐", 120, d1,
        [{"ingredient_name": "土豆丝用料", "net_qty": 21.6, "net_unit": "kg"}],
        source_ref="RCP-PT-V2", note="V2 改版：份数增加，单份净用量下调（15kg/100份 -> 21.6kg/120份）")

    # 2) 农家炖菜：秘制酱料以「坛」计且无换算依据
    create_recipe_version(
        db, dishes["stew"].id, "2026-11 午餐", 80, d0,
        [{"ingredient_name": "炖菜土豆", "net_qty": 10.0, "net_unit": "kg"},
         {"ingredient_name": "炖菜胡萝卜", "net_qty": 6.0, "net_unit": "kg"},
         {"ingredient_name": "秘制酱料", "net_qty": 2.0, "net_unit": "坛"}],
        source_ref="RCP-ST-V1")

    # 3) 清炒白菜心：一级要求但只有二级证据 -> 等级失配
    create_recipe_version(
        db, dishes["cabbage"].id, "2026-11 午餐", 60, d0,
        [{"ingredient_name": "白菜心", "net_qty": 12.0, "net_unit": "kg"}],
        source_ref="RCP-CB-V1")

    # 4) 番茄炒蛋：V1 估计出成率 -> 迟到实测；V2 仅西红柿报价上涨（份量不变），用于价格桥
    create_recipe_version(
        db, dishes["egg"].id, "2026-11 上旬午餐", 90, d0,
        [{"ingredient_name": "番茄", "net_qty": 9.0, "net_unit": "kg"},
         {"ingredient_name": "鸡蛋", "net_qty": 4.5, "net_unit": "kg"}],
        source_ref="RCP-EG-V1")
    create_recipe_version(
        db, dishes["egg"].id, "2026-11 中旬午餐", 90, d1,
        [{"ingredient_name": "番茄", "net_qty": 9.0, "net_unit": "kg"},
         {"ingredient_name": "鸡蛋", "net_qty": 4.5, "net_unit": "kg"}],
        source_ref="RCP-EG-V2", note="V2：份量与净用量不变，西红柿箱价 45->49.5 元")

    # 5) 蓝莓山药泥：山药在 11-10 处于两版映射边界 -> 冲突双候选
    create_recipe_version(
        db, dishes["yam"].id, "2026-11 中旬午餐", 50, d1,
        [{"ingredient_name": "山药", "net_qty": 8.0, "net_unit": "kg"}],
        source_ref="RCP-YM-V1")


def _build_snapshots(db, dishes):
    """返回各演示餐期快照；命名与验收样例对应。"""
    out = {}
    out["potato_v1"] = build_meal_snapshot(
        db, dishes["potato"].id, date(2026, 11, 5), "2026-11 上旬午餐",
        created_by="seed", published=True)
    out["potato_v2"] = build_meal_snapshot(
        db, dishes["potato"].id, date(2026, 11, 12), "2026-11 中旬午餐",
        created_by="seed", published=True)
    out["stew_v1"] = build_meal_snapshot(
        db, dishes["stew"].id, date(2026, 11, 5), "2026-11 午餐",
        created_by="seed", published=True)
    out["cabbage_v1"] = build_meal_snapshot(
        db, dishes["cabbage"].id, date(2026, 11, 5), "2026-11 午餐",
        created_by="seed", published=True)
    out["egg_v1"] = build_meal_snapshot(
        db, dishes["egg"].id, date(2026, 11, 5), "2026-11 上旬午餐",
        created_by="seed", published=True)
    out["egg_v2"] = build_meal_snapshot(
        db, dishes["egg"].id, date(2026, 11, 12), "2026-11 中旬午餐",
        created_by="seed", published=True)
    out["yam_conflict"] = build_meal_snapshot(
        db, dishes["yam"].id, date(2026, 11, 10), "2026-11 中旬午餐",
        created_by="seed", published=True)
    return out


def _late_yield_impact(db, tomato, egg_snapshot):
    """报表发布后补传西红柿一级带泥毛菜的抽样实测 -> 影响版本。"""
    register_measured_yield(
        db, product_id=tomato.id, grade="一级",
        processing_status="带泥毛菜", point=0.68,
        sample_batch="YP-202611-TM07", measured_at=date(2026, 11, 13),
        created_by="checker01",
        note="报表 11-12 发布后，11-13 补传的验收抽样实测")
