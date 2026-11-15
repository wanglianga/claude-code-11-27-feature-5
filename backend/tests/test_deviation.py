"""差额归因测试：固定顺序逐步替换，每步贡献相加 = 总差额。"""
from app.deviation import chain_deviation

SNAPSHOT = {
    "terms": {
        "unit": "box",
        "net_weight_per_unit_kg": 20.0,
        "gross_weight_per_unit_kg": 21.0,
        "tax_included": True,
        "tax_rate": None,
        "fee_rules": {"freight": {"min_fee": 20, "tiers": [
            {"max_kg": 100, "fee": 30}, {"max_kg": 300, "per_kg": 0.3}]}},
        "delivery_mode": "配送",
    },
    "planned": {
        "price_per_unit": 35.0,
        "units": 7.0,
        "yield_used": 0.78,
        "freight_weight_kg": 147.0,
        "usable_kg_planned": 109.2,
    },
}


def test_chain_deviation_consistent():
    result = chain_deviation(SNAPSHOT, {
        "actual_unit_price": 36.0,
        "received_weight_kg": 135.0,
        "actual_yield": 0.74,
    })
    steps = result["steps"]
    assert [s["factor"] for s in steps] == ["单价", "收货数量", "出成率"]
    total = sum(s["contribution"] for s in steps)
    assert abs(total - result["total_deviation"]) < 1e-9
    assert result["consistent"]
    # 出成率降低 0.78 -> 0.74 是主要贡献
    assert steps[2]["contribution"] > 0
    assert steps[0]["contribution"] > 0  # 单价上涨
    assert "不构成唯一原因" in result["note"]


def test_unmeasured_yield_step_uses_plan():
    result = chain_deviation(SNAPSHOT, {
        "actual_unit_price": 35.0,
        "received_weight_kg": 147.0,
        "actual_yield": None,
    })
    assert result["steps"][2]["measured"] is False
    assert result["steps"][2]["contribution"] == 0.0
    assert result["total_deviation"] == 0.0
