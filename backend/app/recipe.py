"""食谱成本事实关联与变化解释（feature-5 核心域）。

五个职责，与题目逐一对齐：
1. 食谱版本解析器 resolve_recipe：菜品/餐期/份数/原料净用量/修订生效时间 -> 可追溯配方事实；
2. 原料语义映射器 resolve_mapping_candidates：采购编码、成分编码、等级、过敏原标签、单位换算依据；
3. 出成率证据账 resolve_yield：抽样实测 / 历史估计 / 缺失三态分明，估计不伪装成验收事实；
4. 价格选择器 select_quote：按等级、加工状态、适用区域、有效区间筛选，采用的报价/来源批次/
   换算依据固化进只读的餐期选价快照 PriceSelectionSnapshot；
5. 成本桥接器 bridge_costs：在固定快照上按 份量->价格->出成率->规格->映射 固定顺序分解。

硬规则（任何情况下不得违反）：
- 缺净用量 / 缺单位换算 / 缺过敏原映射 -> 该菜列为“成本不可完整解释”，不用同名原料或默认值补齐；
- 报价只给毛重包装而出成率证据来自不同等级 -> 不计算可用成本，登记“等级失配”质量事件；
- 迟到的实测出成率 -> 生成引用原餐期快照的影响版本，原估计与新证据差额分别保留；
- 食谱版本与映射版本在同一生效时刻冲突 -> 保留两套候选关联，等待人工确认，不按上传时间覆盖。
"""
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import (CostBridge, Dish, IngredientMapping, MappingConflict,
                     PriceSelectionSnapshot, QualityEvent, Quote, RecipeItem,
                     RecipeVersion, SnapshotImpactVersion, SnapshotLine,
                     StandardProduct, YieldEvidence)

# 桥接固定分解顺序；顺序改变归因结果会改变，故集中定义、禁止调用方调整
BRIDGE_ORDER = ["份量", "价格", "出成率", "规格", "映射"]


def r2(x):
    return None if x is None else round(float(x) + 0.0, 2)


def r4(x):
    return None if x is None else round(float(x) + 0.0, 4)


# ---------------------------------------------------------------------------
# 1. 食谱版本解析器
# ---------------------------------------------------------------------------

def resolve_recipe(db: Session, dish_id: int, on_date: date) -> RecipeVersion | None:
    """取 on_date 当天生效的食谱版本（effective_from <= 当天 < effective_to）。"""
    return (db.query(RecipeVersion)
            .filter(RecipeVersion.dish_id == dish_id,
                    RecipeVersion.effective_from <= on_date,
                    (RecipeVersion.effective_to.is_(None))
                    | (RecipeVersion.effective_to > on_date))
            .order_by(RecipeVersion.revision.desc())
            .first())


def create_recipe_version(db: Session, dish_id: int, meal_period: str, servings: float,
                          effective_from: date, items: list[dict],
                          source_ref: str | None = None,
                          note: str | None = None) -> RecipeVersion:
    """新建食谱版本；同菜品旧版本在新生效日自动收口（effective_to 回填）。"""
    if not db.get(Dish, dish_id):
        raise HTTPException(404, "菜品不存在")
    if servings <= 0:
        raise HTTPException(400, "份数必须为正")
    prev = (db.query(RecipeVersion)
            .filter(RecipeVersion.dish_id == dish_id)
            .order_by(RecipeVersion.revision.desc()).first())
    revision = (prev.revision + 1) if prev else 1
    if prev and prev.effective_from >= effective_from:
        raise HTTPException(400, "新版本生效时间必须晚于上一版本")
    recipe = RecipeVersion(
        dish_id=dish_id, revision=revision, meal_period=meal_period,
        servings=servings, effective_from=effective_from,
        supersedes_id=prev.id if prev else None,
        source_ref=source_ref, note=note,
    )
    db.add(recipe)
    db.flush()
    for i, it in enumerate(items, start=1):
        net_qty = it.get("net_qty")
        if net_qty is not None and net_qty <= 0:
            raise HTTPException(400, f"第 {i} 行净用量必须为正；缺失请传 null")
        db.add(RecipeItem(
            recipe_id=recipe.id, line_no=i,
            ingredient_name=it["ingredient_name"],
            net_qty=net_qty, net_unit=it.get("net_unit"),
            note=it.get("note"),
        ))
    if prev:
        prev.effective_to = effective_from
    db.commit()
    db.refresh(recipe)
    return recipe


# ---------------------------------------------------------------------------
# 2. 原料语义映射器（含同一生效时刻的冲突双候选）
# ---------------------------------------------------------------------------

