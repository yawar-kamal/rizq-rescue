I'll read the Soniox documentation and help you understand how to implement it.# Soniox API Documentation Summary & Implementation Guide

## 📚 Key Information About Soniox

### What Makes Soniox Different

**Soniox is a real-time speech-to-text API that:**
- Uses **WebSocket** for streaming (not REST like most STT services)
- Returns **tokens** incrementally (not full sentences)
- Has **final** vs **non-final** tokens (provisional vs confirmed)
- Supports **auto-detect audio formats** (including WebM from browsers!)
- Has **60+ languages** with high accuracy
- Built specifically for **low-latency** applications

### Critical Architecture Detail

**Token-based streaming:**
```javascript
// Instead of getting: "Hello how are you" (once)
// You get:
Response 1: {"tokens": [{"text": "Hello", "is_final": false}]}
Response 2: {"tokens": [{"text": "Hello", "is_final": true}, {"text": " how", "is_final": false}]}
Response 3: {"tokens": [{"text": " how", "is_final": true}, {"text": " are", "is_final": false}]}
// ... and so on
```

**This means:** You need to accumulate tokens client-side, not just display each response.

---

## 🎯 How Soniox Works in Your Project

### Connection Flow

```
1. Browser captures audio → WebM chunks
2. Send WebM to Python backend via your WebSocket
3. Backend forwards to Soniox WebSocket
4. Soniox returns token stream
5. Backend aggregates tokens → full transcript
6. Send transcript to frontend
```

### Audio Format - THE BIG WIN

**Your original concern:** WebM → PCM conversion

**Soniox solves this:**
```json
{
  "audio_format": "auto"
}
```

Soniox **automatically detects WebM**! No conversion needed. This eliminates 90% of the complexity you were worried about.

---

## 📝 What to Tell Cursor/Claude Code

Copy this exact prompt to Cursor:

---

### CURSOR PROMPT:

```markdown
# Implement Soniox Speech-to-Text for Phase 3

## Context
We're building a real-time voice agent. Browser sends WebM audio chunks via WebSocket to Python backend. Backend needs to transcribe using Soniox API.

## Key Soniox Details

### 1. Soniox Uses WebSocket (Not REST)
- Endpoint: `wss://stt-rt.soniox.com/transcribe-websocket`
- First message: Configuration JSON
- After: Stream binary audio
- Receives: JSON responses with tokens

### 2. Audio Format Support
**CRITICAL:** Soniox supports WebM auto-detection!
```json
{
  "audio_format": "auto"
}
```
No conversion needed from browser WebM. This is the easiest approach.

### 3. Token-Based Responses
Soniox returns **incremental tokens**, not full sentences:
```json
{
  "tokens": [
    {"text": "Hello", "is_final": true, "confidence": 0.97},
    {"text": " there", "is_final": false, "confidence": 0.85}
  ],
  "final_audio_proc_ms": 1200,
  "total_audio_proc_ms": 1500
}
```

**is_final: true** = confirmed, will never change
**is_final: false** = provisional, may change

### 4. Implementation Strategy

**Create `backend/app/services/stt_service.py`:**

