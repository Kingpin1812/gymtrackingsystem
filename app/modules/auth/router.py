from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.pagination import Page, PageParams
from app.modules.auth import service
from app.modules.auth.deps import (
    get_current_user,
    get_db,
    get_settings_dep,
    get_token,
    require_admin,
)
from app.modules.auth.models import Role, User
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChange,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    ip = request.client.host if request.client else "unknown"
    token, session, user = service.login(
        db, settings, request.app.state.login_limiter, body.email, body.password, ip
    )
    return LoginResponse(token=token, expires_at=session.expires_at, user=user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: str = Depends(get_token), db: Session = Depends(get_db)):
    service.logout(db, token)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    token: str = Depends(get_token),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.change_password(db, user, body.current_password, body.new_password, token)


@router.get("/users", response_model=Page[UserOut])
def list_users(
    role: Role | None = None,
    page: PageParams = Depends(),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items, total = service.list_users(db, role, page.limit, page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    user = service.create_user(
        db, email=body.email, full_name=body.full_name, role=body.role, password=body.password
    )
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.update_user(db, admin, user_id, body.full_name, body.is_active)