def resolve_mapping_candidates(db: Session, ingredient_name: str,
                               on_date: date) -> list[IngredientMapping]:
    """返回当天适用的映射候选。

    边界日采用“含头含尾”判定：旧版本 effective_to 与新版本 effective_from 为同一天时，
    两个版本在该生效时刻同时成立 -> 返回两条候选，交数据管理员确认，不按上传时间覆盖。
    非边界日正常只有一条。
    """
    rows = (db.query(IngredientMapping)
            .filter(IngredientMapping.ingredient_name == ingredient_name,
                    IngredientMapping.status == "active",
                    IngredientMapping.effective_from <= on_date,
                    (IngredientMapping.effective_to.is_(None))
                    | (IngredientMapping.effective_to >= on_date))
            .order_by(IngredientMapping.revision.asc())
            .all())
    # 同一生效时刻的版本去重（正常区间内不应重叠；重叠即冲突）
    unique = {}
    for m in rows:
        unique.setdefault(m.id, m)
    return list(unique.values())


def create_mapping(db: Session, ingredient_name: str, product_id: int | None,
                   effective_from: date, grade: str | None = None,
                   processing_status: str | None = None,
                   purchase_code: str | None = None,
                   composition_code: str | None = None,
                   allergen_tags: list | None = None,
                   conversion: dict | None = None,
                   allergen_mapped: bool = False,
                   note: str | None = None) -> IngredientMapping:
    """新建映射版本；旧版本在新生效日收口（保留同一天边界，供冲突检测）。"""
    if product_id is not None and not db.get(StandardProduct, product_id):
        raise HTTPException(404, "标准品不存在")
    prev = (db.query(IngredientMapping)
            .filter(IngredientMapping.ingredient_name == ingredient_name,
                    IngredientMapping.status == "active")
            .order_by(IngredientMapping.revision.desc()).first())
    revision = (prev.revision + 1) if prev else 1
    m = IngredientMapping(
        ingredient_name=ingredient_name, revision=revision, product_id=product_id,
        purchase_code=purchase_code, composition_code=composition_code, grade=grade,
        allergen_tags=allergen_tags or [], processing_status=processing_status,
        conversion=conversion, allergen_mapped=allergen_mapped,
        effective_from=effective_from, supersedes_id=prev.id if prev else None,
        note=note,
    )
    db.add(m)
    if prev:
        prev.effective_to = effective_from  # 与新版本同一天 -> 边界冲突可被检出
    db.commit()
    db.refresh(m)
    return m


# ---------------------------------------------------------------------------
# 3. 出成率证据账（measured / estimated / missing 三态）
# ---------------------------------------------------------------------------

def resolve_yield(db: Session, product_id: int, grade: str | None,
                  processing_status: str | None) -> YieldEvidence | None:
    """按 产品+等级+加工状态 取出成率证据；实测优先于估计；缺失返回 None。

    注意：本函数只做“同等级”精确匹配。跨等级证据由价格选择器判为等级失配，
    不得拿来折算可用成本。
    """
    if not processing_status or processing_status == "净菜":
        return None  # 净菜无需出成率换算，调用方按 1.0 处理
    rows = (db.query(YieldEvidence)
            .filter(YieldEvidence.product_id == product_id,
                    YieldEvidence.grade == grade,
                    YieldEvidence.processing_status == processing_status,
                    YieldEvidence.evidence_kind.in_(["measured", "estimated"]))
            .all())
    measured = [e for e in rows if e.evidence_kind == "measured"]
    pool = measured or rows
    if not pool:
        return None
    return sorted(pool, key=lambda e: e.id, reverse=True)[0]


def yield_point(ev: YieldEvidence | None) -> float | None:
    """证据采用值：实测单值优先，否则取区间下界（保守）。"""
    if ev is None:
        return None
    if ev.point is not None:
        return ev.point
    return ev.lower


def find_cross_grade_evidence(db: Session, product_id: int, grade: str | None,
                              processing_status: str) -> YieldEvidence | None:
    """查找不同等级但同加工状态的证据：仅用于等级失配提示，绝不参与折算。"""
    return (db.query(YieldEvidence)
            .filter(YieldEvidence.product_id == product_id,
                    YieldEvidence.processing_status == processing_status,
                    YieldEvidence.grade != grade)
            .order_by(YieldEvidence.id.desc()).first())


# ---------------------------------------------------------------------------
# 4. 价格选择器
# ---------------------------------------------------------------------------

