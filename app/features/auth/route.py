
from fastapi import APIRouter


auth_router = APIRouter(tags=["auth"], prefix="/auth")

@auth_router.post("/request")
async def login() -> dict[str, str]:
    return {"message": "Login successful"}

@auth_router.post("/verify")
async def register() -> dict[str, str]:
    return {"message": "Registration successful"}