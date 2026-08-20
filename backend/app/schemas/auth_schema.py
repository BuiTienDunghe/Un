from pydantic import BaseModel, Field


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class CreateUserRequest(CredentialsRequest):
    role: str = "member"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class RoleUpdateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=16)
