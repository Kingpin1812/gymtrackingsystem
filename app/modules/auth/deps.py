"""FastAPI dependencies for database access, authentication and role checks."""

from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import Forbidden, Unauthenticated
from app.modules.auth import service
from app.modules.auth.models import Role, User

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_token(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthenticated("Authentication required")
    return credentials.credentials


def get_current_user(token: str = Depends(get_token), db: Session = Depends(get_db)) -> User:
    return service.resolve_token(db, token)


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = {r.value for r in roles}

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise Forbidden("You do not have permission to perform this action")
        return user

    return _dependency


require_admin = require_roles(Role.ADMIN)
require_staff = require_roles(Role.ADMIN, Role.TRAINER)
