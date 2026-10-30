from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.users.models import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    organization_id: UUID | None = None
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    role: UserRole = UserRole.USER

    @model_validator(mode="after")
    def validate_role_organization(self) -> "UserCreate":
        if self.role == UserRole.SUPER_ADMIN and self.organization_id is not None:
            raise ValueError("super_admin cannot belong to an organization")
        if self.role != UserRole.SUPER_ADMIN and self.organization_id is None:
            raise ValueError("organization_id is required for organization users")
        return self


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    role: UserRole | None = None
