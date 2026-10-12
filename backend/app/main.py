from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers.auth import router as auth_router
from app.routers.documents import router as documents_router


settings = get_settings()
app = FastAPI(title="StudyMate AI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(auth_router)
app.include_router(documents_router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "message": "StudyMate AI Backend is running",
    }