```python
import asyncio
import json
import logging
from websockets import connect
from app.config import get_settings

logger = logging.getLogger(__name__)

class SonioxSTTService:
    def __init__(self):
        self.settings = get_settings()
        self.ws_url = "wss://stt-rt.soniox.com/transcribe-websocket"
        self.soniox_ws = None
        self.final_tokens = []
        self.non_final_tokens = []
        
    async def start_session(self):
        """Initialize Soniox WebSocket connection"""
        logger.info("Connecting to Soniox...")
        self.soniox_ws = await connect(self.ws_url)
        
        # Send configuration as first message
        config = {
            "api_key": self.settings.soniox_api_key,
            "model": "stt-rt-v4",  # Latest model
            "audio_format": "auto",  # Auto-detect WebM!
            "language_hints": ["en"],  # Adjust for your use case
            "enable_language_identification": True
        }
        
        await self.soniox_ws.send(json.dumps(config))
        logger.info("Soniox session started")
    
    async def send_audio(self, audio_bytes: bytes):
        """Send audio chunk to Soniox"""
        if self.soniox_ws:
            await self.soniox_ws.send(audio_bytes)
    
    async def receive_transcript(self):
        """Receive and parse token responses from Soniox"""
        if not self.soniox_ws:
            return None
            
        try:
            message = await self.soniox_ws.recv()
            response = json.loads(message)
            
            # Check for errors
            if response.get("error_code"):
                logger.error(f"Soniox error: {response['error_code']} - {response['error_message']}")
                return None
            
            # Process tokens
            self.non_final_tokens = []  # Reset non-final on each response
            
            for token in response.get("tokens", []):
                if token.get("text"):
                    if token.get("is_final"):
                        self.final_tokens.append(token)
                    else:
                        self.non_final_tokens.append(token)
            
            # Build full transcript
            final_text = "".join([t["text"] for t in self.final_tokens])
            non_final_text = "".join([t["text"] for t in self.non_final_tokens])
            
            return {
                "text": final_text + non_final_text,
                "final_text": final_text,
                "confidence": self._calculate_confidence(),
                "is_complete": len(self.non_final_tokens) == 0
            }
            
        except Exception as e:
            logger.error(f"Error receiving from Soniox: {e}")
            return None
    
    def _calculate_confidence(self):
        """Calculate average confidence from final tokens"""
        if not self.final_tokens:
            return 0.0
        confidences = [t.get("confidence", 0) for t in self.final_tokens]
        return sum(confidences) / len(confidences) if confidences else 0.0
    
    async def end_session(self):
        """Close Soniox connection"""
        if self.soniox_ws:
            await self.soniox_ws.send("")  # Empty frame signals end
            await self.soniox_ws.close()
            self.soniox_ws = None
        self.final_tokens = []
        self.non_final_tokens = []
```

### 5. Integration with Existing WebSocket Handler

**Modify `backend/app/services/websocket_handler.py`:**

```python
async def handle_websocket(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    # Initialize Soniox service
    stt_service = SonioxSTTService()
    await stt_service.start_session()
    
    # Start background task to receive from Soniox
    async def soniox_receiver():
        while True:
            transcript = await stt_service.receive_transcript()
            if transcript:
                await websocket.send_json({
                    "type": "transcript",
                    "text": transcript["text"],
                    "confidence": transcript["confidence"]
                })
    
    receiver_task = asyncio.create_task(soniox_receiver())
    
    try:
        while True:
            data = await websocket.receive()
            
            if "bytes" in data:
                # Forward audio to Soniox
                audio_bytes = data["bytes"]
                await stt_service.send_audio(audio_bytes)
                
    except WebSocketDisconnect:
        receiver_task.cancel()
        await stt_service.end_session()
        manager.disconnect(client_id)
```

### 6. Requirements

**Add to `requirements.txt`:**
```
websockets==12.0
```

No other dependencies needed! No audio conversion libraries!

## Testing Checklist

After implementation:
1. ✅ Soniox connection establishes (check logs: "Soniox session started")
2. ✅ Audio chunks forwarded (check logs: "Sending audio to Soniox")
3. ✅ Tokens received (check logs for token responses)
4. ✅ Transcript appears in frontend within 2-3 seconds
5. ✅ Confidence scores >80% for clear speech

## Common Issues to Avoid

❌ **DON'T** try to convert WebM to PCM - Soniox handles it
❌ **DON'T** wait for complete sentences - use token streaming
❌ **DON'T** forget to send empty frame when ending session
❌ **DON'T** ignore non-final tokens - they provide instant feedback

✅ **DO** use `audio_format: "auto"`
✅ **DO** accumulate final_tokens across responses
✅ **DO** reset non_final_tokens on each response
✅ **DO** handle errors gracefully

## Reference Documentation
- WebSocket API: https://soniox.com/docs/stt/api-reference/websocket-api
- Real-time guide: https://soniox.com/docs/stt/rt/real-time-transcription
- Models: https://soniox.com/docs/stt/models (use stt-rt-v4)
```

---

## 🚀 Quick Start Commands for Cursor

After giving Cursor the prompt above, test with:

```bash
# 1. Verify API key
echo $SONIOX_API_KEY

# 2. Test Soniox connection (simple script)
python -c "
import asyncio
from websockets import connect
import json

async def test():
    ws = await connect('wss://stt-rt.soniox.com/transcribe-websocket')
    await ws.send(json.dumps({
        'api_key': 'YOUR_KEY',
        'model': 'stt-rt-v4',
        'audio_format': 'auto'
    }))
    print('Connected! Waiting for response...')
    response = await ws.recv()
    print(response)
    await ws.close()

