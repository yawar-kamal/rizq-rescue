/**
 * AudioWebSocket — manages the WebSocket connection to the backend
 * for real-time audio streaming + receiving transcripts.
 */

type MessageHandler = (data: Record<string, unknown>) => void;

export class AudioWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private messageHandlers: MessageHandler[] = [];
  private _clientId: string;

  constructor(url?: string) {
    this.url =
      url || process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
    this._clientId = this.generateId();
  }

  get clientId(): string {
    return this._clientId;
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED;
  }

  /** Connect to the backend WebSocket */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        const wsUrl = `${this.url}/ws/audio`;
        console.log(`[WS] Connecting to ${wsUrl}...`);
        this.ws = new WebSocket(wsUrl);

        let connectionResolved = false;
        let connectionRejected = false;

        // Connection timeout (10 seconds)
        const timeout = setTimeout(() => {
          if (!connectionResolved && !connectionRejected) {
            connectionRejected = true;
            this.ws?.close();
            reject(new Error(`WebSocket connection timeout after 10s. Is backend running on ${this.url}?`));
          }
        }, 10000);

        this.ws.onopen = () => {
          clearTimeout(timeout);
          console.log("[WS] Connected");
          this.reconnectAttempts = 0;
          connectionResolved = true;
          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            this.messageHandlers.forEach((handler) => handler(data));
          } catch (err) {
            console.error("[WS] Failed to parse message:", err);
          }
        };

        this.ws.onerror = (event) => {
          // Don't reject immediately - onerror fires during connection attempts
          // Wait for onclose to determine if connection actually failed
          console.warn("[WS] Error event (connection may still succeed):", event);
        };

        this.ws.onclose = (event) => {
          const wasClean = event.wasClean;
          const code = event.code;
          const reason = event.reason || "Unknown reason";
          
          console.log(
            `[WS] Closed (code=${code}, clean=${wasClean}, reason="${reason}")`
          );

          // If connection never opened, reject the promise
          if (!connectionResolved && !connectionRejected) {
            connectionRejected = true;
            clearTimeout(timeout);
            const errorMsg = `WebSocket connection failed (code=${code}). ` +
              `Is the backend running on ${this.url}? ` +
              `Check: 1) Backend server is running, 2) Port 8000 is accessible, 3) No firewall blocking.`;
            reject(new Error(errorMsg));
            return;
          }
          
          // Only auto-reconnect if it wasn't a clean close (unexpected disconnect)
          if (!wasClean && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(
              `[WS] Reconnecting (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`
            );
            setTimeout(() => {
              this.connect().catch(() => {});
            }, this.reconnectDelay * this.reconnectAttempts);
          } else if (wasClean) {
            // Clean close means intentional disconnect, don't reconnect
            console.log("[WS] Clean close - not reconnecting");
          }
        };

      } catch (err) {
        reject(err);
      }
    });
  }

  /** Send a JSON control message */
  sendJSON(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  /** Send binary audio data */
  sendAudio(audioBlob: Blob): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      audioBlob.arrayBuffer().then((buffer) => {
        this.ws!.send(buffer);
      });
    }
  }

  /** Register a handler for incoming messages */
  onMessage(handler: MessageHandler): void {
    this.messageHandlers.push(handler);
  }

  /** Disconnect cleanly */
  disconnect(): void {
    this.reconnectAttempts = this.maxReconnectAttempts; // prevent auto-reconnect
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.messageHandlers = [];
  }

  /** Generate a short unique client ID */
  private generateId(): string {
    return Math.random().toString(36).substring(2, 10);
  }
}

