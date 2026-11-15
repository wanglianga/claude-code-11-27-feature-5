"""认证与通用依赖：简化的用户头校验（演示环境）。"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

ROLE_NAMES = {"admin": "管理员", "buyer": "采购员", "checker": "验收员"}


def current_user(x_user_id: int | None = Header(default=None),
                 db: Session = Depends(get_db)) -> User:
    if x_user_id is None:
        raise HTTPException(401, "未登录")
    user = db.get(User, x_user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def require_roles(*roles):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(403, f"需要 {'/'.join(ROLE_NAMES.get(r, r) for r in roles)} 角色")
        return user
    return dep
