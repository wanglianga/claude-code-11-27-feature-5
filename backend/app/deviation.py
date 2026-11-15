"""验收偏差归因：按固定顺序逐步替换重算。

顺序：先替换实际单价 -> 再替换收货数量 -> 最后替换出成率。
每步贡献之和 = 总差额；顺序不同归因会不同，各步贡献不构成唯一原因。
"""
from .calc import cost_totals, r2, r4


def _unit_cost(quote_terms, price, units, freight_weight, usable_kg):
    totals = cost_totals(
        price,
        units,
        quote_terms["tax_included"],
        quote_terms["tax_rate"],
        quote_terms["fee_rules"],
        quote_terms["delivery_mode"],
        freight_weight,
    )
    if not usable_kg:
        return totals["total_cost"], None
    return totals["total_cost"], totals["total_cost"] / usable_kg


def chain_deviation(snapshot, actual):
    """snapshot: 采购依据快照；actual: 验收汇总。

    actual = {
      "actual_unit_price": float,
      "received_weight_kg": float,   # 实际到货毛重
      "actual_yield": float | None,  # 未实测则 None
    }
    """
    terms = snapshot["terms"]
    planned = snapshot["planned"]
    price0 = planned["price_per_unit"]
    units0 = planned["units"]
    y0 = planned["yield_used"]  # 计划采用出成率（保守下界）
    gross_per_unit = terms["gross_weight_per_unit_kg"]
    net_per_unit = terms["net_weight_per_unit_kg"]

    fw0 = planned["freight_weight_kg"]
    usable0 = planned["usable_kg_planned"]
    total0, c0 = _unit_cost(terms, price0, units0, fw0, usable0)

    price1 = actual.get("actual_unit_price") or price0
    # 第 1 步：替换实际单价（数量、出成率仍按计划）
    total1, c1 = _unit_cost(terms, price1, units0, fw0, usable0)

    # 第 2 步：替换实际收货数量（按实际毛重折算件数与可用量，出成率仍按计划）
    received = actual["received_weight_kg"]
    if terms["unit"] == "box" and gross_per_unit:
        units1 = received / gross_per_unit
    else:
        units1 = received
    net_kg1 = units1 * (net_per_unit or 1.0)
    usable1 = net_kg1 * y0
    total2, c2 = _unit_cost(terms, price1, units1, received, usable1)

    # 第 3 步：替换实际出成率
    y1 = actual.get("actual_yield")
    yield_measured = y1 is not None
    if not yield_measured:
        y1 = y0
    usable2 = net_kg1 * y1
    total3, c3 = _unit_cost(terms, price1, units1, received, usable2)

    steps = [
        {
            "factor": "单价",
            "from": price0,
            "to": price1,
            "unit_cost_after": r4(c1) if c1 is not None else None,
        },
        {
            "factor": "收货数量",
            "from_kg": r2(fw0),
            "to_kg": r2(received),
            "unit_cost_after": r4(c2) if c2 is not None else None,
        },
        {
            "factor": "出成率",
            "from": y0,
            "to": y1,
            "measured": yield_measured,
            "unit_cost_after": r4(c3) if c3 is not None else None,
        },
    ]
    # 各步贡献舍入到 4 位；总差额取各步贡献之和，保证“每步贡献相加 = 总差额”严格一致；
    # 另给未舍入的精确总差额供核对。
    for s, raw in zip(steps, (c1 - c0, c2 - c1, c3 - c2)):
        s["contribution"] = r4(raw) if raw is not None else None
    total_dev_precise = r4(c3 - c0) if c0 is not None and c3 is not None else None
    total_dev = (r4(sum(s["contribution"] for s in steps))
                 if all(s["contribution"] is not None for s in steps) else None)
    return {
        "unit": "元/可用kg",
        "planned": {
            "price_per_unit": price0,
            "units": units0,
            "yield_used": y0,
            "total_cost": total0,
            "usable_kg": r2(usable0),
            "unit_cost": r4(c0) if c0 is not None else None,
        },
        "actual": {
            "price_per_unit": price1,
            "received_weight_kg": r2(received),
            "yield": y1 if yield_measured else None,
            "total_cost": total3,
            "usable_kg": r2(usable2),
            "unit_cost": r4(c3) if c3 is not None else None,
        },
        "steps": steps,
        "total_deviation": total_dev,
        "total_deviation_precise": total_dev_precise,
        "consistent": total_dev is not None,
        "note": (
            "按固定顺序（单价→收货数量→出成率）逐步替换重算；替换顺序不同归因结果会不同，"
            "各步贡献不构成唯一原因。未实测出成率时该步按计划值处理。"
        ),
    }