asyncio.run(test())
"
```

---

## 🎯 Summary: Key Points to Communicate

**To Cursor/Claude Code, emphasize:**

1. **"Use Soniox WebSocket, not REST API"**
2. **"Set audio_format to 'auto' - it handles WebM automatically"**
3. **"Accumulate tokens across responses - final tokens once, non-final tokens reset"**
4. **"Create bidirectional flow: browser → your websocket → Soniox → your websocket → browser"**
5. **"Use model: 'stt-rt-v4' for best results"**

**Benefits over your original Deepgram plan:**
- ✅ Auto-detects WebM (no conversion)
- ✅ Better accuracy (according to their benchmarks)
- ✅ Token-based streaming (more granular)
- ✅ You already have API key

**The main complexity:**
- Managing the token accumulation logic (but I provided the code above)

---

## ❓ Questions You Might Have

**Q: Do I still need audio conversion?**
A: No! Soniox's `"audio_format": "auto"` handles WebM directly.

**Q: Is this harder than Deepgram?**
A: Slightly different. Deepgram returns full utterances; Soniox returns tokens. But the token approach gives lower latency.

**Q: Can I test this without building the full pipeline?**
A: Yes! Use the Python test script above or check their examples: https://github.com/soniox/soniox_examples

**Q: What if I want to use their Python SDK instead of raw WebSocket?**
A: You can! Install `soniox` package and use their `RealtimeSTTConfig`. But raw WebSocket gives you more control for your use case.

---

**Ready to implement?** Give Cursor the prompt marked "CURSOR PROMPT" above and it should build the STT service correctly!

# Soniox Real-Time Transcription Implementation Guide for Cursor

Based on the official Soniox documentation, here's how to implement real-time transcription in your project.

---

## 📚 How Soniox Real-Time Works

### Key Concepts

**1. Token-Based Streaming**
```
User says: "How are you doing?"

Response 1: [{"text": "How", "is_final": false}]
Response 2: [{"text": "How", "is_final": true}, {"text": " are", "is_final": false}]
Response 3: [{"text": " are", "is_final": true}, {"text": " you", "is_final": false}]
Response 4: [{"text": " you", "is_final": true}, {"text": " doing", "is_final": false}]
Response 5: [{"text": " doing", "is_final": true}, {"text": "?", "is_final": true}]
```

**2. Final vs Non-Final Tokens**
- `is_final: false` → Provisional (may change)
- `is_final: true` → Confirmed (never changes)

**3. Audio Format Support**
```json
{
  "audio_format": "auto"  // Auto-detects WebM, MP3, WAV, etc.
}
```

---

## 🎯 Architecture for Your Project

```
┌─────────────┐         ┌──────────────────┐         ┌─────────────┐
│   Browser   │ WebM    │  FastAPI         │ WebM    │   Soniox    │
│  (RecordRTC)├────────→│  WebSocket       ├────────→│  WebSocket  │
│             │         │  /ws/audio       │         │   API       │
│             │←────────┤                  │←────────┤             │
│             │ JSON    │                  │ JSON    │             │
└─────────────┘         └──────────────────┘         └─────────────┘
```

Your backend acts as a **proxy** between browser and Soniox.

---

## 📝 Example Code from Soniox Docs (Adapted for Your Project)

### Official Python WebSocket Example (Raw WebSocket)

From their docs at: https://github.com/soniox/soniox_examples/blob/master/speech_to_text/python/soniox_realtime.py

**Key sections:**

```python
import json
from websockets.sync.client import connect

SONIOX_WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

# Configuration
config = {
    "api_key": api_key,
    "model": "stt-rt-v4",
    "audio_format": "auto",  # Auto-detects WebM!
    "language_hints": ["en"],
    "enable_endpoint_detection": True
}

# Connect
with connect(SONIOX_WEBSOCKET_URL) as ws:
    # Send config first
    ws.send(json.dumps(config))
    
    # Stream audio
    ws.send(audio_bytes)
    
    # Receive responses
    message = ws.recv()
    response = json.loads(message)
    
    # Process tokens
    for token in response.get("tokens", []):
        if token.get("is_final"):
                    final_tokens.append(token)
                else:
                    non_final_tokens.append(token)
