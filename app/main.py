from fastapi import FastAPI
from app.core.config import settings
from app.routers import auth, accounts, transfers, transactions, services, mfa, ai, loans, settings
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn

app = FastAPI(title="Bank Super App")

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://localhost:8081",
    "http://127.0.0.1:8081"
]

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(transactions.router)
app.include_router(services.router)
app.include_router(mfa.router)
app.include_router(ai.router)
app.include_router(loans.router)
app.include_router(settings.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Можно поставить ["*"] для разрешения всем (только для тестов)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Bank API is running"
    }



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Railway даст PORT=8080
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)