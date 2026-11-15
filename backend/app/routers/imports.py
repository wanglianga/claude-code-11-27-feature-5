import json

from fastapi import (APIRouter, Depends, File, HTTPException, UploadFile)
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..importer import (DEFAULT_COLUMN_MAP, DEFAULT_UNIT_TABLE,
                        SNAPSHOT_COLUMN_MAP, create_batch, process_batch,
                        reparse_batch)
from ..models import ImportBatch, ImportRow
from ..schemas import ReparseIn

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _detect_kind(filename: str, content: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if "snapshot" in name or "快照" in name:
        return "snapshot"
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "snapshots" in data:
            return "snapshot"
    except json.JSONDecodeError:
        pass
    return "json"


@router.post("")
def upload(file: UploadFile = File(...),
           db: Session = Depends(get_db),
           _=Depends(require_roles("buyer"))):
    content = file.file.read().decode("utf-8-sig")
    kind = _detect_kind(file.filename, content)
    batch = create_batch(db, file.filename, content, kind)
    if batch.status != "completed":
        process_batch(db, batch)
    return _batch_out(db, batch)


@router.get("")
def list_batches(db: Session = Depends(get_db)):
    batches = db.query(ImportBatch).order_by(ImportBatch.id.desc()).all()
    return [_batch_out(db, b) for b in batches]


@router.get("/defaults")
def defaults():
    return {"column_mapping": DEFAULT_COLUMN_MAP, "unit_table": DEFAULT_UNIT_TABLE,
            "snapshot_column_mapping": SNAPSHOT_COLUMN_MAP}


@router.get("/{batch_id}")
def batch_detail(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    out = _batch_out(db, batch)
    rows = (db.query(ImportRow).filter_by(batch_id=batch_id)
            .order_by(ImportRow.row_no).all())
    out["rows"] = [
        {"row_no": r.row_no, "status": r.status, "error": r.error,
         "quote_id": r.quote_id, "raw": r.raw}
        for r in rows
    ]
    out["bad_rows"] = [r for r in out["rows"] if r["status"] == "bad"]
    return out


@router.post("/{batch_id}/resume")
def resume(batch_id: int, db: Session = Depends(get_db),
           _=Depends(require_roles("buyer"))):
    """中断续接：跳过已 ok 的行，只处理剩余行。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    process_batch(db, batch, only_pending=True)
    return _batch_out(db, batch)


@router.post("/{batch_id}/reparse")
def reparse(batch_id: int, body: ReparseIn, db: Session = Depends(get_db),
            _=Depends(require_roles("buyer"))):
    """列名表/单位表变更后重解析试算：生成新 revision 批次，旧依据不动。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    new_batch = reparse_batch(db, batch, body.column_mapping, body.unit_table)
    return _batch_out(db, new_batch)


def _batch_out(db: Session, batch: ImportBatch):
    return {
        "id": batch.id, "filename": batch.filename, "kind": batch.kind,
        "status": batch.status, "total_rows": batch.total_rows,
        "ok_rows": batch.ok_rows, "bad_rows": batch.bad_rows,
        "revision": batch.revision, "parent_batch_id": batch.parent_batch_id,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }
