import sys
from pathlib import Path

# Ensure 'backend/' is on the import path so `app.*` imports work
# regardless of how the script is launched
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Rizq-Rescue MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
from app.models.database import init_db
init_db()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "rizq-rescue-backend"}


@app.get("/test/apis")
async def test_all_apis():
    """Test all external API integrations"""
    from app.services.api_tester import test_soniox, test_gemini, test_elevenlabs

    results = {
        "soniox": await test_soniox(),
        "gemini": await test_gemini(),
        "elevenlabs": await test_elevenlabs()
    }

    all_success = all(
        result["status"] in ["success", "ready"]
        for result in results.values()
    )

    return {
        "overall_status": "success" if all_success else "failure",
        "results": results
    }


@app.get("/api/donations")
async def get_donations():
    """Return all donations."""
    from app.models.database import get_donations as db_get_donations
    return {"donations": db_get_donations()}


@app.get("/api/stats")
async def get_stats():
    """Return aggregate donation stats."""
    from app.models.database import get_stats as db_get_stats
    return db_get_stats()


@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time audio streaming + STT + LLM"""
    from app.services.websocket_handler import handle_websocket
    await handle_websocket(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
