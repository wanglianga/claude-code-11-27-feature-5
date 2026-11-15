"""可比成本换算引擎。

规则（与题目约定一致）：
- 整箱舍入：按指定采购量向上取整箱，不把一箱中的毛重全部视作可用；
- 净重需求按出成率下界反推保守采购量，再向上取整箱；
- 运费按报价声明的计重区间与起送费计算，超过门槛只应用对应一档（不累计）；
- 税费是否已含需有明确字段：未含则按税率加计一次，已含不重复加，缺失转待核；
- 出成率为区间 -> 成本为区间；缺测 -> 展示原价，不猜净菜率。
"""
import math
from datetime import date, timedelta

EPS = 1e-9


def r2(x):
    return round(x + 0.0, 2)


def r4(x):
    return round(x + 0.0, 4)


def calc_freight(fee_rules, weight_kg):
    """按计重区间计算运费，返回 (金额, 说明)。只应用匹配的一档。"""
    if not fee_rules or not fee_rules.get("freight"):
        return 0.0, "未声明运费规则（按 0 计）"
    fr = fee_rules["freight"]
    tiers = fr.get("tiers") or []
    min_fee = fr.get("min_fee") or 0.0
    for t in tiers:
        max_kg = t.get("max_kg")
        if max_kg is None or weight_kg <= max_kg + EPS:
            if t.get("fee") is not None:
                amount = float(t["fee"])
                desc = f"计重≤{max_kg}kg 档：固定 {amount} 元"
            else:
                amount = float(t["per_kg"]) * weight_kg
                desc = f"计重≤{max_kg}kg 档：{t['per_kg']} 元/kg × {r2(weight_kg)}kg"
            if max_kg is None:
                desc = desc.replace("≤Nonekg", "以上")
            if min_fee and amount < min_fee:
                desc += f"，不足起送费按 {min_fee} 元计"
                amount = float(min_fee)
            return amount, desc
    return 0.0, "无匹配计重区间"


def calc_alloc_fees(fee_rules, units, weight_kg):
    """可分摊费用：按件/按重量/固定，返回 (总额, 明细)。"""
    total = 0.0
    items = []
    for f in (fee_rules or {}).get("alloc_fees", []) or []:
        ftype = f.get("type")
        if ftype == "per_box":
            amt = float(f["amount"]) * units
        elif ftype == "per_kg":
            amt = float(f["amount"]) * weight_kg
        else:  # fixed
            amt = float(f["amount"])
        items.append({"name": f.get("name", "费用"), "type": ftype, "amount": r2(amt)})
        total += amt
    return total, items


def cost_totals(price_per_unit, units, tax_included, tax_rate, fee_rules,
                delivery_mode, freight_weight_kg):
    """由单价与件数重算总成本（计划与差额归因共用，保证口径一致）。"""
    goods = price_per_unit * units
    tax_amount = 0.0
    if tax_included is False and tax_rate:
        tax_amount = goods * float(tax_rate)  # 未含税 -> 加计一次
    if delivery_mode == "自提":
        freight, freight_desc = 0.0, "自提，无运费"
    else:
        freight, freight_desc = calc_freight(fee_rules, freight_weight_kg)
    alloc, alloc_items = calc_alloc_fees(fee_rules, units, freight_weight_kg)
    total = goods + tax_amount + freight + alloc
    return {
        "goods_amount": r2(goods),
        "tax_amount": r2(tax_amount),
        "freight": r2(freight),
        "freight_desc": freight_desc,
        "alloc_fees": r2(alloc),
        "alloc_items": alloc_items,
        "total_cost": r2(total),
    }


