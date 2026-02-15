/**
 * API client for async video processing with WebSocket support
 */

import type { Policy, Report, AnalyzeResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace("http", "ws");

export interface TaskStatus {
  task_id: string;
  state: string;
  ready: boolean;
  successful: boolean | null;
  progress: {
    stage: string;
    progress: number;
    message: string;
  };
  error: string | null;
  result?: any;
  message?: string;
}

export interface QueueStats {
  active: number;
  scheduled: number;
  reserved: number;
  workers_online: number;
}

/**
 * Start async video analysis. Returns immediately with a task ID.
 */
export async function startAsyncAnalysis(
  videoFile: File,
  policy: Policy
): Promise<{ task_id: string; status_url: string }> {
  const formData = new FormData();
  formData.append("video", videoFile);
  formData.append("policy_json", JSON.stringify(policy));

  const response = await fetch(`${API_BASE}/async/analyze`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Analysis failed: ${error}`);
  }

  return response.json();
}

/**
 * Check the status of an async task
 */
export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const response = await fetch(`${API_BASE}/async/status/${taskId}`);
  
  if (!response.ok) {
    throw new Error(`Failed to get task status: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Cancel a running task
 */
export async function cancelTask(taskId: string): Promise<boolean> {
  const response = await fetch(`${API_BASE}/async/cancel/${taskId}`, {
    method: "DELETE",
  });

  const result = await response.json();
  return result.success;
}

/**
 * Get queue statistics
 */
export async function getQueueStats(): Promise<QueueStats> {
  const response = await fetch(`${API_BASE}/async/queue/stats`);
  return response.json();
}

/**
 * Connect to WebSocket for real-time task updates
 */
export class TaskWebSocket {
  private ws: WebSocket | null = null;
  private taskId: string;
  private onUpdate: (status: TaskStatus) => void;
  private onComplete: (report: Report) => void;
  private onError: (error: string) => void;
  private reconnectAttempts = 0;
  private maxReconnects = 5;

  constructor(
    taskId: string,
    onUpdate: (status: TaskStatus) => void,
    onComplete: (report: Report) => void,
    onError: (error: string) => void
  ) {
    this.taskId = taskId;
    this.onUpdate = onUpdate;
    this.onComplete = onComplete;
    this.onError = onError;
    this.connect();
  }

  private connect() {
    const wsUrl = `${WS_BASE}/ws/task/${this.taskId}`;
    console.log(`Connecting to WebSocket: ${wsUrl}`);

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log(`WebSocket connected for task ${this.taskId}`);
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      } catch (e) {
        console.error("Failed to parse WebSocket message:", e);
      }
    };

    this.ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      this.onError("Connection error");
    };

    this.ws.onclose = (event) => {
      console.log(`WebSocket closed: ${event.code} - ${event.reason}`);
      
      // Auto-reconnect if not intentional close
      if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnects) {
        this.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), delay);
      }
    };

    // Send periodic pings to keep connection alive
    setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send("ping");
      }
    }, 30000);
  }

  private handleMessage(data: TaskStatus) {
    this.onUpdate(data);

    // Check if task is complete
    if (data.ready && data.successful && data.result?.report) {
      this.onComplete(data.result.report);
      this.close();
    } else if (data.ready && !data.successful) {
      this.onError(data.error || "Task failed");
      this.close();
    }
  }

  public close() {
    if (this.ws) {
      this.ws.close(1000, "Task complete");
      this.ws = null;
    }
  }
}

/**
 * Monitor all system activity via WebSocket
 */
export class SystemMonitorWebSocket {
  private ws: WebSocket | null = null;
  private onStats: (stats: any) => void;

  constructor(onStats: (stats: any) => void) {
    this.onStats = onStats;
    this.connect();
  }

  private connect() {
    const wsUrl = `${WS_BASE}/ws/monitor`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.onStats(data);
      } catch (e) {
        console.error("Failed to parse monitor message:", e);
      }
    };

    this.ws.onerror = (error) => {
      console.error("Monitor WebSocket error:", error);
    };

    this.ws.onclose = () => {
      // Auto-reconnect after 5 seconds
      setTimeout(() => this.connect(), 5000);
    };
  }

  public close() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}