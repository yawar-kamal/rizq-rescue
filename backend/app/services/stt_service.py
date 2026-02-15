import asyncio
import json
import logging
from typing import Optional, Dict, List
from websockets.asyncio.client import connect, ClientConnection
from app.config import get_settings

logger = logging.getLogger(__name__)


class SonioxSTTService:
    """
    Soniox Speech-to-Text service using raw WebSocket API.

    Based on: https://soniox.com/docs/stt/rt/real-time-transcription

    Flow:
      1. Connect to wss://stt-rt.soniox.com/transcribe-websocket
      2. Send JSON config (with api_key, model, audio_format, etc.)
      3. Stream binary audio chunks
      4. Receive JSON responses with tokens
      5. Send empty string "" to signal end-of-audio
    """

    def __init__(self):
        self.settings = get_settings()
        self.ws_url = "wss://stt-rt.soniox.com/transcribe-websocket"
        self.soniox_ws: Optional[ClientConnection] = None

        # Token accumulation (reset for each session)
        self.final_tokens: List[Dict] = []
        self.non_final_tokens: List[Dict] = []

        logger.info("SonioxSTTService initialized (raw WebSocket)")

    async def start_session(self, language_hints: List[str] = None):
        """
        Start a new Soniox WebSocket session.
        First message must be configuration JSON.
        """
        try:
            logger.info(f"Connecting to Soniox: {self.ws_url}")

            # Connect to Soniox WebSocket
            self.soniox_ws = await connect(self.ws_url)

            # Prepare configuration — first message must be JSON
            config = {
                "api_key": self.settings.soniox_api_key,
                "model": "stt-rt-v4",

                # CRITICAL: auto-detect audio format (handles WebM!)
                "audio_format": "auto",

                # Language configuration
                "language_hints": language_hints or ["en"],
                "enable_language_identification": True,

                # Enable endpoint detection for faster finalization
                "enable_endpoint_detection": True,
                "max_endpoint_delay_ms": 2000,
            }

            # Send configuration as first message
            await self.soniox_ws.send(json.dumps(config))
            logger.info(
                "Soniox session started with config: %s",
                {k: v for k, v in config.items() if k != "api_key"},
            )

            # Reset token state
            self.final_tokens = []
            self.non_final_tokens = []

            return True

        except Exception as e:
            logger.error(f"Failed to start Soniox session: {e}")
            self.soniox_ws = None
            return False

    async def send_audio(self, audio_bytes: bytes):
        """
        Send audio chunk to Soniox.
        Audio can be in any format if audio_format="auto" (WebM, MP3, WAV, etc.)
        """
        if not self.soniox_ws:
            logger.warning("Soniox WebSocket not connected")
            return False

        try:
            await self.soniox_ws.send(audio_bytes)
            logger.debug(f"Sent {len(audio_bytes)} bytes to Soniox")
            return True
        except Exception as e:
            logger.error(f"Error sending audio to Soniox: {e}")
            return False

    async def receive_response(self) -> Optional[Dict]:
        """
        Receive and parse one response from Soniox.

        Returns dict with:
            - text: Full transcript (final + non-final)
            - final_text: Only confirmed text
            - confidence: Average confidence score
            - is_complete: True if all tokens are final
            - finished: True if session ended
        """
        if not self.soniox_ws:
            return None

        try:
            # Receive message from Soniox
            message = await self.soniox_ws.recv()
            response = json.loads(message)

            # Check for errors
            if response.get("error_code"):
                error_msg = (
                    f"Soniox error {response['error_code']}: "
                    f"{response.get('error_message', 'unknown')}"
                )
                logger.error(error_msg)
                return {
                    "text": "",
                    "final_text": "",
                    "confidence": 0.0,
                    "is_complete": False,
                    "error": error_msg,
                    "finished": False,
                }

            # Process tokens
            # Key: Non-final tokens reset on each response;
            #      Final tokens accumulate across all responses.
            self.non_final_tokens = []  # Reset non-final

            tokens = response.get("tokens", [])
            for token in tokens:
                if token.get("text"):  # Only process tokens with text
                    if token.get("is_final"):
                        self.final_tokens.append(token)
                    else:
                        self.non_final_tokens.append(token)

            # Build transcript
            final_text = "".join(t["text"] for t in self.final_tokens)
            non_final_text = "".join(t["text"] for t in self.non_final_tokens)
            full_text = final_text + non_final_text

            # Calculate confidence (only from final tokens)
            confidence = self._calculate_confidence()

            # Check if session finished
            finished = response.get("finished", False)

            result = {
                "text": full_text,
                "final_text": final_text,
                "confidence": confidence,
                "is_complete": len(self.non_final_tokens) == 0,
                "finished": finished,
                "audio_processed_ms": response.get("final_audio_proc_ms", 0),
            }

            # Always log at INFO level so we can see what Soniox returns
            logger.info(
                f"Soniox response: {len(tokens)} token(s), "
                f"text=\"{full_text}\", "
                f"confidence={confidence:.0%}, "
                f"final_proc_ms={response.get('final_audio_proc_ms', 0)}, "
                f"total_proc_ms={response.get('total_audio_proc_ms', 0)}, "
                f"finished={finished}"
            )

            if False:  # keep old block for reference
                logger.debug(
                    f"Soniox: 0 tokens, "
                    f"proc_ms={response.get('total_audio_proc_ms', 0)}"
                )

            return result

        except Exception as e:
            logger.error(f"Error receiving from Soniox: {e}")
            return None

    def _calculate_confidence(self) -> float:
        """Calculate average confidence from final tokens."""
        if not self.final_tokens:
            return 0.0
        confidences = [t.get("confidence", 0.0) for t in self.final_tokens]
        return sum(confidences) / len(confidences) if confidences else 0.0

    async def end_session(self):
        """
        End the Soniox session gracefully.
        Send empty string to signal end of audio, then drain final responses.
        """
        if self.soniox_ws:
            try:
                # Send empty string to signal end-of-audio
                await self.soniox_ws.send("")
                logger.info("Sent end-of-audio signal to Soniox")

                # Wait for final responses (drain)
                try:
                    while True:
                        response = await asyncio.wait_for(
                            self.receive_response(),
                            timeout=2.0,
                        )
                        if response and response.get("finished"):
                            logger.info("Soniox session finished")
                            break
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for Soniox finish signal")

                # Close WebSocket connection
                await self.soniox_ws.close()
                logger.info("Soniox WebSocket closed")

            except Exception as e:
                logger.error(f"Error ending Soniox session: {e}")

            finally:
                self.soniox_ws = None
                # NOTE: Do NOT clear final_tokens here!
                # The caller needs get_accumulated_text() after end_session().
                # Tokens are cleared on next start_session() or reset().

    def get_accumulated_text(self) -> str:
        """Return all final text accumulated so far."""
        return "".join(t["text"] for t in self.final_tokens)

    def reset(self):
        """Reset token accumulation."""
        self.final_tokens = []
        self.non_final_tokens = []
        logger.info("Token accumulation reset")