def select_quote(db: Session, product_id: int, grade: str | None,
                 processing_status: str | None, region: str | None,
                 on_date: date) -> tuple[Quote | None, list[str]]:
    """筛选符合 等级/加工状态/适用区域/有效区间 的候选报价。

    区域规则：报价 region 为空表示不限区域（通用），否则必须与菜品区域一致。
    返回 (采用报价, 排除说明列表)；无候选时报价为 None。
    """
    quotes = (db.query(Quote)
              .filter(Quote.product_id == product_id, Quote.is_latest.is_(True))
              .order_by(Quote.id).all())
    candidates, reasons = [], []
    for q in quotes:
        why = []
        if q.review_status == "pending":
            why.append("报价待核（" + "、".join(q.pending_reasons or []) + "）")
        if q.grade != grade:
            why.append(f"等级不符：要求 {grade}，报价 {q.grade or '缺等级'}")
        if q.processing_status != processing_status:
            why.append(f"加工状态不符：要求 {processing_status}，报价 {q.processing_status}")
        if q.region and region and q.region != region:
            why.append(f"适用区域不符：要求 {region}，报价限 {q.region}")
        if q.valid_from and q.valid_from > on_date:
            why.append(f"报价 {q.valid_from} 才生效")
        if q.valid_to and q.valid_to < on_date:
            why.append(f"报价已于 {q.valid_to} 过期")
        if why:
            reasons.append(f"[{q.source_name} {q.external_id or q.id}] " + "；".join(why))
        else:
            candidates.append(q)
    if not candidates:
        return None, reasons
    # 候选均为同等级同状态，按折算后的净用量单价择优（折算依据随快照固化）
    best, best_cost = None, None
    for q in candidates:
        c = _gross_price_per_kg(q)
        if c is not None and (best_cost is None or c < best_cost):
            best, best_cost = q, c
    return best, reasons


def _tax_factor(q: Quote) -> float:
    """税费口径：未含税按税率加计一次；已含不重复；待核报价不会进入候选。"""
    if q.tax_included is False and q.tax_rate:
        return 1.0 + float(q.tax_rate)
    return 1.0


def _gross_price_per_kg(q: Quote) -> float | None:
    """含税毛重单价（元/毛kg）；箱价按单件净重折算。"""
    tf = _tax_factor(q)
    if q.unit == "box":
        if not q.net_weight_per_unit_kg:
            return None
        return q.price_per_unit * tf / q.net_weight_per_unit_kg
    if q.unit == "kg":
        return q.price_per_unit * tf
    return None


def net_price_per_kg(q: Quote, yield_value: float | None) -> float | None:
    """含税净用量单价（元/净kg）：毛重单价 / 出成率；净菜出成率按 1。"""
    gross = _gross_price_per_kg(q)
    if gross is None:
        return None
    y = yield_value if yield_value is not None else 1.0
    if not y:
        return None
    return gross / y


def _to_kg(qty: float | None, unit: str | None, conversion: dict | None) -> tuple[float | None, list[dict]]:
    """把食谱净用量换算为 kg；缺换算依据时返回 None，调用方登记质量事件而非猜默认值。"""
    chain = []
    if qty is None or not unit:
        return None, chain
    if unit == "kg":
        return float(qty), [{"from": "kg", "to": "kg", "factor": 1.0, "basis": "基准单位"}]
    if unit == "g":
        return float(qty) / 1000.0, [
            {"from": "g", "to": "kg", "factor": 0.001, "basis": "公制标准换算 1kg=1000g"}]
    # 非标准单位必须提供映射换算依据
    if not conversion:
        return None, chain
    factors = conversion.get("to_kg") or conversion.get("factors")
    if not factors or unit not in factors:
        return None, chain
    factor = float(factors[unit])
    return float(qty) * factor, [
        {"from": unit, "to": "kg", "factor": factor,
         "basis": conversion.get("basis") or "原料语义映射登记的单位换算依据"}]


# ---------------------------------------------------------------------------
# 5. 餐期选价快照（只读事实装配）
# ---------------------------------------------------------------------------

