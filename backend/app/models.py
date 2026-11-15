"""数据模型：报价归集与可比成本分析平台。

设计要点：
- Quote 保留来源、原行(raw)、全部规格与费用规则，按 revision 保留同号换值历史；
- PurchaseDecision 生成后只读，snapshot 固化当时换算依据，映射修订/重解析不影响它；
- Acceptance 按车次登记，短装/退货/等级拒收分列，未验收部分不计损耗。
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float,
                        ForeignKey, Integer, String, Text)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(128), nullable=False)
    display_name = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)  # admin / buyer / checker
    created_at = Column(DateTime, default=datetime.utcnow)


class StandardProduct(Base):
    __tablename__ = "standard_products"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    category = Column(String(64), default="蔬菜")
    base_unit = Column(String(16), default="kg")
    note = Column(String(256))

    yield_rates = relationship("YieldRate", back_populates="product")


class YieldRate(Base):
    """出成率（有依据的区间）；缺测则不建记录，前端展示原价而不猜净菜率。"""

    __tablename__ = "yield_rates"

    id = Column(Integer, primary_key=True)
    product_id = Column(ForeignKey("standard_products.id"), nullable=False)
    from_state = Column(String(32), nullable=False)  # 报价加工状态，如 带泥毛菜
    to_state = Column(String(32), nullable=False, default="净菜")
    lower = Column(Float, nullable=False)
    upper = Column(Float, nullable=False)
    evidence = Column(String(256))  # 依据，如实测批次
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("StandardProduct", back_populates="yield_rates")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True)
    filename = Column(String(256))
    file_hash = Column(String(64), index=True)
    kind = Column(String(16))  # csv / json / snapshot
    status = Column(String(16), default="processing")  # processing/partial/completed/failed
    total_rows = Column(Integer, default=0)
    ok_rows = Column(Integer, default=0)
    bad_rows = Column(Integer, default=0)
    column_mapping = Column(JSON)  # 文件列名 -> 标准字段
    unit_table = Column(JSON)  # 单位字面值 -> box/kg
    revision = Column(Integer, default=1)  # 重解析试算递增
    parent_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    file_content = Column(Text)  # 原始文件内容，供续接与重解析
    created_at = Column(DateTime, default=datetime.utcnow)

    rows = relationship("ImportRow", back_populates="batch")


class ImportRow(Base):
    """逐行处理结果：坏行单列，续接时跳过已 ok 的行。"""

    __tablename__ = "import_rows"

    id = Column(Integer, primary_key=True)
    batch_id = Column(ForeignKey("import_batches.id"), nullable=False)
    row_no = Column(Integer, nullable=False)
    status = Column(String(8), nullable=False)  # ok / bad
    raw = Column(JSON)
    error = Column(String(512))
    quote_id = Column(Integer, ForeignKey("quotes.id"), nullable=True)

    batch = relationship("ImportBatch", back_populates="rows")


class Quote(Base):
    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True)
    batch_id = Column(ForeignKey("import_batches.id"), nullable=False)
    row_no = Column(Integer)
    external_id = Column(String(64))  # 报价编号（同号换值时递增 revision）
    revision = Column(Integer, default=1)
    supersedes_id = Column(Integer, nullable=True)
    is_latest = Column(Boolean, default=True, index=True)
    source_name = Column(String(128))
    source_type = Column(String(16), default="supplier")  # supplier / market
    raw = Column(JSON)  # 原始行，溯源用
    raw_product_name = Column(String(128))
    product_id = Column(ForeignKey("standard_products.id"), nullable=True)
    mapping_status = Column(String(16), default="pending")  # mapped / pending
    mapping_candidates = Column(JSON)  # 名称相似只给候选，不自动归并
    grade = Column(String(32))  # 等级，缺 -> 待核
    origin = Column(String(64))  # 产地
    region = Column(String(32))  # 适用区域；NULL 表示不限区域（通用）
    package_desc = Column(String(64))
    unit = Column(String(16))  # box / kg / None(缺单位 -> 待核)
    unit_raw = Column(String(16))
    net_weight_per_unit_kg = Column(Float)  # 包装净重
    gross_weight_per_unit_kg = Column(Float)
    processing_status = Column(String(32))  # 加工状态：带泥毛菜/净菜...
    price_per_unit = Column(Float)
    tax_included = Column(Boolean)  # 税费是否已含；NULL -> 待补
    tax_rate = Column(Float)
    valid_from = Column(Date)
    valid_to = Column(Date)
    moq_quantity = Column(Float)  # 起订量
    moq_unit = Column(String(16))
    delivery_mode = Column(String(16))  # 配送 / 自提
    lead_days = Column(Integer, default=0)  # 0=当天，1=隔日
    fee_rules = Column(JSON)  # {"freight": {...}, "alloc_fees": [...]}
    zero_price_basis = Column(String(256))  # 零价免费依据
    review_status = Column(String(16), default="ok")  # ok / pending(待核)
    pending_reasons = Column(JSON, default=list)
    terms_hash = Column(String(64))  # 关键条款哈希，确认时校验
    parse_revision = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class NameMapping(Base):
    __tablename__ = "name_mappings"

    id = Column(Integer, primary_key=True)
    raw_name = Column(String(128), unique=True, nullable=False)
    product_id = Column(ForeignKey("standard_products.id"), nullable=True)
    status = Column(String(16), default="pending")  # pending / approved / rejected
    candidates = Column(JSON)
    revision = Column(Integer, default=1)
    note = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    reviewed_by = Column(String(64))


class PurchaseDecision(Base):
    """采购依据：生成后只读；更正通过 correct 生成新 revision。"""

    __tablename__ = "purchase_decisions"

    id = Column(Integer, primary_key=True)
    quote_id = Column(ForeignKey("quotes.id"), nullable=False)
    product_id = Column(ForeignKey("standard_products.id"), nullable=False)
    need_type = Column(String(8), nullable=False)  # gross / net
    need_quantity = Column(Float, nullable=False)
    units = Column(Float, nullable=False)  # 实际采购件数（箱）
    snapshot = Column(JSON)  # 固化换算依据与条款
    terms_hash = Column(String(64))
    status = Column(String(16), default="active")  # active / superseded
    revision = Column(Integer, default=1)
    corrects_id = Column(Integer, ForeignKey("purchase_decisions.id"), nullable=True)
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)

    acceptances = relationship("Acceptance", back_populates="decision")


class Acceptance(Base):
    """验收：关联实际车次与原订单；短装/退货/等级拒收分开登记。"""

    __tablename__ = "acceptances"

    id = Column(Integer, primary_key=True)
    decision_id = Column(ForeignKey("purchase_decisions.id"), nullable=False)
    trip_no = Column(String(64), nullable=False)  # 车次
    received_weight_kg = Column(Float, nullable=False)  # 实际到货毛重
    actual_unit_price = Column(Float)  # 实际结算单价
    actual_grade = Column(String(32))
    returned_weight_kg = Column(Float, default=0)  # 退货
    grade_rejected_weight_kg = Column(Float, default=0)  # 等级拒收
    actual_yield = Column(Float)  # 实际出成率（可空，未实测不猜）
    note = Column(String(512))
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)

    decision = relationship("PurchaseDecision", back_populates="acceptances")


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True)
    batch_id = Column(ForeignKey("import_batches.id"), nullable=False)
    seller = Column(String(128), nullable=False)  # 独立卖方
    raw_product_name = Column(String(128))
    product_id = Column(ForeignKey("standard_products.id"), nullable=True)
    grade = Column(String(32))
    processing_status = Column(String(32))
    price_per_kg = Column(Float, nullable=False)
    captured_at = Column(Date, nullable=False)
    source_name = Column(String(128))  # 采集来源
    repost_of = Column(Integer, nullable=True)  # 转载来源快照 id，转载不增权重
    created_at = Column(DateTime, default=datetime.utcnow)


# ===========================================================================
# 食谱成本事实域（feature-5）
#
# 设计原则（题目约定，采用“绑定到餐期快照”的第二种做法）：
# - 食谱版本、原料语义映射、出成率证据、报价均按“生效时刻”解析，并在餐期快照中
#   固化当时的关联与换算链；后续任何改版都不改写历史快照；
# - 估计值与实测值在证据账中显式分级，绝不把估计伪装成验收事实；
# - 选价快照只读；迟到的实测证据通过“影响版本”追加，原估计差额保留可查；
# - 同一生效时刻食谱版本与映射版本冲突时，保留两套候选关联，等待人工确认，
#   不按最后上传时间覆盖。
# ===========================================================================


class Dish(Base):
    """菜品（食堂出餐的一道菜）。"""

    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    category = Column(String(32), default="热菜")
    region = Column(String(32), default="中央厨房")  # 默认适用区域
    note = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)


class RecipeVersion(Base):
    """食谱版本：菜品 + 餐期 + 份数 + 原料净用量 + 修订生效时间，可追溯配方事实。"""

    __tablename__ = "recipe_versions"

    id = Column(Integer, primary_key=True)
    dish_id = Column(ForeignKey("dishes.id"), nullable=False)
    revision = Column(Integer, nullable=False, default=1)  # 同一菜品递增
    meal_period = Column(String(32), nullable=False)  # 餐期，如 2026-11-10 午餐
    servings = Column(Float, nullable=False)  # 本餐期份数
    effective_from = Column(Date, nullable=False)  # 修订生效时间
    effective_to = Column(Date, nullable=True)  # 失效日（被下一版替换时回填）
    supersedes_id = Column(ForeignKey("recipe_versions.id"), nullable=True)
    source_ref = Column(String(128))  # 来源系统单据号
    note = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("RecipeItem", back_populates="recipe",
                         cascade="all, delete-orphan",
                         order_by="RecipeItem.id")


class RecipeItem(Base):
    """食谱行：一种原料的净用量（成品净用量口径）。

    net_qty 为空表示食谱缺少净用量 -> 该菜“成本不可完整解释”，
    不得用同名原料或默认值补齐。
    """

    __tablename__ = "recipe_items"

    id = Column(Integer, primary_key=True)
    recipe_id = Column(ForeignKey("recipe_versions.id"), nullable=False)
    line_no = Column(Integer, nullable=False)
    ingredient_name = Column(String(128), nullable=False)  # 食谱系统中的原料名
    net_qty = Column(Float, nullable=True)  # 成品净用量；缺失置 NULL
    net_unit = Column(String(16), nullable=True)  # 净用量单位
    note = Column(String(256))

    recipe = relationship("RecipeVersion", back_populates="items")


class IngredientMapping(Base):
    """原料语义映射：采购编码 / 成分编码 / 等级 / 过敏原标签 / 单位换算依据。

    按版本维护；同一原料的映射在不同生效时刻可能指向不同标准品（同名误映射修订）。
    conversion 为单位换算链，如 采购箱 -> kg -> 成品净用量 g 的因子与依据。
    """

    __tablename__ = "ingredient_mappings"

    id = Column(Integer, primary_key=True)
    ingredient_name = Column(String(128), nullable=False)  # 食谱原料名
    revision = Column(Integer, nullable=False, default=1)
    product_id = Column(ForeignKey("standard_products.id"), nullable=True)  # 采购编码（标准品）
    purchase_code = Column(String(64))  # 采购系统编码
    composition_code = Column(String(64))  # 成分系统编码
    grade = Column(String(32))  # 要求等级
    allergen_tags = Column(JSON, default=list)  # 过敏原标签，如 ["蛋类","麸质"]
    processing_status = Column(String(32))  # 要求加工状态
    conversion = Column(JSON, nullable=True)  # 单位换算依据；缺失置 None
    allergen_mapped = Column(Boolean, default=False)  # 过敏原映射是否完成
    status = Column(String(16), default="active")  # active / superseded
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    supersedes_id = Column(ForeignKey("ingredient_mappings.id"), nullable=True)
    note = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)


class YieldEvidence(Base):
    """出成率证据账：严格区分抽样实测 / 历史估计 / 缺失。

    - measured：抽样实测（验收事实），可登记实测批次；
    - estimated：历史估计，只能作为估计值参与，evidence_kind 标明不是验收事实；
    - 缺失：不建记录或显式 missing 记录，选价与桥接不得用默认出成率补齐。
    """

    __tablename__ = "yield_evidences"

    id = Column(Integer, primary_key=True)
    product_id = Column(ForeignKey("standard_products.id"), nullable=False)
    grade = Column(String(32), nullable=False)  # 证据绑定的等级（等级失配判定用）
    processing_status = Column(String(32), nullable=False)  # 绑定的加工状态
    evidence_kind = Column(String(16), nullable=False)  # measured / estimated / missing
    lower = Column(Float, nullable=True)
    upper = Column(Float, nullable=True)
    point = Column(Float, nullable=True)  # 实测单值时使用
    sample_batch = Column(String(128))  # 抽样实测批次/车次
    measured_at = Column(Date, nullable=True)
    note = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)


class PriceSelectionSnapshot(Base):
    """餐期选价快照（只读）：一次餐期成本计算所采用的报价、来源批次与换算依据。

    生成后不可改写；报表发布后补传的实测出成率通过 SnapshotImpactVersion 追加，
    原快照与原估计差额永久保留。
    """

    __tablename__ = "price_selection_snapshots"

    id = Column(Integer, primary_key=True)
    dish_id = Column(ForeignKey("dishes.id"), nullable=False)
    recipe_id = Column(ForeignKey("recipe_versions.id"), nullable=False)
    meal_period = Column(String(32), nullable=False)
    serving_date = Column(Date, nullable=False)
    servings = Column(Float, nullable=False)
    status = Column(String(16), default="active")  # active / conflicted / superseded
    fully_explainable = Column(Boolean, default=False)  # 成本是否可完整解释
    total_unit_cost = Column(Float, nullable=True)  # 每份单位成本（可解释部分）
    explained_cost = Column(Float, nullable=True)  # 可解释原料成本合计
    unexplained_cost = Column(Float, nullable=True)  # 不可解释原料成本合计（不猜）
    explainable_ratio = Column(Float, nullable=True)  # 可解释成本比例
    conflict_note = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)  # 报表发布时间

    lines = relationship("SnapshotLine", back_populates="snapshot",
                         cascade="all, delete-orphan", order_by="SnapshotLine.id")
    events = relationship("QualityEvent", back_populates="snapshot",
                          cascade="all, delete-orphan", order_by="QualityEvent.id")
    impacts = relationship("SnapshotImpactVersion", back_populates="snapshot",
                           cascade="all, delete-orphan",
                           order_by="SnapshotImpactVersion.id")


class SnapshotLine(Base):
    """快照行：固化一条食谱原料在该餐期采用的完整关联与换算链。"""

    __tablename__ = "snapshot_lines"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(ForeignKey("price_selection_snapshots.id"), nullable=False)
    recipe_item_id = Column(ForeignKey("recipe_items.id"), nullable=False)
    ingredient_name = Column(String(128), nullable=False)
    mapping_id = Column(ForeignKey("ingredient_mappings.id"), nullable=True)
    product_id = Column(ForeignKey("standard_products.id"), nullable=True)
    quote_id = Column(ForeignKey("quotes.id"), nullable=True)
    yield_evidence_id = Column(ForeignKey("yield_evidences.id"), nullable=True)
    # 固化的事实（防止后续修订影响历史）
    net_qty = Column(Float, nullable=True)  # 食谱净用量
    net_unit = Column(String(16), nullable=True)
    required_grade = Column(String(32))
    required_processing = Column(String(32))
    quote_grade = Column(String(32))
    quote_processing = Column(String(32))
    conversion_chain = Column(JSON, nullable=True)  # 采购单位->加工单位->净用量
    price_basis = Column(JSON, nullable=True)  # 采用报价的单价/批次/来源
    yield_value = Column(Float, nullable=True)  # 采用的出成率点值/下界
    yield_evidence_kind = Column(String(16), nullable=True)  # measured/estimated
    line_cost = Column(Float, nullable=True)  # 该行可解释成本
    explainable = Column(Boolean, default=False)
    unexplained_reasons = Column(JSON, default=list)  # 不可完整解释的具体原因

    snapshot = relationship("PriceSelectionSnapshot", back_populates="lines")


class QualityEvent(Base):
    """质量事件：等级失配、证据缺失、换算缺失等，不静默吞掉。"""

    __tablename__ = "quality_events"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(ForeignKey("price_selection_snapshots.id"), nullable=False)
    snapshot_line_id = Column(ForeignKey("snapshot_lines.id"), nullable=True)
    event_type = Column(String(32), nullable=False)
    # grade_mismatch / missing_net_qty / missing_conversion / missing_allergen /
    # missing_yield / quote_not_found / mapping_missing
    severity = Column(String(16), default="error")  # error / warning
    ingredient_name = Column(String(128))
    detail = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    snapshot = relationship("PriceSelectionSnapshot", back_populates="events")


class MappingConflict(Base):
    """生效时刻冲突：食谱版本与原料映射版本同一时刻相互冲突。

    保留两套候选关联（candidate_a / candidate_b），等待数据管理员确认；
    确认前不按最后上传时间覆盖，关联餐期快照置为 conflicted。
    """

    __tablename__ = "mapping_conflicts"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(ForeignKey("price_selection_snapshots.id"), nullable=False)
    recipe_item_id = Column(ForeignKey("recipe_items.id"), nullable=False)
    ingredient_name = Column(String(128), nullable=False)
    effective_at = Column(Date, nullable=False)
    candidate_a = Column(JSON, nullable=False)  # 食谱版本侧候选
    candidate_b = Column(JSON, nullable=False)  # 映射版本侧候选
    status = Column(String(16), default="pending")  # pending / resolved
    resolution = Column(String(32), nullable=True)  # a / b
    resolved_by = Column(String(64))
    resolved_at = Column(DateTime)
    note = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)


class SnapshotImpactVersion(Base):
    """影响版本：报表发布后补传验收实测出成率时生成，引用原餐期快照。

    分别保存原估计与新证据造成的单位成本与差额，原快照保持只读不变。
    """

    __tablename__ = "snapshot_impact_versions"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(ForeignKey("price_selection_snapshots.id"), nullable=False)
    snapshot_line_id = Column(ForeignKey("snapshot_lines.id"), nullable=False)
    yield_evidence_id = Column(ForeignKey("yield_evidences.id"), nullable=False)
    reason = Column(String(256), default="验收实测出成率补传")
    old_yield = Column(Float, nullable=False)  # 原估计出成率
    old_yield_kind = Column(String(16), nullable=False)  # estimated
    new_yield = Column(Float, nullable=False)  # 新实测出成率
    old_line_cost = Column(Float, nullable=False)  # 原估计行成本
    new_line_cost = Column(Float, nullable=False)  # 新证据行成本
    cost_delta = Column(Float, nullable=False)  # 本行差额
    unit_cost_delta = Column(Float, nullable=False)  # 折算到每份的差额
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)

    snapshot = relationship("PriceSelectionSnapshot", back_populates="impacts")


class CostBridge(Base):
    """成本桥接结果：固定食谱快照上分解各因素对单位成本的贡献。

    分解顺序固定为 份量 -> 价格 -> 出成率 -> 规格 -> 映射；
    各步贡献之和 = 总差额。base_snapshot_id / target_snapshot_id 指向两个餐期快照。
    """

    __tablename__ = "cost_bridges"

    id = Column(Integer, primary_key=True)
    dish_id = Column(ForeignKey("dishes.id"), nullable=False)
    base_snapshot_id = Column(ForeignKey("price_selection_snapshots.id"), nullable=False)
    target_snapshot_id = Column(ForeignKey("price_selection_snapshots.id"), nullable=False)
    base_unit_cost = Column(Float, nullable=False)
    target_unit_cost = Column(Float, nullable=False)
    total_delta = Column(Float, nullable=False)
    steps = Column(JSON, nullable=False)  # 逐步分解（含依据引用）
    consistent = Column(Boolean, default=False)  # 各步贡献之和是否=总差额
    note = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)
