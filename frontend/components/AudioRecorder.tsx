"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioWebSocket } from "@/lib/websocket";

/* ── Types ──────────────────────────────────────────────────── */

interface LogEntry {
  time: string;
  message: string;
  type: "info" | "sent" | "received" | "error";
}

interface TranscriptEntry {
  text: string;
  finalText: string;
  confidence: number;
  isComplete: boolean;
}

interface AIResponse {
  text: string;
  functionCalled: boolean;
  functionName?: string;
  functionArgs?: Record<string, unknown>;
}

interface ConversationTurn {
  role: "user" | "ai";
  text: string;
  timestamp: string;
}

type Mode = "restaurant" | "ngo";

interface AudioRecorderProps {
  onDonationUpdate?: () => void;
}

/* ── Component ──────────────────────────────────────────────── */

export default function AudioRecorder({ onDonationUpdate }: AudioRecorderProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isAiSpeaking, setIsAiSpeaking] = useState(false);
  const [mode, setMode] = useState<Mode>("restaurant");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [transcript, setTranscript] = useState<TranscriptEntry | null>(null);
  const [aiResponse, setAiResponse] = useState<AIResponse | null>(null);
  const [conversation, setConversation] = useState<ConversationTurn[]>([]);
  const [extractedData, setExtractedData] = useState<Record<string, unknown>[]>(
    []
  );
  const [statusMessage, setStatusMessage] = useState("");

  const wsRef = useRef<AudioWebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const logsEndRef = useRef<HTMLDivElement | null>(null);
  const convEndRef = useRef<HTMLDivElement | null>(null);
  const isRecordingRef = useRef(false); // stable ref for callbacks
  const accumulatedTextRef = useRef(""); // accumulate transcript while recording
  const isAiSpeakingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const addLog = useCallback(
    (message: string, type: LogEntry["type"] = "info") => {
      const time = new Date().toLocaleTimeString("en-US", { hour12: false });
      setLogs((prev) => [...prev.slice(-50), { time, message, type }]);
    },
    []
  );

  const ts = () => new Date().toLocaleTimeString("en-US", { hour12: false });

  const playAiAudio = useCallback(
    async (audioBase64: string, mimeType: string) => {
      const audio = audioRef.current;
      if (!audio || !audioBase64) return;

      try {
        isAiSpeakingRef.current = true;
        setIsAiSpeaking(true);
        addLog("🔊 AI speaking...", "info");

        audio.pause();
        audio.currentTime = 0;
        audio.src = `data:${mimeType};base64,${audioBase64}`;
        await audio.play();
      } catch (err) {
        isAiSpeakingRef.current = false;
        setIsAiSpeaking(false);
        addLog(`Audio play failed: ${String(err)}`, "error");
      }
    },
    [addLog]
  );

  // Auto-scroll
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);
  useEffect(() => {
    convEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation]);

  /* ── WebSocket ────────────────────────────────────────────── */

  const connectWS = useCallback(async () => {
    try {
      const ws = new AudioWebSocket();
      wsRef.current = ws;

      ws.onMessage((data) => {
        const msgType = data.type as string;

        if (msgType === "transcript") {
          const entry: TranscriptEntry = {
            text: (data.text as string) || "",
            finalText: (data.final_text as string) || "",
            confidence: (data.confidence as number) || 0,
            isComplete: (data.is_complete as boolean) || false,
          };
          setTranscript(entry);

          // While recording: just accumulate the final text (don't add to conversation yet)
          if (entry.finalText.trim()) {
            accumulatedTextRef.current = entry.finalText.trim();
          }
        } else if (msgType === "turn_complete") {
          const userText = ((data.text as string) || "").trim();
          if (userText) {
            setConversation((prev) => [
              ...prev,
              { role: "user", text: userText, timestamp: ts() },
            ]);
            addLog(`User: ${userText.slice(0, 60)}...`, "received");
            accumulatedTextRef.current = "";
          }
        } else if (msgType === "ai_response") {
          const resp: AIResponse = {
            text: (data.text as string) || "",
            functionCalled: data.function_called as boolean,
            functionName: data.function_name as string | undefined,
            functionArgs: data.function_args as Record<string, unknown> | undefined,
          };
          setAiResponse(resp);
          addLog(`AI: ${resp.text.slice(0, 60)}...`, "received");

          // Add AI turn to conversation
          setConversation((prev) => [
            ...prev,
            { role: "ai", text: resp.text, timestamp: ts() },
          ]);

          // Track extracted data
          if (resp.functionCalled && resp.functionArgs) {
            setExtractedData((prev) => [...prev, resp.functionArgs!]);
            addLog(
              `📦 Donation recorded: ${JSON.stringify(resp.functionArgs)}`,
              "received"
            );
          }
        } else if (msgType === "ai_audio") {
          const audioBase64 = (data.audio_base64 as string) || "";
          const mimeType = (data.mime_type as string) || "audio/mpeg";
          void playAiAudio(audioBase64, mimeType);
        } else if (msgType === "status") {
          setStatusMessage(data.message as string);
          addLog(data.message as string, "info");
        } else if (msgType === "error") {
          addLog(`Error: ${data.message}`, "error");
        } else if (msgType === "donation_update") {
          addLog(`Dashboard: new donation`, "received");
          onDonationUpdate?.();
        }
      });

      await ws.connect();
      setIsConnected(true);
      addLog("Connected to backend", "info");
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      addLog(`Connection failed: ${errorMsg}`, "error");
      setStatusMessage(
        `Failed to connect. Make sure backend is running on ${
          process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000"
        }`
      );
      setIsConnected(false);
    }
  }, [addLog, playAiAudio]);

  const disconnectWS = useCallback(() => {
    wsRef.current?.disconnect();
    wsRef.current = null;
    setIsConnected(false);
    addLog("Disconnected", "info");
  }, [addLog]);

  // Connect on mount
  useEffect(() => {
    connectWS();
    return () => {
      wsRef.current?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Recording ────────────────────────────────────────────── */

  const startRecording = async () => {
    if (isAiSpeakingRef.current) {
      addLog("Wait for AI to finish speaking", "error");
      return;
    }

    if (!wsRef.current?.isConnected) {
      addLog("Not connected to backend", "error");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      const audioTrack = stream.getAudioTracks()[0];
      const settings = audioTrack?.getSettings();
      addLog(
        `Mic: ${settings?.sampleRate || "?"}Hz, ch=${settings?.channelCount || "?"}`,
        "info"
      );

      // Tell backend to start (pass mode)
      wsRef.current.sendJSON({ type: "start_recording", mode });

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";
      if (!mimeType) throw new Error("No supported audio format found");

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType,
        bitsPerSecond: 128000,
      });

      mediaRecorder.ondataavailable = (event) => {
        if (
          event.data.size > 0 &&
          wsRef.current?.isConnected &&
          !isAiSpeakingRef.current
        ) {
          wsRef.current.sendAudio(event.data);
        }
      };

      mediaRecorder.start(1000);
      mediaRecorderRef.current = mediaRecorder;

      isRecordingRef.current = true;
      accumulatedTextRef.current = "";
      setIsRecording(true);
      setTranscript(null);
      setAiResponse(null);
      addLog(`Recording started (${mode} mode, ${mimeType})`, "info");
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        addLog("Microphone access denied. Please allow mic access.", "error");
      } else {
        addLog(`Mic error: ${err}`, "error");
      }
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    wsRef.current?.sendJSON({ type: "stop_recording" });
    isRecordingRef.current = false;
    setIsRecording(false);
    addLog("Recording stopped", "info");
  };

  const resetConversation = () => {
    wsRef.current?.sendJSON({ type: "reset_conversation" });
    setConversation([]);
    setTranscript(null);
    setAiResponse(null);
    setExtractedData([]);
    addLog("Conversation reset", "info");
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onEnded = () => {
      isAiSpeakingRef.current = false;
      setIsAiSpeaking(false);
    };
    const onPause = () => {
      if (audio.ended) return;
      isAiSpeakingRef.current = false;
      setIsAiSpeaking(false);
    };

    audio.addEventListener("ended", onEnded);
    audio.addEventListener("pause", onPause);
    return () => {
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("pause", onPause);
    };
  }, []);

  /* ── Helpers ──────────────────────────────────────────────── */

  const confidenceColor = (c: number) => {
    if (c >= 0.8) return "bg-green-100 text-green-800 border-green-300";
    if (c >= 0.5) return "bg-yellow-100 text-yellow-800 border-yellow-300";
    return "bg-red-100 text-red-800 border-red-300";
  };

  const foodLabel: Record<string, string> = {
    rice_curry: "🍛 Rice & Curry",
    bread: "🍞 Bread",
    mixed: "🥗 Mixed",
    other: "📦 Other",
  };

  /* ── Render ───────────────────────────────────────────────── */

  return (
    <>
    <div className="space-y-6">
      {/* ── Mode Selector + Connection ───────────────────────── */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">
            🎙️ Voice Agent
          </h2>
          <div className="flex items-center gap-3">
            <span
              className={`inline-block w-3 h-3 rounded-full ${
                isConnected ? "bg-green-500" : "bg-red-500"
              }`}
            />
            <span className="text-sm text-gray-600">
              {isConnected ? "Connected" : "Disconnected"}
            </span>
            {!isConnected && (
              <button
                onClick={connectWS}
                className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 cursor-pointer"
              >
                Retry
              </button>
            )}
          </div>
        </div>

        {/* Mode radio buttons */}
        <div className="flex gap-4 mb-4">
          {(["restaurant", "ngo"] as Mode[]).map((m) => (
            <label
              key={m}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg border cursor-pointer transition-all ${
                mode === m
                  ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                  : "border-gray-200 text-gray-600 hover:border-gray-300"
              }`}
            >
              <input
                type="radio"
                name="mode"
                value={m}
                checked={mode === m}
                onChange={() => setMode(m)}
                disabled={isRecording}
                className="accent-indigo-600"
              />
              {m === "restaurant" ? "🏪 Restaurant Mode" : "🚐 NGO / Volunteer Mode"}
            </label>
          ))}
        </div>

        {statusMessage && (
          <p className="text-sm text-indigo-600 mb-4">{statusMessage}</p>
        )}

        {/* Controls */}
        <div className="flex gap-3">
          {!isRecording ? (
            <button
              onClick={startRecording}
              disabled={!isConnected || isAiSpeaking}
              className={`flex-1 py-3 px-6 rounded-lg font-medium text-white transition-all ${
                isConnected && !isAiSpeaking
                  ? "bg-green-600 hover:bg-green-700 cursor-pointer"
                  : "bg-gray-400 cursor-not-allowed"
              }`}
            >
              🎤 Start Recording
            </button>
          ) : (
            <button
              onClick={stopRecording}
              className="flex-1 py-3 px-6 rounded-lg font-medium text-white bg-red-600 hover:bg-red-700 cursor-pointer"
            >
              ⏹ Stop Recording
            </button>
          )}
          <button
            onClick={resetConversation}
            className="py-3 px-4 rounded-lg font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 cursor-pointer"
          >
            🔄 Reset
          </button>
        </div>

        {isRecording && (
          <div className="flex items-center gap-2 mt-4">
            <span className="relative flex h-4 w-4">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-4 w-4 bg-red-500" />
            </span>
            <span className="text-sm text-red-600 font-medium">
              Recording...
            </span>
          </div>
        )}
        {isAiSpeaking && (
          <div className="mt-3 text-sm text-indigo-700 font-medium">🔊 AI Speaking...</div>
        )}
      </div>

      {/* ── Live Transcript ──────────────────────────────────── */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">
          📝 Live Transcript
        </h2>

        {transcript ? (
          <div className="space-y-3">
            <div className="bg-gray-50 rounded-lg p-4 min-h-[60px]">
              <p className="text-gray-900 text-lg leading-relaxed">
                <span className="font-medium">{transcript.finalText}</span>
                <span className="text-gray-400">
                  {transcript.text.slice(transcript.finalText.length)}
                </span>
              </p>
            </div>
            <span
              className={`text-sm font-mono px-2 py-1 rounded border ${confidenceColor(
                transcript.confidence
              )}`}
            >
              Confidence: {Math.round(transcript.confidence * 100)}%
            </span>
          </div>
        ) : (
          <p className="text-gray-400 italic">
            {isRecording ? "Listening... speak now" : "Start recording to begin"}
          </p>
        )}
      </div>

      {/* ── AI Response ──────────────────────────────────────── */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">
          🤖 AI Response
        </h2>

        {aiResponse ? (
          <div className="space-y-3">
            <div className="bg-indigo-50 rounded-lg p-4">
              <p className="text-indigo-900 text-lg">{aiResponse.text}</p>
            </div>
            {aiResponse.functionCalled && (
              <div className="text-sm text-green-700 bg-green-50 rounded px-3 py-2">
                ✅ Function called: <span className="font-mono">{aiResponse.functionName}</span>
              </div>
            )}
          </div>
        ) : (
          <p className="text-gray-400 italic">
            AI will respond after you speak...
          </p>
        )}
      </div>

      {/* ── Conversation History ─────────────────────────────── */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">
          💬 Conversation
        </h2>
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {conversation.length === 0 ? (
            <p className="text-gray-400 italic">No conversation yet</p>
          ) : (
            conversation.map((turn, i) => (
              <div
                key={i}
                className={`flex ${
                  turn.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[80%] rounded-lg px-4 py-2 ${
                    turn.role === "user"
                      ? "bg-blue-100 text-blue-900"
                      : "bg-indigo-100 text-indigo-900"
                  }`}
                >
                  <p className="text-xs font-medium opacity-60 mb-1">
                    {turn.role === "user" ? "You" : "AI"} · {turn.timestamp}
                  </p>
                  <p className="text-sm">{turn.text}</p>
                </div>
              </div>
            ))
          )}
          <div ref={convEndRef} />
        </div>
      </div>

      {/* ── Extracted Data ───────────────────────────────────── */}
      {extractedData.length > 0 && (
        <div className="bg-white rounded-lg shadow-lg p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">
            📦 Extracted Donations
          </h2>
          <div className="space-y-2">
            {extractedData.map((d, i) => (
              <div
                key={i}
                className="flex items-center gap-4 bg-green-50 border border-green-200 rounded-lg px-4 py-3"
              >
                <span className="text-2xl">
                  {foodLabel[d.food_type as string] ?? "📦"}
                </span>
                <div>
                  <p className="font-medium text-green-900">
                    {(d.food_type as string)?.replace("_", " & ")} —{" "}
                    {d.quantity_kg as number} kg
                  </p>
                  {d.serves_people ? (
                    <p className="text-sm text-green-700">
                      Serves ~{d.serves_people as number} people
                    </p>
                  ) : null}
                  {d.donation_id ? (
                    <p className="text-xs text-green-600">
                      ID #{d.donation_id as number}
                    </p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Activity Log ─────────────────────────────────────── */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">📋 Activity Log</h2>
          <button
            onClick={() => setLogs([])}
            className="text-xs text-gray-400 hover:text-gray-600 cursor-pointer"
          >
            Clear
          </button>
        </div>
        <div className="bg-gray-900 rounded-lg p-4 max-h-40 overflow-y-auto font-mono text-xs">
          {logs.length === 0 ? (
            <p className="text-gray-500">No activity yet</p>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="py-0.5">
                <span className="text-gray-500">{log.time}</span>{" "}
                <span
                  className={
                    log.type === "error"
                      ? "text-red-400"
                      : log.type === "sent"
                        ? "text-blue-400"
                        : log.type === "received"
                          ? "text-green-400"
                          : "text-gray-300"
                  }
                >
                  {log.type === "sent"
                    ? "→ "
                    : log.type === "received"
                      ? "← "
                      : ""}
                  {log.message}
                </span>
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
    <audio ref={audioRef} hidden preload="auto" />
    </>
  );
}