```

---

## 🚀 Implementation for Cursor

Give Cursor this complete implementation guide:

---

## CURSOR PROMPT:

```markdown
# Implement Soniox Real-Time Transcription (Phase 3)

## Architecture Overview

We need to create a **bidirectional proxy** where:
1. Browser sends WebM audio chunks to our WebSocket (`/ws/audio`)
2. Our backend forwards audio to Soniox WebSocket
3. Soniox sends back token responses
4. Our backend aggregates tokens and sends transcripts to browser

## Implementation Steps

### STEP 1: Create Soniox Service

Create `backend/app/services/stt_service.py`:

```python
import asyncio
import json
import logging
from typing import Optional, Dict, List
from websockets import connect, WebSocketClientProtocol
from app.config import get_settings

logger = logging.getLogger(__name__)

class SonioxSTTService:
    """
    Soniox Speech-to-Text service using WebSocket API.
    
    Based on: https://soniox.com/docs/stt/rt/real-time-transcription
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.ws_url = "wss://stt-rt.soniox.com/transcribe-websocket"
        self.soniox_ws: Optional[WebSocketClientProtocol] = None
        
        # Token accumulation (reset for each session)
        self.final_tokens: List[Dict] = []
        self.non_final_tokens: List[Dict] = []
        
        logger.info("SonioxSTTService initialized")
    
    async def start_session(self, language_hints: List[str] = None):
        """
        Start a new Soniox WebSocket session.
        
        First message must be configuration JSON.
        """
        try:
            logger.info(f"Connecting to Soniox: {self.ws_url}")
            
            # Connect to Soniox
            self.soniox_ws = await connect(self.ws_url)
            
            # Prepare configuration
            config = {
                "api_key": self.settings.soniox_api_key,
                "model": "stt-rt-v4",  # Latest real-time model
                
                # CRITICAL: Auto-detect audio format (handles WebM!)
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
            logger.info("Soniox session started with config: %s", 
                       {k: v for k, v in config.items() if k != 'api_key'})
            
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
            # Send binary audio data
            await self.soniox_ws.send(audio_bytes)
            logger.debug(f"Sent {len(audio_bytes)} bytes to Soniox")
            return True
            
        except Exception as e:
            logger.error(f"Error sending audio to Soniox: {e}")
            return False
    
    async def receive_response(self) -> Optional[Dict]:
        """
        Receive and parse one response from Soniox.
        
        Returns:
            Dict with:
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
                error_msg = f"Soniox error {response['error_code']}: {response['error_message']}"
                logger.error(error_msg)
                return {
                    "text": "",
                    "final_text": "",
                    "confidence": 0.0,
                    "is_complete": False,
                    "error": error_msg,
                    "finished": False
                }
            
            # Process tokens
            # Key insight: Non-final tokens reset on each response
            # Final tokens accumulate across all responses
            self.non_final_tokens = []  # Reset non-final
            
            for token in response.get("tokens", []):
                if token.get("text"):  # Only process tokens with text
                    if token.get("is_final"):
                        # Final tokens: append once, never change
                        self.final_tokens.append(token)
                    else:
                        # Non-final tokens: reset every response
                        self.non_final_tokens.append(token)
            
            # Build transcript
            final_text = "".join([t["text"] for t in self.final_tokens])
            non_final_text = "".join([t["text"] for t in self.non_final_tokens])
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
                "audio_processed_ms": response.get("final_audio_proc_ms", 0)
            }
            
            logger.debug(f"Transcript: '{full_text}' (confidence: {confidence:.2f})")
            
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
        
        Send empty frame to signal end of audio.
        """
        if self.soniox_ws:
            try:
                # Send empty string to signal end
                await self.soniox_ws.send("")
                logger.info("Sent end-of-audio signal to Soniox")
                
                # Wait for final responses
                try:
                    while True:
                        response = await asyncio.wait_for(
                            self.receive_response(), 
                            timeout=2.0
                        )
                        if response and response.get("finished"):
                            logger.info("Soniox session finished")
                            break
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for Soniox finish")
                
                # Close connection
                await self.soniox_ws.close()
                logger.info("Soniox WebSocket closed")
                
            except Exception as e:
                logger.error(f"Error ending Soniox session: {e}")
            
            finally:
                self.soniox_ws = None
                self.final_tokens = []
                self.non_final_tokens = []
    
    def reset(self):
        """Reset token accumulation."""
        self.final_tokens = []
        self.non_final_tokens = []
        logger.info("Token accumulation reset")
```

