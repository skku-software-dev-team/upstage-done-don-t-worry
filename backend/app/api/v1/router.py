from fastapi import APIRouter

from app.api.v1.endpoints import chat, checklist, documents

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(documents.router)
api_router.include_router(checklist.router)
api_router.include_router(chat.router)
