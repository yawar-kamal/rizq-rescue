"""Edge-TTS service for synthesizing AI replies in Urdu."""

import base64
import io
import logging
from typing import Optional

import edge_tts

logger = logging.getLogger(__name__)

# Available Urdu voices (Microsoft Edge Neural):
#   ur-PK-AsadNeural   — male
#   ur-PK-UzmaNeural   — female
DEFAULT_VOICE = "ur-PK-AsadNeural"


class EdgeTTSService:
    """Generate speech audio with Microsoft Edge TTS (free, no API key)."""

    def __init__(self, voice: str = DEFAULT_VOICE):
        self.voice = voice
        logger.info("EdgeTTSService initialized (voice=%s)", self.voice)

    async def synthesize_speech(self, text: str) -> Optional[dict]:
        """
        Convert text to speech using Edge TTS.

        Returns:
            {"audio_base64": "...", "mime_type": "audio/mpeg"} or None on failure.
        """
        text = (text or "").strip()
        if not text:
            return None

        try:
            communicate = edge_tts.Communicate(text, voice=self.voice)

            # Collect all audio chunks into a buffer
            audio_buffer = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.write(chunk["data"])

            audio_bytes = audio_buffer.getvalue()
            if not audio_bytes:
                logger.warning("Edge TTS returned empty audio")
                return None

            logger.info(
                "Edge TTS synthesized %d chars → %d bytes MP3",
                len(text),
                len(audio_bytes),
            )
            return {
                "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                "mime_type": "audio/mpeg",
            }

        except Exception as exc:
            logger.error("Edge TTS synthesis failed: %s", exc)
            return None
