import logging

logger = logging.getLogger(__name__)


async def test_soniox():
    """Test Soniox STT API connection"""
    try:
        from soniox import SonioxClient
        from app.config import get_settings

        settings = get_settings()

        logger.info("Testing Soniox API...")

        # Initialize client to verify API key
        client = SonioxClient(api_key=settings.soniox_api_key)

        # Just verify client initializes (we'll test actual transcription in Phase 3)
        return {
            "service": "soniox",
            "status": "ready",
            "message": "Soniox client initialized successfully"
        }
    except Exception as e:
        logger.error(f"Soniox test failed: {e}")
        return {
            "service": "soniox",
            "status": "error",
            "error": str(e)
        }


async def test_gemini():
    """Test Gemini LLM with a simple prompt"""
    try:
        from google import genai
        from app.config import get_settings

        settings = get_settings()

        logger.info("Testing Gemini API...")

        client = genai.Client(api_key=settings.gemini_api_key)
        # Try models in order of preference
        model_candidates = [
            "models/gemini-2.5-flash-preview-09-2025",
            "models/gemini-2.0-flash",
            "models/gemini-2.0-flash-lite",
            "models/gemini-1.5-flash",
        ]
        
        response = None
        selected_model = None
        last_error = None
        
        for model_name in model_candidates:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents="Say 'Hello from Gemini' in exactly 3 words.",
                )
                selected_model = model_name
                break
            except Exception as model_error:
                last_error = model_error
                logger.warning(f"Model {model_name} failed: {model_error}")
        
        if response is None:
            raise RuntimeError(
                f"No working Gemini model found. Last error: {last_error}"
            )

        return {
            "service": "gemini",
            "status": "success",
            "response": getattr(response, "text", "") or "",
            "model": selected_model,
            "message": "Gemini API working",
        }
    except Exception as e:
        logger.error(f"Gemini test failed: {e}")
        return {
            "service": "gemini",
            "status": "error",
            "error": str(e),
        }


async def test_elevenlabs():
    """Test Edge TTS (replaced ElevenLabs — free, no API key)."""
    try:
        import edge_tts

        logger.info("Testing Edge TTS...")

        # Quick synthesis of a short phrase to validate connectivity
        communicate = edge_tts.Communicate("test", voice="ur-PK-AsadNeural")
        audio_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes += chunk["data"]
                break  # just need first chunk to confirm it works

        if audio_bytes:
            return {
                "service": "tts",
                "status": "success",
                "voice": "ur-PK-AsadNeural (Edge TTS)",
                "message": "Edge TTS working — Urdu voice available",
            }
        else:
            return {
                "service": "tts",
                "status": "error",
                "error": "Edge TTS returned no audio",
            }
    except Exception as e:
        logger.error(f"Edge TTS test failed: {e}")
        return {
            "service": "tts",
            "status": "error",
            "error": str(e),
        }

