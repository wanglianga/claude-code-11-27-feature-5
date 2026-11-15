"""feature-5 路由：食谱事实、语义映射、出成率证据、餐期选价快照、成本桥接、覆盖质量。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import (CostBridge, Dish, IngredientMapping, MappingConflict,
                      PriceSelectionSnapshot, Quote, RecipeVersion,
                      StandardProduct, YieldEvidence)
from ..recipe import (bridge_costs, build_meal_snapshot, coverage_overview,
                      create_mapping, create_recipe_version,
                      register_measured_yield, resolve_conflict)
from ..schemas import (BridgeIn, ConflictResolveIn, DishIn, MappingIn,
                       MeasuredYieldIn, RecipeVersionIn, SnapshotIn,
                       YieldEvidenceIn)

router = APIRouter(prefix="/api", tags=["recipe-cost"])


# ---------------------------------------------------------------- 菜品/食谱

def _dish_out(d: Dish):
    return {"id": d.id, "code": d.code, "name": d.name, "category": d.category,
            "region": d.region, "note": d.note}


@router.get("/dishes")
def list_dishes(db: Session = Depends(get_db)):
    return [_dish_out(d) for d in db.query(Dish).order_by(Dish.id).all()]


@router.post("/dishes")
def create_dish(body: DishIn, db: Session = Depends(get_db),
                _=Depends(require_roles("buyer"))):
    if db.query(Dish).filter(Dish.code == body.code).first():
        raise HTTPException(409, "菜品编码已存在")
    d = Dish(**body.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    return _dish_out(d)


def _recipe_out(r: RecipeVersion):
    return {
        "id": r.id, "dish_id": r.dish_id, "revision": r.revision,
        "meal_period": r.meal_period, "servings": r.servings,
        "effective_from": r.effective_from.isoformat(),
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "supersedes_id": r.supersedes_id, "source_ref": r.source_ref, "note": r.note,
        "items": [{"id": i.id, "line_no": i.line_no,
                   "ingredient_name": i.ingredient_name,
                   "net_qty": i.net_qty, "net_unit": i.net_unit, "note": i.note}
                  for i in r.items],
    }


@router.get("/dishes/{dish_id}/recipe-versions")
def list_recipe_versions(dish_id: int, db: Session = Depends(get_db)):
    if not db.get(Dish, dish_id):
        raise HTTPException(404, "菜品不存在")
    rs = (db.query(RecipeVersion).filter_by(dish_id=dish_id)
          .order_by(RecipeVersion.revision.desc()).all())
    return [_recipe_out(r) for r in rs]


@router.post("/dishes/{dish_id}/recipe-versions")
def add_recipe_version(dish_id: int, body: RecipeVersionIn,
                       db: Session = Depends(get_db),
                       _=Depends(require_roles("buyer"))):
    r = create_recipe_version(
        db, dish_id, body.meal_period, body.servings, body.effective_from,
        [i.model_dump() for i in body.items], body.source_ref, body.note)
    return _recipe_out(r)


@router.get("/recipe-versions/{recipe_id}")
def recipe_detail(recipe_id: int, db: Session = Depends(get_db)):
    r = db.get(RecipeVersion, recipe_id)
    if not r:
        raise HTTPException(404, "食谱版本不存在")
    return _recipe_out(r)


# ---------------------------------------------------------------- 语义映射

def _mapping_out(m: IngredientMapping, db: Session):
    product = db.get(StandardProduct, m.product_id) if m.product_id else None
    return {
        "id": m.id, "ingredient_name": m.ingredient_name, "revision": m.revision,
        "product_id": m.product_id,
        "product_name": product.name if product else None,
        "purchase_code": m.purchase_code, "composition_code": m.composition_code,
        "grade": m.grade, "processing_status": m.processing_status,
        "allergen_tags": m.allergen_tags or [], "conversion": m.conversion,
        "allergen_mapped": m.allergen_mapped, "status": m.status,
        "effective_from": m.effective_from.isoformat(),
        "effective_to": m.effective_to.isoformat() if m.effective_to else None,
        "note": m.note,
    }


@router.get("/ingredient-mappings")
def list_mappings(ingredient_name: str | None = None, db: Session = Depends(get_db)):
    q = db.query(IngredientMapping).order_by(
        IngredientMapping.ingredient_name, IngredientMapping.revision.desc())
    if ingredient_name:
        q = q.filter(IngredientMapping.ingredient_name == ingredient_name)
    return [_mapping_out(m, db) for m in q.all()]


@router.post("/ingredient-mappings")
def add_mapping(body: MappingIn, db: Session = Depends(get_db),
                _=Depends(require_roles("buyer"))):
    m = create_mapping(
        db, body.ingredient_name, body.product_id, body.effective_from,
        grade=body.grade, processing_status=body.processing_status,
        purchase_code=body.purchase_code, composition_code=body.composition_code,
        allergen_tags=body.allergen_tags, conversion=body.conversion,
        allergen_mapped=body.allergen_mapped, note=body.note)
    return _mapping_out(m, db)


# ---------------------------------------------------------------- 出成率证据

def _evidence_out(e: YieldEvidence, db: Session):
    p = db.get(StandardProduct, e.product_id)
    return {"id": e.id, "product_id": e.product_id,
            "product_name": p.name if p else None, "grade": e.grade,
            "processing_status": e.processing_status, "evidence_kind": e.evidence_kind,
            "lower": e.lower, "upper": e.upper, "point": e.point,
            "sample_batch": e.sample_batch,
            "measured_at": e.measured_at.isoformat() if e.measured_at else None,
            "note": e.note}


@router.get("/yield-evidences")
def list_evidences(product_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(YieldEvidence).order_by(YieldEvidence.id.desc())
    if product_id:
        q = q.filter(YieldEvidence.product_id == product_id)
    return [_evidence_out(e, db) for e in q.all()]


@router.post("/yield-evidences")
def add_evidence(body: YieldEvidenceIn, db: Session = Depends(get_db),
                 _=Depends(require_roles("checker", "buyer"))):
    if not db.get(StandardProduct, body.product_id):
        raise HTTPException(404, "标准品不存在")
    if body.evidence_kind == "measured" and body.point is None:
        raise HTTPException(400, "抽样实测必须给出 point 实测值")
    e = YieldEvidence(**body.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    return _evidence_out(e, db)


@router.post("/yield-evidences/measured-upload")
def upload_measured(body: MeasuredYieldIn, db: Session = Depends(get_db),
                    user=Depends(require_roles("checker"))):
    """报表发布后补传验收实测出成率：生成引用原餐期快照的影响版本。"""
    return register_measured_yield(
        db, body.product_id, body.grade, body.processing_status, body.point,
        body.sample_batch, body.measured_at, created_by=user.username, note=body.note)


# ---------------------------------------------------------------- 餐期快照

def _line_out(line, db: Session):
    quote = db.get(Quote, line.quote_id) if line.quote_id else None
    return {
        "id": line.id, "ingredient_name": line.ingredient_name,
        "recipe_item_id": line.recipe_item_id, "mapping_id": line.mapping_id,
        "product_id": line.product_id, "quote_id": line.quote_id,
        "yield_evidence_id": line.yield_evidence_id,
        "net_qty": line.net_qty, "net_unit": line.net_unit,
        "required_grade": line.required_grade,
        "required_processing": line.required_processing,
        "quote_grade": line.quote_grade, "quote_processing": line.quote_processing,
        "conversion_chain": line.conversion_chain, "price_basis": line.price_basis,
        "yield_value": line.yield_value,
        "yield_evidence_kind": line.yield_evidence_kind,
        "line_cost": line.line_cost, "explainable": line.explainable,
        "unexplained_reasons": line.unexplained_reasons or [],
        "quote_external_id": quote.external_id if quote else None,
        "source_name": quote.source_name if quote else None,
    }


def _snapshot_out(s: PriceSelectionSnapshot, db: Session, detail: bool = False):
    dish = db.get(Dish, s.dish_id)
    out = {
        "id": s.id, "dish_id": s.dish_id, "dish_name": dish.name if dish else None,
        "recipe_id": s.recipe_id, "meal_period": s.meal_period,
        "serving_date": s.serving_date.isoformat(), "servings": s.servings,
        "status": s.status, "fully_explainable": s.fully_explainable,
        "total_unit_cost": s.total_unit_cost, "explained_cost": s.explained_cost,
        "unexplained_cost": s.unexplained_cost,
        "explainable_ratio": s.explainable_ratio, "conflict_note": s.conflict_note,
        "published_at": s.published_at.isoformat() if s.published_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    if detail:
        out["lines"] = [_line_out(l, db) for l in s.lines]
        out["events"] = [{"id": e.id, "event_type": e.event_type,
                          "severity": e.severity, "ingredient_name": e.ingredient_name,
                          "detail": e.detail} for e in s.events]
        out["conflicts"] = [{
            "id": c.id, "ingredient_name": c.ingredient_name,
            "effective_at": c.effective_at.isoformat(),
            "candidate_a": c.candidate_a, "candidate_b": c.candidate_b,
            "status": c.status, "resolution": c.resolution,
            "resolved_by": c.resolved_by, "note": c.note}
            for c in db.query(MappingConflict).filter_by(snapshot_id=s.id).all()]
        out["impacts"] = [{
            "id": i.id, "snapshot_line_id": i.snapshot_line_id,
            "yield_evidence_id": i.yield_evidence_id, "reason": i.reason,
            "old_yield": i.old_yield, "old_yield_kind": i.old_yield_kind,
            "new_yield": i.new_yield, "old_line_cost": i.old_line_cost,
            "new_line_cost": i.new_line_cost, "cost_delta": i.cost_delta,
            "unit_cost_delta": i.unit_cost_delta,
            "created_at": i.created_at.isoformat()} for i in s.impacts]
    return out


@router.post("/snapshots")
def create_snapshot(body: SnapshotIn, db: Session = Depends(get_db),
                    _=Depends(require_roles("buyer"))):
    s = build_meal_snapshot(db, body.dish_id, body.serving_date, body.meal_period,
                            published=body.published)
    return _snapshot_out(s, db, detail=True)


@router.get("/snapshots")
def list_snapshots(dish_id: int | None = None,
                   status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(PriceSelectionSnapshot).order_by(
        PriceSelectionSnapshot.serving_date.desc(),
        PriceSelectionSnapshot.id.desc())
    if dish_id:
        q = q.filter(PriceSelectionSnapshot.dish_id == dish_id)
    if status:
        q = q.filter(PriceSelectionSnapshot.status == status)
    return [_snapshot_out(s, db) for s in q.all()]


@router.get("/snapshots/{snapshot_id}")
def snapshot_detail(snapshot_id: int, db: Session = Depends(get_db)):
    s = db.get(PriceSelectionSnapshot, snapshot_id)
    if not s:
        raise HTTPException(404, "餐期快照不存在")
    return _snapshot_out(s, db, detail=True)


@router.post("/snapshots/{snapshot_id}/publish")
def publish_snapshot(snapshot_id: int, db: Session = Depends(get_db),
                     _=Depends(require_roles("buyer"))):
    from datetime import datetime
    s = db.get(PriceSelectionSnapshot, snapshot_id)
    if not s:
        raise HTTPException(404, "餐期快照不存在")
    if not s.published_at:
        s.published_at = datetime.utcnow()
        db.commit()
    return _snapshot_out(s, db)


# ---------------------------------------------------------------- 冲突确认

@router.get("/mapping-conflicts")
def list_conflicts(status: str | None = "pending", db: Session = Depends(get_db)):
    q = db.query(MappingConflict).order_by(MappingConflict.id.desc())
    if status:
        q = q.filter(MappingConflict.status == status)
    return [{"id": c.id, "snapshot_id": c.snapshot_id,
             "recipe_item_id": c.recipe_item_id,
             "ingredient_name": c.ingredient_name,
             "effective_at": c.effective_at.isoformat(),
             "candidate_a": c.candidate_a, "candidate_b": c.candidate_b,
             "status": c.status, "resolution": c.resolution,
             "resolved_by": c.resolved_by, "note": c.note} for c in q.all()]


@router.post("/mapping-conflicts/{conflict_id}/resolve")
def resolve_mapping_conflict(conflict_id: int, body: ConflictResolveIn,
                             db: Session = Depends(get_db),
                             user=Depends(require_roles("buyer"))):
    new_snap = resolve_conflict(db, conflict_id, body.choice, user.username)
    return _snapshot_out(new_snap, db, detail=True)


# ---------------------------------------------------------------- 成本桥接

def _bridge_out(b: CostBridge):
    return {"id": b.id, "dish_id": b.dish_id,
            "base_snapshot_id": b.base_snapshot_id,
            "target_snapshot_id": b.target_snapshot_id,
            "base_unit_cost": b.base_unit_cost,
            "target_unit_cost": b.target_unit_cost,
            "total_delta": b.total_delta, "steps": b.steps,
            "consistent": b.consistent, "note": b.note,
            "created_at": b.created_at.isoformat() if b.created_at else None}


@router.post("/cost-bridges")
def create_bridge(body: BridgeIn, db: Session = Depends(get_db),
                  _=Depends(require_roles("buyer"))):
    b = bridge_costs(db, body.base_snapshot_id, body.target_snapshot_id)
    return _bridge_out(b)


@router.get("/cost-bridges")
def list_bridges(dish_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(CostBridge).order_by(CostBridge.id.desc())
    if dish_id:
        q = q.filter(CostBridge.dish_id == dish_id)
    return [_bridge_out(b) for b in q.all()]


@router.get("/cost-bridges/{bridge_id}")
def bridge_detail(bridge_id: int, db: Session = Depends(get_db)):
    b = db.get(CostBridge, bridge_id)
    if not b:
        raise HTTPException(404, "成本桥接不存在")
    return _bridge_out(b)


# ---------------------------------------------------------------- 覆盖质量

@router.get("/coverage")
def coverage(db: Session = Depends(get_db)):
    return coverage_overview(db)
