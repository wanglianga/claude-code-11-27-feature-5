"""feature-5 测试：食谱成本事实关联与变化解释。

覆盖五类验收样例：配方改版、单位换算缺失、等级失配、迟到出成率、同名原料误映射；
并校验：快照只读、桥接固定顺序且贡献和=总差额、冲突双候选、覆盖质量。
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app.models import (Dish, ImportBatch, IngredientMapping, MappingConflict,
                        PriceSelectionSnapshot, Quote, StandardProduct,
                        YieldEvidence)
from app.recipe import (BRIDGE_ORDER, build_meal_snapshot, bridge_costs,
                        create_mapping, create_recipe_version,
                        register_measured_yield, resolve_conflict,
                        resolve_recipe, coverage_overview)

KG = {"to_kg": {"kg": 1.0, "g": 0.001}, "basis": "公制标准换算"}
D0, D1, D2 = date(2026, 11, 1), date(2026, 11, 10), date(2026, 11, 12)


# --------------------------------------------------------------------- 夹具

def _batch(db):
    b = ImportBatch(filename="t", file_hash=f"h-{id(db)}", kind="json",
                    status="completed", file_content="")
    db.add(b)
    db.flush()
    return b


def make_product(db, name):
    p = StandardProduct(name=name)
    db.add(p)
    db.flush()
    return p


def make_quote(db, product, external_id, price, grade="一级",
               processing_status="净菜", unit="kg", pack_net=None,
               pack_gross=None, region="中央厨房", valid_from=D0,
               valid_to=date(2026, 12, 31), review_status="ok",
               pending=None):
    q = Quote(
        batch_id=_batch(db).id, source_name="测试供应商", external_id=external_id,
        revision=1, is_latest=True, raw_product_name=product.name,
        product_id=product.id, mapping_status="mapped", grade=grade,
        processing_status=processing_status, unit=unit,
        unit_raw="箱" if unit == "box" else "公斤",
        net_weight_per_unit_kg=pack_net, gross_weight_per_unit_kg=pack_gross,
        price_per_unit=price, tax_included=True, valid_from=valid_from,
        valid_to=valid_to, region=region, delivery_mode="配送", lead_days=0,
        review_status=review_status, pending_reasons=pending or [])
    db.add(q)
    db.flush()
    return q


def make_evidence(db, product, grade, processing_status, kind, **kw):
    e = YieldEvidence(product_id=product.id, grade=grade,
                      processing_status=processing_status,
                      evidence_kind=kind, **kw)
    db.add(e)
    db.flush()
    return e


def make_dish(db, name="测试菜", code=None, region="中央厨房"):
    d = Dish(code=code or f"D-{name}", name=name, region=region)
    db.add(d)
    db.flush()
    return d


def events_of(snap):
    return {e.event_type for e in snap.events}


def line_named(snap, name):
    return next(l for l in snap.lines if l.ingredient_name == name)


# ---------------------------------------------------------- 1. 食谱版本解析器

def test_recipe_version_resolution_and_revision_chain(db):
    dish = make_dish(db)
    r1 = create_recipe_version(db, dish.id, "餐期A", 100, D0,
                               [{"ingredient_name": "A", "net_qty": 10, "net_unit": "kg"}])
    r2 = create_recipe_version(db, dish.id, "餐期B", 120, D1,
                               [{"ingredient_name": "A", "net_qty": 12, "net_unit": "kg"}])
    assert r2.revision == 2 and r2.supersedes_id == r1.id
    db.refresh(r1)
    assert r1.effective_to == D1  # 旧版本在新生效日收口
    assert resolve_recipe(db, dish.id, D0).id == r1.id
    assert resolve_recipe(db, dish.id, date(2026, 11, 9)).id == r1.id
    assert resolve_recipe(db, dish.id, D1).id == r2.id


def test_recipe_rejects_earlier_effective_date(db):
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "A", 100, D1,
                          [{"ingredient_name": "A", "net_qty": 1, "net_unit": "kg"}])
    with pytest.raises(HTTPException):
        create_recipe_version(db, dish.id, "B", 100, D0,
                              [{"ingredient_name": "A", "net_qty": 1, "net_unit": "kg"}])


# ---------------------------------------------------------- 2. 完整可解释链路

def test_full_explainable_snapshot_freezes_facts(db):
    p = make_product(db, "净菜A")
    make_quote(db, p, "Q1", 2.0)
    create_mapping(db, "原料A", p.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 100, D0,
                          [{"ingredient_name": "原料A", "net_qty": 10, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    assert snap.fully_explainable is True
    assert snap.status == "active"
    line = snap.lines[0]
    assert line.explainable and line.line_cost == 20.0
    assert snap.total_unit_cost == 0.2  # 20 元 / 100 份
    assert line.price_basis["quote_id"] is not None
    assert line.conversion_chain[0]["to"] == "kg"


# ---------------------------------------------------------- 3. 缺净用量

def test_missing_net_qty_marks_unexplained_without_fill(db):
    p = make_product(db, "净菜B")
    make_quote(db, p, "Q1", 2.0)
    create_mapping(db, "原料B", p.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D0,
                          [{"ingredient_name": "原料B", "net_qty": None,
                            "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    assert snap.fully_explainable is False
    line = snap.lines[0]
    assert line.line_cost is None and line.quote_id is None
    assert "missing_net_qty" in events_of(snap)
    assert "食谱缺少原料净用量" in line.unexplained_reasons


# ---------------------------------------------------------- 4. 单位换算缺失

def test_missing_conversion_blocks_cost(db):
    p = make_product(db, "酱料品")
    make_quote(db, p, "Q1", 10.0)
    create_mapping(db, "秘制酱料", p.id, D0, conversion=None, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D0,
                          [{"ingredient_name": "秘制酱料", "net_qty": 2,
                            "net_unit": "坛"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    line = line_named(snap, "秘制酱料")
    assert line.explainable is False and line.line_cost is None
    assert "missing_conversion" in events_of(snap)
    assert "单位换算依据缺失" in line.unexplained_reasons


def test_missing_allergen_marks_unexplained(db):
    p = make_product(db, "净菜C")
    make_quote(db, p, "Q1", 3.0)
    create_mapping(db, "原料C", p.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=False)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D0,
                          [{"ingredient_name": "原料C", "net_qty": 5, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    assert snap.fully_explainable is False
    assert "missing_allergen" in events_of(snap)


# ---------------------------------------------------------- 5. 等级失配

def test_grade_mismatch_blocks_usable_cost(db):
    p = make_product(db, "白菜")
    # 一级毛重包装报价存在
    make_quote(db, p, "Q-G1", 18.0, processing_status="带根毛菜",
               unit="box", pack_net=15, pack_gross=16)
    # 但只有二级证据
    make_evidence(db, p, "二级", "带根毛菜", "measured", point=0.7,
                  sample_batch="CB2")
    create_mapping(db, "白菜心", p.id, D0, grade="一级",
                   processing_status="带根毛菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 60, D0,
                          [{"ingredient_name": "白菜心", "net_qty": 12, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    line = line_named(snap, "白菜心")
    assert line.explainable is False and line.line_cost is None
    ev = next(e for e in snap.events if e.event_type == "grade_mismatch")
    assert "失配" in ev.detail and "Q-G1" in ev.detail  # 明确指出毛重报价不得折算


def test_missing_yield_uses_no_default(db):
    p = make_product(db, "毛菜D")
    make_quote(db, p, "Q1", 20.0, processing_status="带泥毛菜",
               unit="box", pack_net=20, pack_gross=21)
    create_mapping(db, "原料D", p.id, D0, grade="一级",
                   processing_status="带泥毛菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D0,
                          [{"ingredient_name": "原料D", "net_qty": 8, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    assert "missing_yield" in events_of(snap)
    assert line_named(snap, "原料D").line_cost is None  # 不补默认出成率


# ---------------------------------------------------------- 6. 价格选择器

def test_quote_selector_region_and_validity(db):
    p = make_product(db, "净菜E")
    make_quote(db, p, "Q-NORTH", 1.0, region="北区")          # 区域不符
    make_quote(db, p, "Q-EXPIRED", 1.1, valid_to=D0)          # 已过期
    make_quote(db, p, "Q-GENERIC", 2.5, region=None)          # 通用，应被选中
    create_mapping(db, "原料E", p.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db, region="中央厨房")
    create_recipe_version(db, dish.id, "午餐", 10, D0,
                          [{"ingredient_name": "原料E", "net_qty": 4, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    assert line_named(snap, "原料E").price_basis["external_id"] == "Q-GENERIC"


# ---------------------------------------------------------- 7. 快照只读

def test_snapshot_is_readonly_after_master_data_changes(db):
    p = make_product(db, "净菜F")
    q = make_quote(db, p, "Q1", 2.0)
    m = create_mapping(db, "原料F", p.id, D0, grade="一级",
                       processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 100, D0,
                          [{"ingredient_name": "原料F", "net_qty": 10, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    frozen_price = snap.lines[0].price_basis["price_per_unit"]

    # 事后改报价与映射换算依据
    q.price_per_unit = 99.0
    m.conversion = {"to_kg": {"kg": 999.0}, "basis": "被篡改"}
    db.commit()
    db.refresh(snap)
    assert snap.lines[0].price_basis["price_per_unit"] == frozen_price == 2.0
    assert snap.lines[0].conversion_chain[0]["factor"] == 1.0


# ---------------------------------------------------------- 8. 迟到出成率

def test_late_measured_yield_creates_impact_version(db):
    p = make_product(db, "番茄")
    make_quote(db, p, "Q1", 45.0, processing_status="带泥毛菜",
               unit="box", pack_net=15, pack_gross=16)
    make_evidence(db, p, "一级", "带泥毛菜", "estimated", lower=0.75, upper=0.8)
    create_mapping(db, "番茄", p.id, D0, grade="一级",
                   processing_status="带泥毛菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 90, D0,
                          [{"ingredient_name": "番茄", "net_qty": 9, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐", published=True)
    line = line_named(snap, "番茄")
    assert line.yield_evidence_kind == "estimated"  # 估计值不伪装成实测
    old_cost = line.line_cost

    result = register_measured_yield(
        db, p.id, "一级", "带泥毛菜", 0.68, "YP-TM07", D2, created_by="checker01")
    assert result["affected_snapshots"] == 1
    impact = snap.impacts[0]
    assert impact.old_yield == 0.75 and impact.new_yield == 0.68
    assert impact.old_yield_kind == "estimated"
    assert impact.cost_delta == round(impact.new_line_cost - impact.old_line_cost, 2)
    assert impact.new_line_cost > old_cost  # 出成率下降 -> 成本上升
    # 原快照行保持只读不变
    db.refresh(line)
    assert line.line_cost == old_cost and line.yield_value == 0.75


# ---------------------------------------------------------- 9. 冲突双候选

def test_effective_time_conflict_keeps_dual_candidates(db):
    p1 = make_product(db, "土豆X")
    p2 = make_product(db, "山药X")
    make_quote(db, p1, "Q-P1", 2.0)
    make_quote(db, p2, "Q-P2", 5.0)
    # V1 -> 土豆X；V2 -> 山药X，边界同为 D1
    create_mapping(db, "山药", p1.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True,
                   note="误映射")
    create_mapping(db, "山药", p2.id, D1, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True,
                   note="正确映射")
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D1,
                          [{"ingredient_name": "山药", "net_qty": 8, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    assert snap.status == "conflicted"
    assert snap.fully_explainable is False
    conflict = db.query(MappingConflict).filter_by(snapshot_id=snap.id).first()
    assert conflict is not None and conflict.status == "pending"
    assert conflict.candidate_a["product_id"] == p1.id
    assert conflict.candidate_b["product_id"] == p2.id

    # 管理员确认候选 b（正确映射）-> 旧快照 superseded，新快照可解释
    new_snap = resolve_conflict(db, conflict.id, "b", "admin")
    db.refresh(snap)
    assert snap.status == "superseded"
    assert new_snap.id != snap.id and new_snap.fully_explainable is True
    assert line_named(new_snap, "山药").product_id == p2.id
    db.refresh(conflict)
    assert conflict.status == "resolved" and conflict.resolution == "b"


def test_resolved_conflict_cannot_re_resolve(db):
    p1 = make_product(db, "土豆Y")
    p2 = make_product(db, "山药Y")
    make_quote(db, p1, "Q1", 2.0)
    make_quote(db, p2, "Q2", 5.0)
    create_mapping(db, "山药", p1.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    create_mapping(db, "山药", p2.id, D1, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D1,
                          [{"ingredient_name": "山药", "net_qty": 8, "net_unit": "kg"}])
    snap = build_meal_snapshot(db, dish.id, D1, "午餐")
    conflict = db.query(MappingConflict).filter_by(snapshot_id=snap.id).first()
    resolve_conflict(db, conflict.id, "a", "admin")
    with pytest.raises(HTTPException):
        resolve_conflict(db, conflict.id, "b", "admin")


# --------------------------------------------------------- 10. 成本桥接器

def test_bridge_fixed_order_and_consistency(db):
    p = make_product(db, "桥接净菜")
    make_quote(db, p, "Q1", 2.0, valid_to=date(2026, 11, 9))
    make_quote(db, p, "Q2", 2.5, valid_from=D1)
    create_mapping(db, "主料", p.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "上旬", 100, D0,
                          [{"ingredient_name": "主料", "net_qty": 10, "net_unit": "kg"}])
    create_recipe_version(db, dish.id, "中旬", 120, D1,
                          [{"ingredient_name": "主料", "net_qty": 15, "net_unit": "kg"}])
    s1 = build_meal_snapshot(db, dish.id, date(2026, 11, 5), "上旬")
    s2 = build_meal_snapshot(db, dish.id, D2, "中旬")
    bridge = bridge_costs(db, s1.id, s2.id)
    assert [s["factor"] for s in bridge.steps] == BRIDGE_ORDER
    assert bridge.consistent is True
    # 手算：单位成本 0.2 -> 0.3125，总差额 0.1125
    assert bridge.base_unit_cost == 0.2
    assert bridge.target_unit_cost == 0.3125
    assert bridge.total_delta == round(0.3125 - 0.2, 4)
    portion = next(s for s in bridge.steps if s["factor"] == "份量")
    price = next(s for s in bridge.steps if s["factor"] == "价格")
    assert portion["contribution"] == 0.05       # 15*2/120 - 10*2/100
    assert price["contribution"] == 0.0625       # 15*(2.5-2)/120


def test_bridge_mapping_step_captures_wrong_mapping_revision(db):
    p1 = make_product(db, "旧品")
    p2 = make_product(db, "新品")
    make_quote(db, p1, "Q1", 2.0)
    make_quote(db, p2, "Q2", 3.0)
    create_mapping(db, "同名料", p1.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    create_mapping(db, "同名料", p2.id, D1, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    # 两版映射边界 D1：分别在边界前/后建快照，各只命中一条
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 100, D0,
                          [{"ingredient_name": "同名料", "net_qty": 10, "net_unit": "kg"}])
    s1 = build_meal_snapshot(db, dish.id, date(2026, 11, 5), "午餐")
    s2 = build_meal_snapshot(db, dish.id, D2, "午餐")
    assert line_named(s1, "同名料").product_id == p1.id
    assert line_named(s2, "同名料").product_id == p2.id
    bridge = bridge_costs(db, s1.id, s2.id)
    mapping_step = next(s for s in bridge.steps if s["factor"] == "映射")
    assert mapping_step["detail"]["changes"][0]["product_to"] == p2.id
    assert bridge.total_delta == 0.1  # (3-2)*10/100
    assert bridge.consistent is True


def test_bridge_rejects_incomparable_periods(db):
    p = make_product(db, "毛菜Z")
    make_quote(db, p, "Q1", 20.0, processing_status="带泥毛菜",
               unit="box", pack_net=20, pack_gross=21)
    create_mapping(db, "料Z", p.id, D0, grade="一级",
                   processing_status="带泥毛菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 50, D0,
                          [{"ingredient_name": "料Z", "net_qty": 8, "net_unit": "kg"}])
    s_bad = build_meal_snapshot(db, dish.id, D1, "午餐")  # 缺出成率
    with pytest.raises(HTTPException) as ei:
        bridge_costs(db, s_bad.id, s_bad.id)
    assert ei.value.status_code == 409


def test_yield_factor_bridge_step(db):
    p = make_product(db, "毛菜Y")
    make_quote(db, p, "Q1", 20.0, processing_status="带泥毛菜",
               unit="box", pack_net=20, pack_gross=21)
    make_evidence(db, p, "一级", "带泥毛菜", "estimated", lower=0.8, upper=0.8)
    create_mapping(db, "料Y", p.id, D0, grade="一级",
                   processing_status="带泥毛菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db)
    create_recipe_version(db, dish.id, "午餐", 100, D0,
                          [{"ingredient_name": "料Y", "net_qty": 8, "net_unit": "kg"}])
    s1 = build_meal_snapshot(db, dish.id, date(2026, 11, 5), "午餐")
    # 补一条更晚的实测证据（出成率下降），再建第二份快照
    make_evidence(db, p, "一级", "带泥毛菜", "measured", point=0.7,
                  sample_batch="YP-1", measured_at=D2)
    s2 = build_meal_snapshot(db, dish.id, D2, "午餐")
    bridge = bridge_costs(db, s1.id, s2.id)
    ystep = next(s for s in bridge.steps if s["factor"] == "出成率")
    assert ystep["detail"]["changes"][0]["from"] == 0.8
    assert ystep["detail"]["changes"][0]["to"] == 0.7
    assert ystep["contribution"] > 0  # 出成率下降推高单位成本
    assert bridge.consistent is True


# --------------------------------------------------------- 11. 覆盖质量 + API

def test_coverage_overview_lists_missing_evidence(db):
    p = make_product(db, "净菜G")
    make_quote(db, p, "Q1", 2.0)
    create_mapping(db, "料G", p.id, D0, conversion=None, allergen_mapped=True)
    dish = make_dish(db, name="覆盖菜")
    create_recipe_version(db, dish.id, "午餐", 50, D0,
                          [{"ingredient_name": "料G", "net_qty": 2, "net_unit": "坛"}])
    build_meal_snapshot(db, dish.id, D1, "午餐")
    overview = coverage_overview(db)
    row = next(r for r in overview if r["dish_id"] == dish.id)
    assert row["fully_explainable"] is False
    assert any(m["type"] == "missing_conversion" for m in row["missing_evidence"])
    assert len(row["incomparable_periods"]) == 1


def test_api_snapshot_conflict_and_coverage_flow(client, db, buyer_headers):
    p1 = StandardProduct(name="API土豆")
    p2 = StandardProduct(name="API山药")
    db.add_all([p1, p2])
    db.flush()
    make_quote(db, p1, "AQ1", 2.0)
    make_quote(db, p2, "AQ2", 5.0)
    create_mapping(db, "API山药", p1.id, D0, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    create_mapping(db, "API山药", p2.id, D1, grade="一级",
                   processing_status="净菜", conversion=KG, allergen_mapped=True)
    dish = make_dish(db, name="API菜", code="DISH-API")
    create_recipe_version(db, dish.id, "午餐", 50, D1,
                          [{"ingredient_name": "API山药", "net_qty": 8,
                            "net_unit": "kg"}])
    # 未登录 401
    r = client.post("/api/snapshots",
                    json={"dish_id": dish.id, "serving_date": D1.isoformat(),
                          "meal_period": "午餐"})
    assert r.status_code == 401
    # 建快照 -> 冲突
    r = client.post("/api/snapshots", headers=buyer_headers,
                    json={"dish_id": dish.id, "serving_date": D1.isoformat(),
                          "meal_period": "午餐"})
    assert r.status_code == 200 and r.json()["status"] == "conflicted"
    conflicts = client.get("/api/mapping-conflicts").json()
    assert conflicts and conflicts[0]["status"] == "pending"
    # 确认 b
    r = client.post(f"/api/mapping-conflicts/{conflicts[0]['id']}/resolve",
                    headers=buyer_headers, json={"choice": "b"})
    assert r.status_code == 200 and r.json()["fully_explainable"] is True
    # 覆盖质量
    cov = client.get("/api/coverage").json()
    assert any(c["dish_id"] == dish.id for c in cov)
    # 成本桥接：两个可解释快照（冲突重建后）
    snaps = client.get("/api/snapshots", params={"dish_id": dish.id}).json()
    explainable_ids = [s["id"] for s in snaps if s["fully_explainable"]]
    # 再建一个正常餐期用于桥接
    r2 = client.post("/api/snapshots", headers=buyer_headers,
                     json={"dish_id": dish.id, "serving_date": D2.isoformat(),
                           "meal_period": "午餐"})
    assert r2.json()["fully_explainable"] is True
    bridge = client.post("/api/cost-bridges", headers=buyer_headers,
                         json={"base_snapshot_id": r2.json()["id"],
                               "target_snapshot_id": explainable_ids[0]}).json()
    assert bridge["consistent"] is True