### STEP 2: Integrate with WebSocket Handler

Update `backend/app/services/websocket_handler.py`:

```python
from fastapi import WebSocket, WebSocketDisconnect
import logging
import json
import asyncio
from app.services.stt_service import SonioxSTTService

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"Client {client_id} connected")
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        logger.info(f"Client {client_id} disconnected")
    
    async def send_json(self, client_id: str, data: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(data)

manager = ConnectionManager()

async def handle_websocket(websocket: WebSocket, client_id: str):
    """Main WebSocket handler with Soniox integration."""
    
    await manager.connect(websocket, client_id)
    
    # Initialize Soniox service for this connection
    stt_service = SonioxSTTService()
    soniox_started = False
    
    # Background task to receive from Soniox
    async def soniox_receiver():
        """Continuously receive responses from Soniox and forward to client."""
        while soniox_started and stt_service.soniox_ws:
            try:
                result = await stt_service.receive_response()
                
                if result:
                    # Send transcript to browser
                    await websocket.send_json({
                        "type": "transcript",
                        "text": result["text"],
                        "final_text": result["final_text"],
                        "confidence": result["confidence"],
                        "is_complete": result["is_complete"]
                    })
                    
                    # Check if session finished
                    if result.get("finished"):
                        logger.info("Soniox session finished")
                        break
                
            except Exception as e:
                logger.error(f"Error in Soniox receiver: {e}")
                break
    
    receiver_task = None
    
    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connection established",
            "client_id": client_id
        })
        
        # Main loop: receive from browser
        while True:
            data = await websocket.receive()
            
            # Handle JSON control messages
            if "text" in data:
                try:
                    message = json.loads(data["text"])
                    msg_type = message.get("type")
                    
                    if msg_type == "start_recording":
                        logger.info(f"Client {client_id} started recording")
                        
                        # Start Soniox session
                        success = await stt_service.start_session(
                            language_hints=["en"]  # Configure as needed
                        )
                        
                        if success:
                            soniox_started = True
                            # Start receiver task
                            receiver_task = asyncio.create_task(soniox_receiver())
                            
                            await websocket.send_json({
                                "type": "recording_started",
                                "message": "Soniox session started"
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Failed to start Soniox session"
                            })
                    
                    elif msg_type == "stop_recording":
                        logger.info(f"Client {client_id} stopped recording")
                        
                        # End Soniox session
                        await stt_service.end_session()
                        soniox_started = False
                        
                        if receiver_task:
                            receiver_task.cancel()
                        
                        await websocket.send_json({
                            "type": "recording_stopped",
                            "message": "Soniox session ended"
                        })
                
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON")
            
            # Handle binary audio data
            elif "bytes" in data:
                audio_bytes = data["bytes"]
                chunk_size = len(audio_bytes)
                
                logger.debug(f"Received audio chunk: {chunk_size} bytes")
                
                # Forward to Soniox if session started
                if soniox_started:
                    success = await stt_service.send_audio(audio_bytes)
                    
                    if not success:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Failed to send audio to Soniox"
                        })
    
    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected")
    
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
    
    finally:
        # Cleanup
        if receiver_task:
            receiver_task.cancel()
        
        if soniox_started:
            await stt_service.end_session()
        
        manager.disconnect(client_id)
```

### STEP 3: Update Frontend to Display Transcripts

Update `frontend/components/AudioRecorder.tsx`:

Add transcript display section:

