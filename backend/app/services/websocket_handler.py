"""WebSocket handler — routes audio → Soniox STT → Gemini LLM + ElevenLabs TTS."""

import asyncio
import json
import logging
import uuid
from fastapi import WebSocket, WebSocketDisconnect

from app.services.stt_service import SonioxSTTService
from app.services.llm_service import GeminiLLMService
from app.services.tts_service import EdgeTTSService

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track active WebSocket connections."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(
            f"Client {client_id} connected. Total: {len(self.active_connections)}"
        )

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        logger.info(
            f"Client {client_id} disconnected. Total: {len(self.active_connections)}"
        )

    async def send_json(self, client_id: str, data: dict):
        ws = self.active_connections.get(client_id)
        if ws:
            await ws.send_json(data)

    async def broadcast(self, data: dict):
        """Send to all connected clients."""
        for ws in self.active_connections.values():
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


async def handle_websocket(websocket: WebSocket):
    """Main WebSocket handler with Soniox STT + Gemini LLM.

    Flow:
      1. User starts recording → Soniox session opens
      2. While recording: live transcript streams to frontend (NO LLM calls)
      3. User stops recording → full transcript sent to Gemini ONCE
      4. Gemini response sent to frontend
    """

    client_id = str(uuid.uuid4())[:8]
    await manager.connect(websocket, client_id)

    # Services
    stt_service = SonioxSTTService()
    tts_service = EdgeTTSService()
    llm_service: GeminiLLMService | None = None
    soniox_started = False
    receiver_task = None
    llm_lock = asyncio.Lock()  # Prevent concurrent LLM calls
    mode = "restaurant"
    last_sent_final_text = ""

    # ── Background: Soniox → transcript + silence-triggered LLM ─────
    async def soniox_receiver():
        """Receive Soniox transcripts and trigger LLM on utterance boundaries."""
        nonlocal soniox_started, last_sent_final_text
        try:
            while soniox_started and stt_service.soniox_ws:
                try:
                    result = await asyncio.wait_for(
                        stt_service.receive_response(),
                        timeout=5.0,
                    )
                    if not result:
                        continue

                    # Forward live transcript to browser (text only, no LLM)
                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "text": result["text"],
                            "final_text": result["final_text"],
                            "confidence": result["confidence"],
                            "is_complete": result["is_complete"],
                        }
                    )

                    final_text = result["final_text"].strip()
                    if result["is_complete"] and final_text and llm_service:
                        if final_text != last_sent_final_text:
                            if final_text.startswith(last_sent_final_text):
                                new_turn_text = final_text[len(last_sent_final_text):].strip()
                            else:
                                # Soniox can occasionally rewrite final text.
                                # Fallback to current final segment to avoid dropping speech.
                                new_turn_text = final_text

                            if new_turn_text:
                                last_sent_final_text = final_text
                                await websocket.send_json(
                                    {"type": "turn_complete", "text": new_turn_text}
                                )
                                # Keep receiver loop responsive while LLM runs.
                                asyncio.create_task(send_to_llm(new_turn_text))

                    if result.get("finished"):
                        logger.info(f"[{client_id}] Soniox session finished")
                        break

                except asyncio.TimeoutError:
                    continue

        except asyncio.CancelledError:
            logger.info(f"[{client_id}] Soniox receiver cancelled")
        except Exception as e:
            logger.error(f"[{client_id}] Soniox receiver error: {e}")

    # ── Helper: send AI text + TTS audio to frontend ───────────────
    async def send_ai_output(text: str):
        """Send AI text response, then synthesized ElevenLabs audio."""
        clean_text = (text or "").strip()
        if not clean_text:
            return

        await websocket.send_json(
            {
                "type": "ai_response",
                "text": clean_text,
                "function_called": False,
                "function_name": None,
                "function_args": None,
            }
        )

        # Synthesize speech (edge-tts is async-native)
        tts_payload = await tts_service.synthesize_speech(clean_text)
        if tts_payload:
            await websocket.send_json(
                {
                    "type": "ai_audio",
                    "text": clean_text,
                    "audio_base64": tts_payload["audio_base64"],
                    "mime_type": tts_payload["mime_type"],
                }
            )
        else:
            logger.warning("[%s] TTS unavailable for message", client_id)

    # ── Helper: send transcript to Gemini (with lock) ──────────────
    async def send_to_llm(text: str):
        """Send accumulated text to Gemini and forward response. Locked to prevent duplicates."""
        if not text or not llm_service:
            return

        async with llm_lock:
            logger.info(f"[{client_id}] Sending to LLM: {text[:80]}...")

            llm_result = await llm_service.generate_response(text)

            ai_text = (llm_result.get("text") or "").strip()
            if ai_text:
                await websocket.send_json(
                    {
                        "type": "ai_response",
                        "text": ai_text,
                        "function_called": llm_result["function_called"],
                        "function_name": llm_result.get("function_name"),
                        "function_args": llm_result.get("function_args"),
                    }
                )
                tts_payload = await tts_service.synthesize_speech(ai_text)
                if tts_payload:
                    await websocket.send_json(
                        {
                            "type": "ai_audio",
                            "text": ai_text,
                            "audio_base64": tts_payload["audio_base64"],
                            "mime_type": tts_payload["mime_type"],
                        }
                    )
                else:
                    logger.warning("[%s] TTS unavailable for LLM output", client_id)

            if llm_result["function_called"] and llm_result.get("function_args"):
                await manager.broadcast(
                    {
                        "type": "donation_update",
                        "donation": llm_result["function_args"],
                    }
                )

    # ── Main loop: receive from browser ────────────────────────────
    try:
        while True:
            data = await websocket.receive()

            # JSON control messages
            if "text" in data:
                try:
                    message = json.loads(data["text"])
                    msg_type = message.get("type", "")

                    # ── Start recording ──────────────────────────
                    if msg_type == "start_recording":
                        mode = message.get("mode", "restaurant")
                        logger.info(f"[{client_id}] Start recording (mode={mode})")

                        # Init LLM if not already created, or reset for new turn
                        if not llm_service:
                            llm_service = GeminiLLMService(mode=mode)
                        elif llm_service.mode != mode:
                            llm_service = GeminiLLMService(mode=mode)
                        last_sent_final_text = ""
                        opening_text = llm_service.get_opening_greeting() if llm_service else ""

                        # Start Soniox STT session
                        success = await stt_service.start_session(
                            language_hints=["en"]
                        )
                        if success:
                            soniox_started = True
                            receiver_task = asyncio.create_task(soniox_receiver())
                            await websocket.send_json(
                                {
                                    "type": "status",
                                    "message": f"Recording started — {mode} mode",
                                }
                            )
                            if opening_text:
                                await send_ai_output(opening_text)
                        else:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": "Failed to start Soniox session",
                                }
                            )

                    # ── Stop recording ───────────────────────────
                    elif msg_type == "stop_recording":
                        logger.info(f"[{client_id}] Stop recording")

                        # 1. Stop Soniox receiver
                        soniox_started = False
                        if receiver_task:
                            receiver_task.cancel()
                            try:
                                await receiver_task
                            except asyncio.CancelledError:
                                pass
                            receiver_task = None

                        # 2. End Soniox session (drains final tokens)
                        await stt_service.end_session()

                        # 3. Get accumulated finalized transcript
                        full_text = stt_service.get_accumulated_text().strip()

                        await websocket.send_json(
                            {"type": "status", "message": "Recording stopped"}
                        )

                        # 4. Flush unsent finalized text (if user stops mid-turn)
                        if full_text and full_text != last_sent_final_text:
                            if full_text.startswith(last_sent_final_text):
                                pending_text = full_text[len(last_sent_final_text):].strip()
                            else:
                                pending_text = full_text

                            if pending_text:
                                await websocket.send_json(
                                    {"type": "turn_complete", "text": pending_text}
                                )
                                last_sent_final_text = full_text
                                await send_to_llm(pending_text)
                        else:
                            logger.info(f"[{client_id}] No unsent transcript to flush")

                    # ── Set mode (without starting) ──────────────
                    elif msg_type == "set_mode":
                        mode = message.get("mode", "restaurant")
                        logger.info(f"[{client_id}] Mode set to {mode}")

                    # ── Reset conversation ────────────────────────
                    elif msg_type == "reset_conversation":
                        if llm_service:
                            llm_service.reset()
                        llm_service = None
                        last_sent_final_text = ""
                        await websocket.send_json(
                            {"type": "status", "message": "Conversation reset"}
                        )

                    else:
                        logger.warning(
                            f"[{client_id}] Unknown message type: {msg_type}"
                        )

                except json.JSONDecodeError:
                    logger.warning(f"[{client_id}] Invalid JSON received")

            # Binary audio data
            elif "bytes" in data:
                audio_bytes = data["bytes"]
                if soniox_started:
                    await stt_service.send_audio(audio_bytes)
                else:
                    logger.debug(
                        f"[{client_id}] Audio received but STT not started"
                    )

    except WebSocketDisconnect:
        logger.info(f"[{client_id}] WebSocket disconnected")

    except Exception as e:
        logger.error(f"[{client_id}] WebSocket error: {e}")

    finally:
        soniox_started = False
        if receiver_task:
            receiver_task.cancel()
            try:
                await receiver_task
            except asyncio.CancelledError:
                pass
        if stt_service.soniox_ws:
            await stt_service.end_session()
        manager.disconnect(client_id)
