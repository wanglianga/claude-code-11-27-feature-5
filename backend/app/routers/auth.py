from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import ROLE_NAMES
from ..models import User
from ..schemas import LoginIn

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    if not user or user.password != body.password:
        raise HTTPException(401, "用户名或密码错误")
    return {"id": user.id, "username": user.username,
            "display_name": user.display_name, "role": user.role,
            "role_name": ROLE_NAMES.get(user.role, user.role)}