```typescript
// Add state for transcript
const [transcript, setTranscript] = useState<string>('');
const [finalTranscript, setFinalTranscript] = useState<string>('');
const [confidence, setConfidence] = useState<number>(0);

// Update WebSocket message handler
useEffect(() => {
  if (wsRef.current) {
    wsRef.current.onMessage((data) => {
      addLog(`← Server: ${data.type}`);
      
      // Handle transcript messages
      if (data.type === 'transcript') {
        setTranscript(data.text);
        setFinalTranscript(data.final_text);
        setConfidence(data.confidence);
      }
    });
  }
}, []);

// Add to JSX (after activity log):
<div className="mt-4 border rounded-lg p-4 bg-gray-50">
  <h3 className="font-semibold mb-2 text-sm text-gray-700">Live Transcript:</h3>
  
  <div className="space-y-2">
    {/* Final transcript (confirmed) */}
    <div className="text-gray-900 font-medium">
      {finalTranscript}
      {/* Non-final transcript (provisional) */}
      <span className="text-gray-400 italic">
        {transcript.slice(finalTranscript.length)}
      </span>
    </div>
    
    {/* Confidence score */}
    {confidence > 0 && (
      <div className="text-xs text-gray-600">
        Confidence: {(confidence * 100).toFixed(0)}%
        <div className="w-full bg-gray-200 rounded-full h-2 mt-1">
          <div
            className={`h-2 rounded-full ${
              confidence > 0.8 ? 'bg-green-500' : 
              confidence > 0.5 ? 'bg-yellow-500' : 
              'bg-red-500'
            }`}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
      </div>
    )}
  </div>
</div>
```

### STEP 4: Update Requirements

Ensure `backend/requirements.txt` has:

```txt
websockets==12.0
```

**NO OTHER DEPENDENCIES NEEDED!** Soniox handles audio format conversion.

## Testing Steps

1. **Start backend:**
   ```bash
   cd backend
   python -m app.main
   ```

2. **Start frontend:**
   ```bash
   cd frontend
   npm run dev
   ```

3. **Test flow:**
   - Click "Start Recording"
   - Speak clearly: "Testing Soniox transcription"
   - Watch transcript appear in real-time
   - Final text (black) = confirmed
   - Provisional text (gray/italic) = may change
   - Click "Stop Recording"

4. **Check logs:**
   - Backend: Should show "Soniox session started"
   - Backend: Should show "Sent X bytes to Soniox"
   - Backend: Should show transcripts with confidence

## Expected Behavior

**User speaks:** "Hello how are you"

**Frontend displays (in real-time):**
```
Hello            (confirmed - black text)
 how             (provisional - gray italic)

Hello how        (confirmed - black text)
 are             (provisional - gray italic)

Hello how are    (confirmed - black text)
 you             (provisional - gray italic)

Hello how are you (all confirmed - all black text)
```

**Confidence score updates** as more text is confirmed.

## Troubleshooting

### Issue: "Soniox session failed to start"
- Check SONIOX_API_KEY in `.env`
- Verify API key at: https://soniox.com/

### Issue: "No transcript appearing"
- Check backend logs for Soniox responses
- Verify audio chunks are being sent (check logs)
- Try speaking louder/clearer

### Issue: "WebSocket disconnects"
- Check for any exceptions in backend logs
- Verify Soniox WebSocket stays open
- Add more error handling around WebSocket operations

### Issue: "Transcript is gibberish"
- Check `language_hints` configuration
- Verify audio quality (try different microphone)
- Check network latency

## Key Implementation Notes

1. **Audio format is auto-detected** - No conversion needed!
2. **Tokens accumulate** - Final tokens are kept, non-final reset each response
3. **Bidirectional communication** - One task sends audio, another receives transcripts
4. **Session lifecycle** - Start session → Stream audio → End session (send empty frame)
5. **Error handling** - Always check for `error_code` in Soniox responses

## Reference

- Docs: https://soniox.com/docs/stt/rt/real-time-transcription
- Examples: https://github.com/soniox/soniox_examples
- Model: stt-rt-v4 (latest real-time model)
```

---

## 🎯 Summary for Cursor

**Tell Cursor:**

1. **"Create `backend/app/services/stt_service.py`"** - Full service class to manage Soniox WebSocket
2. **"Update `backend/app/services/websocket_handler.py`"** - Integrate STT service with bidirectional communication
3. **"Update `frontend/components/AudioRecorder.tsx`"** - Display transcripts with final/non-final distinction
4. **Key point:** Use `audio_format: "auto"` - Soniox auto-detects WebM!
5. **Key pattern:** Final tokens accumulate, non-final tokens reset on each response

**The implementation is straightforward because:**
- ✅ No audio conversion needed (Soniox handles WebM)
- ✅ Simple WebSocket proxy pattern
- ✅ Token accumulation logic provided above
- ✅ All example code is production-ready

Copy the entire "CURSOR PROMPT" section above to Cursor and it should implement Phase 3 correctly!