from fastapi import APIRouter

from app.modules.audit.service import AuditAction, record
from app.modules.auth.deps import CurrentAuth, DbSession, Meta
from app.modules.users.schemas import ProfileUpdateIn, SettingsUpdateIn, UserOut, UserSettingsOut

router = APIRouter(prefix="/me", tags=["account"])


@router.get("")
async def get_me(auth: CurrentAuth) -> UserOut:
    return UserOut.model_validate(auth.user)


@router.patch("")
async def update_profile(
    data: ProfileUpdateIn, auth: CurrentAuth, db: DbSession, meta: Meta
) -> UserOut:
    auth.user.full_name = data.full_name
    record(db, AuditAction.PROFILE_UPDATED, user_id=auth.user.id, ip_address=meta.ip)
    await db.commit()
    return UserOut.model_validate(auth.user)


@router.get("/settings")
async def read_settings(auth: CurrentAuth) -> UserSettingsOut:
    return UserSettingsOut.model_validate(auth.user.settings)


@router.patch("/settings")
async def update_settings(
    data: SettingsUpdateIn, auth: CurrentAuth, db: DbSession, meta: Meta
) -> UserSettingsOut:
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(auth.user.settings, field, value)
    record(
        db,
        AuditAction.SETTINGS_UPDATED,
        user_id=auth.user.id,
        ip_address=meta.ip,
        fields=sorted(changes),
    )
    await db.commit()
    return UserSettingsOut.model_validate(auth.user.settings)
