"""成本换算引擎纯函数测试。"""
from datetime import date, timedelta
from types import SimpleNamespace

from app.calc import assign_overlap_groups, calc_freight, plan_quote

FREIGHT = {"freight": {"min_fee": 20, "tiers": [
    {"max_kg": 100, "fee": 30},
    {"max_kg": 300, "per_kg": 0.3},
    {"max_kg": None, "per_kg": 0.25},
]}}


def make_quote(**kw):
    defaults = dict(
        id=1, review_status="ok", pending_reasons=[], valid_to=date(2026, 12, 31),
        lead_days=1, unit="box", unit_raw="箱", net_weight_per_unit_kg=20.0,
        gross_weight_per_unit_kg=21.0, price_per_unit=35.0, tax_included=True,
        tax_rate=None, moq_quantity=5, moq_unit="箱", delivery_mode="配送",
        fee_rules=FREIGHT, zero_price_basis=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_yield(lower=0.78, upper=0.85):
    return SimpleNamespace(lower=lower, upper=upper)


TODAY = date(2026, 11, 14)


class TestFreight:
    def test_first_tier_fixed_fee(self):
        amount, _ = calc_freight(FREIGHT, 100)
        assert amount == 30

    def test_middle_tier_per_kg_applies_to_all_weight(self):
        # 超过门槛只应用对应一档：147kg 全部按 0.3 元/kg，不累计
        amount, _ = calc_freight(FREIGHT, 147)
        assert abs(amount - 44.1) < 1e-6

    def test_top_tier(self):
        amount, _ = calc_freight(FREIGHT, 400)
        assert abs(amount - 100.0) < 1e-6

    def test_min_fee(self):
        rules = {"freight": {"min_fee": 20, "tiers": [{"max_kg": None, "per_kg": 0.1}]}}
        amount, desc = calc_freight(rules, 100)
        assert amount == 20
        assert "起送费" in desc


class TestBoxRounding:
    def test_net_need_conservative_boxes(self):
        # 净重需求 100kg：按出成率下界 0.78 反推 -> 每箱可用 15.6kg -> 7 箱
        plan = plan_quote(make_quote(), make_yield(), "net", 100, today=TODAY)
        assert plan["eligible"]
        assert plan["units"] == 7
        assert plan["purchase_kg"] == 140
        # 预计可用范围 [109.2, 119]，保守余量 9.2
        assert plan["expected_usable_range"] == [109.2, 119.0]
        assert plan["surplus_kg"] == 9.2

    def test_gross_need_boxes(self):
        plan = plan_quote(make_quote(), make_yield(), "gross", 100, today=TODAY)
        assert plan["units"] == 5
        assert plan["surplus_kg"] == 0.0

    def test_not_all_gross_counted_usable(self):
        plan = plan_quote(make_quote(), make_yield(), "net", 100, today=TODAY)
        # 7 箱净含量 140kg，但可用上界 119kg，不把毛重全视作可用
        assert plan["usable_kg_upper"] == 119.0
        assert plan["usable_kg_lower"] == 109.2

    def test_cost_interval_from_yield_interval(self):
        plan = plan_quote(make_quote(), make_yield(), "net", 100, today=TODAY)
        total = plan["total_cost"]
        assert plan["cost_per_usable_kg_lower"] == round(total / 119.0, 4)
        assert plan["cost_per_usable_kg_upper"] == round(total / 109.2, 4)


class TestTax:
    def test_tax_added_once_when_not_included(self):
        q = make_quote(unit="kg", unit_raw="公斤", tax_included=False, tax_rate=0.09,
                       price_per_unit=2.1, moq_quantity=None, delivery_mode="自提",
                       fee_rules=None)
        plan = plan_quote(q, make_yield(1.0, 1.0), "gross", 100, today=TODAY)
        assert plan["goods_amount"] == 210.0
        assert plan["tax_amount"] == round(210.0 * 0.09, 2)
        assert plan["total_cost"] == round(210.0 * 1.09, 2)

    def test_tax_not_double_counted_when_included(self):
        q = make_quote(unit="kg", unit_raw="公斤", tax_included=True, tax_rate=0.09,
                       price_per_unit=2.3, moq_quantity=None, delivery_mode="自提",
                       fee_rules=None)
        plan = plan_quote(q, make_yield(1.0, 1.0), "gross", 100, today=TODAY)
        assert plan["tax_amount"] == 0.0
        assert plan["total_cost"] == 230.0


class TestExclusions:
    def test_expired(self):
        q = make_quote(valid_to=TODAY - timedelta(days=1))
        plan = plan_quote(q, make_yield(), "gross", 100, today=TODAY)
        assert not plan["eligible"]
        assert any("过期" in r for r in plan["reasons"])

    def test_moq_not_met(self):
        plan = plan_quote(make_quote(moq_quantity=10), make_yield(),
                          "gross", 100, today=TODAY)
        assert not plan["eligible"]
        assert any("起订量" in r for r in plan["reasons"])

    def test_pending_review_excluded(self):
        q = make_quote(review_status="pending", pending_reasons=["缺等级"])
        plan = plan_quote(q, make_yield(), "gross", 100, today=TODAY)
        assert not plan["eligible"]
        assert "缺等级" in plan["reasons"]

    def test_deliverable_by(self):
        q = make_quote(lead_days=2)
        plan = plan_quote(q, make_yield(), "gross", 100, today=TODAY,
                          deliverable_by=TODAY + timedelta(days=1))
        assert not plan["eligible"]
        assert any("到货" in r for r in plan["reasons"])

    def test_zero_price_with_basis_ok(self):
        q = make_quote(price_per_unit=0, zero_price_basis="新品推广试吃装",
                       moq_quantity=None)
        plan = plan_quote(q, make_yield(), "gross", 100, today=TODAY)
        assert plan["eligible"]
        assert plan["goods_amount"] == 0.0


class TestYieldMissing:
    def test_net_need_missing_yield_shows_original_price(self):
        plan = plan_quote(make_quote(), None, "net", 100, today=TODAY)
        assert plan["eligible"]
        assert plan["convertible"] is False
        assert "原价" in plan["note"]

    def test_gross_need_missing_yield_still_comparable(self):
        plan = plan_quote(make_quote(), None, "gross", 100, today=TODAY)
        assert plan["eligible"] and plan["convertible"]
        assert plan.get("yield_missing")


class TestOverlap:
    def test_overlapping_intervals_not_ranked(self):
        results = [
            {"convertible": True, "cost_per_usable_kg_lower": 2.1, "cost_per_usable_kg_upper": 2.4},
            {"convertible": True, "cost_per_usable_kg_lower": 2.3, "cost_per_usable_kg_upper": 2.3},
            {"convertible": True, "cost_per_usable_kg_lower": 3.0, "cost_per_usable_kg_upper": 3.1},
        ]
        out = assign_overlap_groups(results)
        assert out[0]["overlapped"] and out[1]["overlapped"]
        assert not out[2]["overlapped"]
        assert out[0]["overlap_group"] == out[1]["overlap_group"] != out[2]["overlap_group"]
