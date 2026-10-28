"""Login, the current user, and user administration."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api import audit, schemas
from wtpdm.api.deps import db
from wtpdm.api.security import (
    Principal,
    admin,
    create_token,
    engineer,
    hash_password,
    verify_password,
    viewer,
)
from wtpdm.db.models import AppUser, Role

router = APIRouter(tags=["auth"])


@router.post("/auth/token", response_model=schemas.TokenOut, summary="Log in (OAuth2 password flow)")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), s: Session = Depends(db)):
    user = s.scalars(select(AppUser).where(AppUser.username == form.username.strip().lower())).first()
    ok = verify_password(form.password, user.password_hash if user else None)
    client = request.client.host if request.client else None
    if not ok or user is None or not user.is_active:
        # Committed even though the request fails: failed logins belong in the audit trail.
        audit.record(s, form.username[:64], "auth.login_failed", "user", form.username[:64], client=client)
        s.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, ttl = create_token(user.username, user.role)
    audit.record(s, user.username, "auth.login", "user", user.username, client=client)
    return schemas.TokenOut(access_token=token, expires_in=ttl, user=schemas.UserOut.model_validate(user))


@router.get("/auth/me", response_model=schemas.UserOut)
def me(user: Principal = Depends(viewer), s: Session = Depends(db)):
    return s.scalars(select(AppUser).where(AppUser.username == user.username)).one()


@router.post(
    "/auth/seen",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Mark the user's visit",
)
def seen(user: Principal = Depends(viewer), s: Session = Depends(db)) -> Response:
    """Called by the console when a session ends; "what changed since your last visit"
    (the assistant's proactive insights) is measured from this time."""
    row = s.scalars(select(AppUser).where(AppUser.username == user.username)).one()
    row.last_seen_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/directory", response_model=list[schemas.DirectoryEntry], tags=["users"])
def directory(_: Principal = Depends(engineer), s: Session = Depends(db)):
    """Active users who can own alerts (engineers and admins) - for the assignee picker."""
    return s.scalars(
        select(AppUser)
        .where(AppUser.is_active, AppUser.role.in_([Role.ENGINEER, Role.ADMIN]))
        .order_by(AppUser.display_name)
    ).all()


@router.get("/users", response_model=list[schemas.UserOut], tags=["users"])
def list_users(_: Principal = Depends(admin), s: Session = Depends(db)):
    return s.scalars(select(AppUser).order_by(AppUser.username)).all()


@router.post("/users", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED, tags=["users"])
def create_user(body: schemas.UserCreate, actor: Principal = Depends(admin), s: Session = Depends(db)):
    if s.scalars(select(AppUser).where(AppUser.username == body.username)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"User {body.username} already exists")
    user = AppUser(
        username=body.username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    s.add(user)
    s.flush()
    audit.record(s, actor.username, "user.create", "user", user.username, role=body.role.value)
    return user


@router.patch("/users/{username}", response_model=schemas.UserOut, tags=["users"])
def update_user(
    username: str, body: schemas.UserUpdate, actor: Principal = Depends(admin), s: Session = Depends(db)
):
    user = s.scalars(select(AppUser).where(AppUser.username == username)).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No user {username}")
    if username == actor.username and (body.is_active is False or (body.role and body.role != Role.ADMIN)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Admins cannot demote or deactivate themselves")
    changed = body.model_dump(exclude_unset=True, exclude_none=True)
    if "password" in changed:
        user.password_hash = hash_password(changed.pop("password"))
        changed["password"] = "changed"
    for field in ("display_name", "role", "is_active"):
        if field in changed:
            setattr(user, field, changed[field])
    audit.record(
        s,
        actor.username,
        "user.update",
        "user",
        username,
        **{k: (v.value if isinstance(v, Role) else v) for k, v in changed.items()},
    )
    return user
