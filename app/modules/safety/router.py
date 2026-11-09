from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db_session, require_roles
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import EmployeeSafetyRead, SafetyStageUpdate
from app.modules.safety.service import SafetyService
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/safety", tags=["safety"])


def service(session: AsyncSession = Depends(get_db_session)) -> SafetyService:
    return SafetyService(SafetyRepository(session))


admin = require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)


@router.get("/employees", response_model=list[EmployeeSafetyRead])
async def list_employee_safety(
    actor: User = Depends(admin), safety_service: SafetyService = Depends(service)
) -> list[EmployeeSafetyRead]:
    return await safety_service.list_employees(actor)


@router.get("/employees/me", response_model=EmployeeSafetyRead)
async def get_my_safety(
    actor: User = Depends(get_current_user), safety_service: SafetyService = Depends(service)
) -> EmployeeSafetyRead:
    return await safety_service.get(actor, actor.id)


@router.get("/employees/{user_id}", response_model=EmployeeSafetyRead)
async def get_employee_safety(
    user_id: UUID,
    actor: User = Depends(get_current_user),
    safety_service: SafetyService = Depends(service),
) -> EmployeeSafetyRead:
    return await safety_service.get(actor, user_id)


@router.patch("/employees/{user_id}/stages/{stage_code}", response_model=EmployeeSafetyRead)
async def update_employee_stage(
    user_id: UUID,
    stage_code: str,
    data: SafetyStageUpdate,
    actor: User = Depends(admin),
    safety_service: SafetyService = Depends(service),
) -> EmployeeSafetyRead:
    return await safety_service.update_stage(actor, user_id, stage_code, data)