def build_meal_snapshot(db: Session, dish_id: int, serving_date: date,
                        meal_period: str, created_by: str | None = None,
                        force_mapping_id: int | None = None,
                        published: bool = False) -> PriceSelectionSnapshot:
    """为某菜品某餐期装配只读选价快照。

    force_mapping_id 用于冲突确认后按管理员选择重建；正常流程不传。
    """
    dish = db.get(Dish, dish_id)
    if not dish:
        raise HTTPException(404, "菜品不存在")
    recipe = resolve_recipe(db, dish_id, serving_date)
    if not recipe:
        raise HTTPException(404, f"{serving_date} 无生效食谱版本")

    snap = PriceSelectionSnapshot(
        dish_id=dish_id, recipe_id=recipe.id, meal_period=meal_period,
        serving_date=serving_date, servings=recipe.servings,
        status="active", published_at=datetime.utcnow() if published else None,
    )
    db.add(snap)
    db.flush()

    explained_cost = 0.0
    explainable_lines = 0
    conflicted = False

    for item in recipe.items:
        line = SnapshotLine(
            snapshot_id=snap.id, recipe_item_id=item.id,
            ingredient_name=item.ingredient_name, net_qty=item.net_qty,
            net_unit=item.net_unit, explainable=False,
            unexplained_reasons=[],
        )
        db.add(line)
        db.flush()
        reasons = line.unexplained_reasons or []

        # (a) 缺净用量：直接不可完整解释，不补齐
        if item.net_qty is None:
            reasons.append("食谱缺少原料净用量")
            _event(db, snap, line, "missing_net_qty", item.ingredient_name,
                   f"食谱行 #{item.line_no}「{item.ingredient_name}」缺净用量，"
                   "不用同名原料或默认值补齐")
            line.unexplained_reasons = reasons
            continue

        # (b) 语义映射（含冲突双候选）
        if force_mapping_id:
            mappings = [m for m in resolve_mapping_candidates(
                db, item.ingredient_name, serving_date) if m.id == force_mapping_id]
            if not mappings:
                forced = db.get(IngredientMapping, force_mapping_id)
                mappings = [forced] if forced else []
        else:
            mappings = resolve_mapping_candidates(db, item.ingredient_name, serving_date)

        if not mappings:
            reasons.append("原料语义映射缺失")
            _event(db, snap, line, "mapping_missing", item.ingredient_name,
                   f"「{item.ingredient_name}」在 {serving_date} 无生效语义映射")
            line.unexplained_reasons = reasons
            continue
        if len(mappings) > 1:
            # 同一生效时刻冲突：两套候选都保留，等待人工确认
            conflicted = True
            cand_a, cand_b = mappings[0], mappings[1]
            db.add(MappingConflict(
                snapshot_id=snap.id, recipe_item_id=item.id,
                ingredient_name=item.ingredient_name, effective_at=serving_date,
                candidate_a=_mapping_candidate(cand_a),
                candidate_b=_mapping_candidate(cand_b),
                note="食谱版本与原料映射版本在同一生效时刻相互冲突，"
                     "保留两套候选关联，不按最后上传时间覆盖",
            ))
            reasons.append("生效时刻映射冲突，待数据管理员确认")
            _event(db, snap, line, "mapping_conflict", item.ingredient_name,
                   "两套映射候选同一生效时刻成立，已挂起待确认")
            line.unexplained_reasons = reasons
            continue

        mapping = mappings[0]
        line.mapping_id = mapping.id
        line.product_id = mapping.product_id
        line.required_grade = mapping.grade
        line.required_processing = mapping.processing_status

        # (c) 过敏原映射缺失：不可完整解释（硬规则）
        if not mapping.allergen_mapped:
            reasons.append("过敏原映射缺失")
            _event(db, snap, line, "missing_allergen", item.ingredient_name,
                   f"「{item.ingredient_name}」缺过敏原标签映射，"
                   "不得用同名原料的过敏原信息补齐", severity="warning")

        # (d) 单位换算：把成品净用量折到 kg
        net_kg, conv_chain = _to_kg(item.net_qty, item.net_unit, mapping.conversion)
        if net_kg is None:
            reasons.append("单位换算依据缺失")
            _event(db, snap, line, "missing_conversion", item.ingredient_name,
                   f"净用量单位 {item.net_unit} 无换算依据，不能折算采购口径")
            line.unexplained_reasons = reasons
            continue
        line.conversion_chain = conv_chain

        if not mapping.product_id:
            reasons.append("映射未关联采购编码（标准品）")
            _event(db, snap, line, "mapping_missing", item.ingredient_name,
                   "映射存在但未关联采购编码，无法选价")
            line.unexplained_reasons = reasons
            continue

        # (e) 出成率证据账：同等级精确匹配，跨等级只作失配提示
        is_gross = bool(mapping.processing_status and mapping.processing_status != "净菜")
        ev = resolve_yield(db, mapping.product_id, mapping.grade,
                           mapping.processing_status) if is_gross else None
        yv = yield_point(ev)
        if is_gross and ev is None:
            cross = find_cross_grade_evidence(
                db, mapping.product_id, mapping.grade, mapping.processing_status)
            if cross:
                # 等级失配：报价即使给毛重包装也不得计算可用成本
                gross_quote, _ = select_quote(
                    db, mapping.product_id, mapping.grade,
                    mapping.processing_status, dish.region, serving_date)
                quote_text = (f"；毛重包装报价 {gross_quote.external_id} 因此不得折算可用成本"
                              if gross_quote else "")
                reasons.append("出成率证据等级失配")
                _event(db, snap, line, "grade_mismatch", item.ingredient_name,
                       f"仅找到 {cross.grade} 等级的出成率证据（{cross.evidence_kind}，"
                       f"批次 {cross.sample_batch or cross.note or '无'}），"
                       f"与要求等级 {mapping.grade} 失配{quote_text}")
                line.unexplained_reasons = reasons
                continue
            reasons.append("出成率证据缺失（不猜默认值）")
            _event(db, snap, line, "missing_yield", item.ingredient_name,
                   "同等级同加工状态无任何出成率证据，缺失值不补默认出成率")
            line.unexplained_reasons = reasons
            continue

        # (f) 价格选择器：等级/加工状态/区域/有效区间
        quote, exclude_reasons = select_quote(
            db, mapping.product_id, mapping.grade, mapping.processing_status,
            dish.region, serving_date)
        if not quote:
            reasons.append("无符合等级/状态/区域/有效期的候选报价")
            _event(db, snap, line, "quote_not_found", item.ingredient_name,
                   "价格选择器无可用候选；筛选过程："
                   + ("；".join(exclude_reasons) or "无报价记录"))
            line.unexplained_reasons = reasons
            continue

        # 毛重包装 + 证据等级已在上面精确匹配；此处双保险：
        # 报价为毛重包装而证据来自别的等级 -> 拒绝折算（理论上不会走到，防御性保留）
        if is_gross and ev and ev.grade != mapping.grade:
            reasons.append("出成率证据等级失配")
            _event(db, snap, line, "grade_mismatch", item.ingredient_name,
                   "出成率证据等级与报价等级不一致，不计算可用成本")
            line.unexplained_reasons = reasons
            continue

        net_unit_price = net_price_per_kg(quote, yv)
        if net_unit_price is None:
            reasons.append("报价缺包装净重，无法换算")
            _event(db, snap, line, "missing_conversion", item.ingredient_name,
                   f"报价 {quote.external_id} 缺单件净重")
            line.unexplained_reasons = reasons
            continue

        line.quote_id = quote.id
        line.quote_grade = quote.grade
        line.quote_processing = quote.processing_status
        line.yield_evidence_id = ev.id if ev else None
        line.yield_value = yv
        line.yield_evidence_kind = ev.evidence_kind if ev else None
        line.price_basis = {
            "quote_id": quote.id,
            "external_id": quote.external_id,
            "quote_revision": quote.revision,
            "source_batch_id": quote.batch_id,
            "source_name": quote.source_name,
            "price_per_unit": quote.price_per_unit,
            "unit": quote.unit,
            "unit_raw": quote.unit_raw,
            "net_weight_per_unit_kg": quote.net_weight_per_unit_kg,
            "gross_weight_per_unit_kg": quote.gross_weight_per_unit_kg,
            "tax_included": quote.tax_included,
            "tax_rate": quote.tax_rate,
            "tax_factor": _tax_factor(quote),
            "gross_price_per_kg": r4(_gross_price_per_kg(quote)),
            "net_price_per_kg": r4(net_unit_price),
            "valid_from": quote.valid_from.isoformat() if quote.valid_from else None,
            "valid_to": quote.valid_to.isoformat() if quote.valid_to else None,
            "region": quote.region,
            "selected_at": datetime.utcnow().isoformat(),
        }
        line.conversion_chain = conv_chain + [{
            "from": "毛重kg", "to": "净用量kg",
            "factor": r4(yv) if yv is not None else 1.0,
            "basis": (f"出成率证据 #{ev.id}（{ev.evidence_kind}："
                      f"{ev.sample_batch or ev.note or '区间下界'}）") if ev
            else "净菜无需出成率换算",
        }]
        line_cost = net_kg * net_unit_price
        line.line_cost = r2(line_cost)
        # 过敏原缺失只影响“完整可解释”标志，不影响计价
        if not reasons:
            line.explainable = True
            explainable_lines += 1
            explained_cost += line_cost
        line.unexplained_reasons = reasons

    total_lines = len(recipe.items)
    fully = (explainable_lines == total_lines and total_lines > 0 and not conflicted)
    snap.fully_explainable = fully
    snap.status = "conflicted" if conflicted else "active"
    snap.explained_cost = r2(explained_cost)
    snap.unexplained_cost = None  # 不可解释部分不猜价，置空而非填 0
    # 不可解释行无法估价，不能做成本加权；可解释比例按“有完整证据的食谱行占比”计量
    snap.explainable_ratio = r4(explainable_lines / total_lines) if total_lines else None
    snap.total_unit_cost = r2(explained_cost / recipe.servings) if recipe.servings else None
    if conflicted:
        snap.conflict_note = "存在同一生效时刻的映射冲突，待数据管理员确认后重建快照"
    db.commit()
    db.refresh(snap)
    return snap


