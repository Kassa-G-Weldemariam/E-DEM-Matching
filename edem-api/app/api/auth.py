from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.session import get_db
from app.schemas.auth import RegisterRequest, UserResponse
from app.services.auth import register_user

router = APIRouter(prefix="/auth", tags=["Auth"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: DbSession):
    user = register_user(db, data)
    return success_response(
        UserResponse.model_validate(user).model_dump(mode="json"),
        "Account created successfully",
    )