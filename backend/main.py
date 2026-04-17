import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.schema import init_schema
from db.connection import close_connection
from ingestion.scheduler import create_scheduler
from ingestion.price import refresh_aliases_for_existing_companies
from api.routes.ticker import router as ticker_router
from api.routes.fundamentals import router as fundamentals_router
from api.routes.screener import router as screener_router
from api.routes.sentiment import router as sentiment_router
from api.routes.narratives import router as narratives_router
from api.routes.watchlist import router as watchlist_router
from api.routes.comparison import router as comparison_router
from api.routes.portfolio import router as portfolio_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_schema()
    try:
        refresh_aliases_for_existing_companies()
    except Exception as e:
        print(f"[startup] Alias refresh skipped: {e}")
    scheduler = create_scheduler()
    scheduler.start()
    print("Scheduler started.")

    yield

    # Shutdown
    scheduler.shutdown()
    close_connection()
    print("Shutdown complete.")


app = FastAPI(
    title="Stock Analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ticker_router)
app.include_router(fundamentals_router)
app.include_router(screener_router)
app.include_router(sentiment_router)
app.include_router(narratives_router)
app.include_router(watchlist_router)
app.include_router(comparison_router)
app.include_router(portfolio_router)


@app.get("/health")
def health():
    return {"status": "ok"}