def _event(db, snap, line, event_type, ingredient, detail, severity="error"):
    db.add(QualityEvent(
        snapshot_id=snap.id, snapshot_line_id=line.id if line else None,
        event_type=event_type, severity=severity,
        ingredient_name=ingredient, detail=detail,
    ))


def _mapping_candidate(m: IngredientMapping) -> dict:
    return {
        "mapping_id": m.id, "ingredient_name": m.ingredient_name,
        "revision": m.revision, "product_id": m.product_id,
        "purchase_code": m.purchase_code, "composition_code": m.composition_code,
        "grade": m.grade, "processing_status": m.processing_status,
        "allergen_tags": m.allergen_tags, "conversion": m.conversion,
        "effective_from": m.effective_from.isoformat(),
        "effective_to": m.effective_to.isoformat() if m.effective_to else None,
        "note": m.note,
    }


def resolve_conflict(db: Session, conflict_id: int, choice: str,
                     resolved_by: str) -> PriceSelectionSnapshot:
    """管理员确认候选 a/b：原冲突快照置 superseded，按所选映射重建只读快照。"""
    if choice not in ("a", "b"):
        raise HTTPException(400, "choice 必须为 a 或 b")
    conflict = db.get(MappingConflict, conflict_id)
    if not conflict:
        raise HTTPException(404, "冲突记录不存在")
    if conflict.status == "resolved":
        raise HTTPException(409, "该冲突已确认")
    chosen = conflict.candidate_a if choice == "a" else conflict.candidate_b
    old = db.get(PriceSelectionSnapshot, conflict.snapshot_id)
    conflict.status = "resolved"
    conflict.resolution = choice
    conflict.resolved_by = resolved_by
    conflict.resolved_at = datetime.utcnow()
    old.status = "superseded"
    db.commit()
    new_snap = build_meal_snapshot(
        db, old.dish_id, old.serving_date, old.meal_period,
        created_by=resolved_by, force_mapping_id=chosen["mapping_id"])
    return new_snap