def plan_quote(quote, yield_rate, need_type, need_qty, today=None,
               deliverable_by=None):
    """对单条报价做可比成本试算。

    返回 dict：eligible=False 时带 reasons；eligible=True 时带完整换算依据。
    need_type: 'gross'（毛重需求）或 'net'（可用净重需求）。
    """
    today = today or date.today()
    reasons = []
    if quote.review_status == "pending":
        reasons.extend(quote.pending_reasons or ["待核"])
    if quote.valid_to and quote.valid_to < today:
        reasons.append(f"报价已于 {quote.valid_to.isoformat()} 过期")
    if deliverable_by:
        earliest = today + timedelta(days=quote.lead_days or 0)
        if earliest > deliverable_by:
            reasons.append(
                f"最早 {earliest.isoformat()} 到货，晚于要求 {deliverable_by.isoformat()}"
            )
    if reasons:
        return {"eligible": False, "reasons": reasons}

    is_box = quote.unit == "box"
    box_net = quote.net_weight_per_unit_kg
    box_gross = quote.gross_weight_per_unit_kg or box_net
    if is_box and not box_net:
        return {"eligible": False, "reasons": ["缺单件净重，无法换算"]}
    if not is_box and quote.unit != "kg":
        return {"eligible": False, "reasons": ["缺单位或单位无法识别"]}

    yl = yield_rate.lower if yield_rate else None
    yu = yield_rate.upper if yield_rate else None

    base = {
        "eligible": True,
        "quote_id": quote.id,
        "unit": quote.unit,
        "price_per_unit": quote.price_per_unit,
        "zero_price_basis": quote.zero_price_basis,
    }

    # 净重需求但缺出成率实测：展示原价，不猜净菜率
    if need_type == "net" and yl is None:
        base.update({
            "convertible": False,
            "note": "缺出成率实测，按原价展示，不参与可用成本排名",
            "original_price_text": (
                f"{quote.price_per_unit} 元/{quote.unit_raw or quote.unit}"
            ),
        })
        return base

    if is_box:
        if need_type == "net":
            per_box_usable = box_net * yl  # 保守：出成率下界
            units = math.ceil(need_qty / per_box_usable - EPS)
        else:
            units = math.ceil(need_qty / box_net - EPS)
    else:
        units = need_qty / yl if need_type == "net" else float(need_qty)

    # 起订量校验（按报价声明单位与本次采购件数比较）
    moq = quote.moq_quantity or 0
    if moq and units + EPS < moq:
        return {
            "eligible": False,
            "reasons": [
                f"未满足起订量（起订 {moq}{quote.moq_unit or quote.unit}，"
                f"本次需 {r2(units)}{quote.unit_raw or quote.unit}）"
            ],
        }

    purchase_kg = units * box_net if is_box else units  # 净含量合计
    freight_weight = units * box_gross if is_box else units  # 计费用重量（毛重）
    totals = cost_totals(
        quote.price_per_unit, units, quote.tax_included, quote.tax_rate,
        quote.fee_rules, quote.delivery_mode, freight_weight,
    )
    total = totals["total_cost"]

    result = {
        **base,
        "convertible": True,
        "units": r2(units),
        "purchase_kg": r2(purchase_kg),
        "freight_weight_kg": r2(freight_weight),
        **totals,
        "cost_per_gross_kg": r4(total / purchase_kg) if purchase_kg else None,
    }
    if yl is not None:
        usable_lower = purchase_kg * yl
        usable_upper = purchase_kg * yu
        result.update({
            "yield_lower": yl,
            "yield_upper": yu,
            "usable_kg_lower": r2(usable_lower),
            "usable_kg_upper": r2(usable_upper),
            # 成本低 = 出成率高；区间 [总成本/可用上界, 总成本/可用下界]
            "cost_per_usable_kg_lower": r4(total / usable_upper),
            "cost_per_usable_kg_upper": r4(total / usable_lower),
        })
        if need_type == "net":
            # 保守可用量 - 需求 = 多买余量（>=0，由向上取整保证）
            result["expected_usable_range"] = [r2(usable_lower), r2(usable_upper)]
            result["surplus_kg"] = r2(usable_lower - need_qty)
        else:
            result["surplus_kg"] = r2(purchase_kg - need_qty)
    else:
        # 毛重需求但缺出成率：仍可比毛重成本，可用量不猜
        result["surplus_kg"] = r2(purchase_kg - need_qty) if need_type == "gross" else None
        result["yield_missing"] = True
    return result


def assign_overlap_groups(results):
    """为成本区间重叠的报价打标：重叠区间不强排精确名次。"""
    convertible = [r for r in results if r.get("convertible") and r.get("cost_per_usable_kg_lower") is not None]
    convertible.sort(key=lambda r: (r["cost_per_usable_kg_lower"], r["cost_per_usable_kg_upper"]))
    group_id = 0
    current_upper = None
    for r in convertible:
        lo, hi = r["cost_per_usable_kg_lower"], r["cost_per_usable_kg_upper"]
        if current_upper is None or lo > current_upper + EPS:
            group_id += 1
            current_upper = hi
        else:
            current_upper = max(current_upper, hi)
        r["overlap_group"] = group_id
    # 组内多于 1 条 -> 区间重叠，不区分名次
    counts = {}
    for r in convertible:
        counts[r["overlap_group"]] = counts.get(r["overlap_group"], 0) + 1
    for r in convertible:
        r["overlapped"] = counts[r["overlap_group"]] > 1
    return results