# ---------------------------------------------------------------------------
# 6. 迟到的验收实测出成率 -> 影响版本（原快照保持只读）
# ---------------------------------------------------------------------------

def register_measured_yield(db: Session, product_id: int, grade: str,
                            processing_status: str, point: float,
                            sample_batch: str, measured_at: date,
                            created_by: str | None = None,
                            note: str | None = None) -> dict:
    """补传抽样实测出成率，对引用同等级证据的历史快照生成影响版本。"""
    if not 0 < point <= 1:
        raise HTTPException(400, "实测出成率必须在 (0,1] 区间")
    ev = YieldEvidence(
        product_id=product_id, grade=grade, processing_status=processing_status,
        evidence_kind="measured", point=point, lower=point, upper=point,
        sample_batch=sample_batch, measured_at=measured_at,
        note=note or "报表发布后补传的验收实测",
    )
    db.add(ev)
    db.flush()

    # 找所有引用该产品+等级+加工状态、且当时采用估计值的快照行
    lines = (db.query(SnapshotLine)
             .join(PriceSelectionSnapshot,
                   PriceSelectionSnapshot.id == SnapshotLine.snapshot_id)
             .filter(SnapshotLine.product_id == product_id,
                     SnapshotLine.required_grade == grade,
                     SnapshotLine.required_processing == processing_status,
                     SnapshotLine.yield_evidence_kind == "estimated")
             .order_by(SnapshotLine.id).all())
    impacts = []
    for line in lines:
        snap = db.get(PriceSelectionSnapshot, line.snapshot_id)
        old_y = line.yield_value
        quote = db.get(Quote, line.quote_id)
        gross = _gross_price_per_kg(quote)
        old_cost = line.line_cost
        net_kg = _line_net_kg(line)
        new_net_price = gross / point
        new_cost = r2(net_kg * new_net_price)
        delta = r2(new_cost - old_cost)
        impact = SnapshotImpactVersion(
            snapshot_id=snap.id, snapshot_line_id=line.id, yield_evidence_id=ev.id,
            reason=f"验收实测补传（批次 {sample_batch}，{measured_at}）",
            old_yield=old_y, old_yield_kind="estimated",
            new_yield=point, old_line_cost=old_cost, new_line_cost=new_cost,
            cost_delta=delta,
            unit_cost_delta=r4(delta / snap.servings) if snap.servings else None,
            created_by=created_by,
        )
        db.add(impact)
        db.flush()
        impacts.append({
            "impact_id": impact.id, "snapshot_id": snap.id,
            "ingredient_name": line.ingredient_name,
            "old_yield": old_y, "new_yield": point,
            "old_line_cost": old_cost, "new_line_cost": new_cost,
            "cost_delta": delta, "unit_cost_delta": impact.unit_cost_delta,
        })
    db.commit()
    return {"evidence_id": ev.id, "affected_snapshots": len({i["snapshot_id"] for i in impacts}),
            "impacts": impacts}


def _line_net_kg(line: SnapshotLine) -> float:
    """从固化的换算链还原该行净用量 kg。"""
    if not line.conversion_chain:
        return line.net_qty or 0.0
    kg = line.net_qty
    for step in line.conversion_chain:
        if step.get("to") == "kg" and step.get("from") != "毛重kg":
            kg = (line.net_qty or 0.0) * step["factor"]
    return kg


# ---------------------------------------------------------------------------
# 7. 成本桥接器：固定顺序连环替代
# ---------------------------------------------------------------------------

def _line_params(line: SnapshotLine) -> dict | None:
    """从只读快照行提取桥接所需的全部参数（不回查实时报价/映射）。"""
    if not line.explainable or not line.price_basis:
        return None
    pb = line.price_basis
    return {
        "ingredient": line.ingredient_name,
        "product_id": line.product_id,
        "qty_kg": _line_net_kg(line),
        "price": pb["price_per_unit"],
        "tax_factor": pb["tax_factor"],
        "pack": pb["net_weight_per_unit_kg"] if pb["unit"] == "box" else 1.0,
        "yield": line.yield_value if line.yield_value is not None else 1.0,
        "serving_line_id": line.id,
        "quote_id": pb["quote_id"],
        "mapping_id": line.mapping_id,
    }


def _unit_cost(servings: float, params: list[dict]) -> float:
    """按当前参数向量重算每份单位成本。

    c = Σ qty(净用量kg) × price × tax_factor / (pack × yield) / servings
    其中 price/pack 为含税毛重单价，再除出成率得净用量单价。
    """
    total = sum(p["qty_kg"] * p["price"] * p["tax_factor"]
                / (p["pack"] * p["yield"]) for p in params)
    return total / servings if servings else 0.0


def bridge_costs(db: Session, base_snapshot_id: int,
                 target_snapshot_id: int) -> CostBridge:
    """在两个固定餐期快照间分解单位成本变化。

    顺序固定：份量（含配方结构/单行净用量）-> 价格 -> 出成率 -> 规格 -> 映射。
    任一侧快照不可完整解释则拒绝比较，作为“不能比较的期间”暴露在覆盖质量页。
    """
    base = db.get(PriceSelectionSnapshot, base_snapshot_id)
    target = db.get(PriceSelectionSnapshot, target_snapshot_id)
    if not base or not target:
        raise HTTPException(404, "餐期快照不存在")
    if base.dish_id != target.dish_id:
        raise HTTPException(400, "成本桥接只能比较同一菜品的两个餐期")
    if not base.fully_explainable or not target.fully_explainable:
        raise HTTPException(
            409, {"detail": "存在不可完整解释的餐期，不能做成本桥接",
                  "base_explainable": base.fully_explainable,
                  "target_explainable": target.fully_explainable,
                  "base_snapshot_id": base.id, "target_snapshot_id": target.id})

    b_params = [p for p in (_line_params(l) for l in base.lines) if p]
    t_params = [p for p in (_line_params(l) for l in target.lines) if p]
    b_map = {p["ingredient"]: p for p in b_params}
    t_map = {p["ingredient"]: p for p in t_params}
    names = sorted(set(b_map) | set(t_map))

    # 工作向量：以基准参数起步，逐步替换为目标参数
    work = {}
    for n in names:
        pb = b_map.get(n)
        pt = t_map.get(n)
        work[n] = dict(pb) if pb else None
    servings = base.servings

    def current_params():
        return [work[n] for n in names if work[n] is not None]

    def cost_now():
        return r4(_unit_cost(servings, current_params()))

    c0 = cost_now()
    steps = []

    # 第 1 步 份量：份数、配方结构（新增/删除原料行）、同行净用量变化
    removed, added, qty_changed = [], [], []
    servings = target.servings
    for n in names:
        pb, pt = b_map.get(n), t_map.get(n)
        if pb and not pt:
            removed.append(n)
            work[n] = None
        elif pt and not pb:
            added.append(n)
            work[n] = dict(pt)  # 新行先按目标参数进入，后续价格/出成率/规格步骤跳过它
            work[n]["_new_line"] = True
        elif pb and pt:
            if abs(pb["qty_kg"] - pt["qty_kg"]) > 1e-9:
                qty_changed.append({"ingredient": n, "from_kg": pb["qty_kg"],
                                    "to_kg": pt["qty_kg"]})
            work[n]["qty_kg"] = pt["qty_kg"]
    c1 = cost_now()
    steps.append({
        "factor": "份量",
        "detail": {"servings_from": base.servings, "servings_to": target.servings,
                   "added_lines": added, "removed_lines": removed,
                   "qty_changed": qty_changed},
        "unit_cost_after": c1, "contribution": r4(c1 - c0),
        "evidence": {"base_snapshot_id": base.id, "target_snapshot_id": target.id,
                     "recipe_base_id": base.recipe_id, "recipe_target_id": target.recipe_id},
    })

    # 同产品行参与价格/出成率/规格替换；换了产品（映射变化）的行留到第 5 步整体替换
    same_product = {n for n in names
                    if b_map.get(n) and t_map.get(n)
                    and b_map[n]["product_id"] == t_map[n]["product_id"]}
    remapped = {n for n in names
                if b_map.get(n) and t_map.get(n)
                and b_map[n]["product_id"] != t_map[n]["product_id"]}

    # 第 2 步 价格（含税费口径）
    price_changes = []
    for n in same_product:
        pb, pt = b_map[n], t_map[n]
        if abs(pb["price"] * pb["tax_factor"] - pt["price"] * pt["tax_factor"]) > 1e-9:
            price_changes.append({"ingredient": n,
                                  "from": r4(pb["price"] * pb["tax_factor"]),
                                  "to": r4(pt["price"] * pt["tax_factor"]),
                                  "quote_from": pb["quote_id"], "quote_to": pt["quote_id"]})
        work[n]["price"] = pt["price"]
        work[n]["tax_factor"] = pt["tax_factor"]
    c2 = cost_now()
    steps.append({
        "factor": "价格",
        "detail": {"changes": price_changes},
        "unit_cost_after": c2, "contribution": r4(c2 - c1),
        "evidence": {"quote_snapshots": [n for n in same_product]},
    })

    # 第 3 步 出成率
    yield_changes = []
    for n in same_product:
        pb, pt = b_map[n], t_map[n]
        if abs(pb["yield"] - pt["yield"]) > 1e-9:
            yield_changes.append({"ingredient": n, "from": pb["yield"], "to": pt["yield"],
                                  "evidence_line_from": pb["serving_line_id"],
                                  "evidence_line_to": pt["serving_line_id"]})
        work[n]["yield"] = pt["yield"]
    c3 = cost_now()
    steps.append({
        "factor": "出成率",
        "detail": {"changes": yield_changes},
        "unit_cost_after": c3, "contribution": r4(c3 - c2),
        "evidence": {"yield_evidence_kinds": "measured 优先，estimated 标明非验收事实"},
    })

    # 第 4 步 规格（包装净重/箱规）
    spec_changes = []
    for n in same_product:
        pb, pt = b_map[n], t_map[n]
        if abs(pb["pack"] - pt["pack"]) > 1e-9:
            spec_changes.append({"ingredient": n, "from_kg_per_unit": pb["pack"],
                                 "to_kg_per_unit": pt["pack"]})
        work[n]["pack"] = pt["pack"]
    c4 = cost_now()
    steps.append({
        "factor": "规格",
        "detail": {"changes": spec_changes},
        "unit_cost_after": c4, "contribution": r4(c4 - c3),
        "evidence": {"basis": "快照行 price_basis.net_weight_per_unit_kg"},
    })

    # 第 5 步 映射：换了采购编码（产品）的原料，整体切换关联一次完成
    mapping_changes = []
    for n in remapped:
        pt = t_map[n]
        mapping_changes.append({
            "ingredient": n,
            "product_from": b_map[n]["product_id"], "product_to": pt["product_id"],
            "mapping_from": b_map[n]["mapping_id"], "mapping_to": pt["mapping_id"],
        })
        work[n] = dict(pt)
    c5 = cost_now()
    steps.append({
        "factor": "映射",
        "detail": {"changes": mapping_changes},
        "unit_cost_after": c5, "contribution": r4(c5 - c4),
        "evidence": {"rule": "同名原料指向不同采购编码时，在最后一步整体替换关联，"
                             "避免与价格/出成率/规格步骤重复归因"},
    })

    target_cost = c5
    total_delta = r4(sum(s["contribution"] for s in steps))
    # 步骤贡献之和与整体重算差额仅可能有舍入误差；同时重算值应贴近快照展示值（2 位小数）
    consistent = (abs(total_delta - r4(c5 - c0)) < 0.01
                  and abs(c0 - base.total_unit_cost) < 0.01
                  and abs(c5 - target.total_unit_cost) < 0.01)
    bridge = CostBridge(
        dish_id=base.dish_id, base_snapshot_id=base.id,
        target_snapshot_id=target.id,
        base_unit_cost=c0, target_unit_cost=c5,
        total_delta=total_delta, steps=steps, consistent=consistent,
        note="按固定顺序（份量→价格→出成率→规格→映射）连环替代；顺序不同归因不同，"
             "各步贡献不构成唯一原因。全部依据只读自两个餐期快照，不回查实时主数据。"
             "单位成本为快照行参数的 4 位重算值，与快照页 2 位展示值仅有舍入差异。",
    )
    db.add(bridge)
    db.commit()
    db.refresh(bridge)
    return bridge


# ---------------------------------------------------------------------------
# 8. 覆盖质量
# ---------------------------------------------------------------------------

def coverage_overview(db: Session) -> list[dict]:
    """每道菜的可解释成本比例、缺失证据与冲突状态。"""
    out = []
    for dish in db.query(Dish).order_by(Dish.id).all():
        snaps = (db.query(PriceSelectionSnapshot)
                 .filter_by(dish_id=dish.id)
                 .order_by(PriceSelectionSnapshot.serving_date.desc(),
                           PriceSelectionSnapshot.id.desc()).all())
        latest = next((s for s in snaps if s.status != "superseded"), None)
        events = []
        incomparable = []
        if latest:
            events = [e for e in latest.events]
        for s in snaps:
            if not s.fully_explainable:
                incomparable.append({
                    "snapshot_id": s.id, "serving_date": s.serving_date.isoformat(),
                    "meal_period": s.meal_period, "status": s.status,
                    "reasons": sorted({r for line in s.lines
                                       for r in (line.unexplained_reasons or [])}),
                })
        out.append({
            "dish_id": dish.id, "dish_code": dish.code, "dish_name": dish.name,
            "latest_snapshot_id": latest.id if latest else None,
            "latest_serving_date": latest.serving_date.isoformat() if latest else None,
            "fully_explainable": latest.fully_explainable if latest else None,
            "explainable_ratio": latest.explainable_ratio if latest else None,
            "total_unit_cost": latest.total_unit_cost if latest else None,
            "missing_evidence": [
                {"type": e.event_type, "ingredient": e.ingredient_name,
                 "detail": e.detail, "severity": e.severity} for e in events],
            "incomparable_periods": incomparable,
            "snapshot_count": len(snaps),
        })
    return out
