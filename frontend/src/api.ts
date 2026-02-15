import axios from "axios";
import type { Policy, AnalyzeResponse, AIProvider } from "./types";

const api = axios.create({
  baseURL: "/api",
  timeout: 300_000, // 5 min — VLM calls can take a while
});

export async function analyzeVideo(
  videoFile: File,
  policy: Policy,
  onStageChange?: (stage: string) => void,
  onUploadProgress?: (percent: number) => void
): Promise<AnalyzeResponse> {
  onStageChange?.("uploading");

  const formData = new FormData();
  formData.append("video", videoFile);
  formData.append("policy_json", JSON.stringify(policy));

  // Stage transitions are approximate — we can't see inside the backend
  // but we know the pipeline order
  let uploadComplete = false;
  const stageTimer = setTimeout(() => {
    if (uploadComplete) onStageChange?.("detecting");
  }, 1000);
  const stageTimer2 = setTimeout(() => {
    if (uploadComplete) onStageChange?.("analyzing");
  }, 5000);
  const stageTimer3 = setTimeout(() => {
    if (uploadComplete) onStageChange?.("evaluating");
  }, 15000);

  try {
    const res = await api.post<AnalyzeResponse>("/analyze/", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onUploadProgress?.(percent);
          if (percent === 100) {
            uploadComplete = true;
            // Give server a moment to process, then move to detecting
            setTimeout(() => onStageChange?.("detecting"), 500);
          }
        }
      },
    });
    clearTimeout(stageTimer);
    clearTimeout(stageTimer2);
    clearTimeout(stageTimer3);
    return res.data;
  } catch (err: any) {
    clearTimeout(stageTimer);
    clearTimeout(stageTimer2);
    clearTimeout(stageTimer3);
    const msg = err.response?.data?.detail || err.message || "Unknown error";
    return { status: "error", report: null, error: msg };
  }
}

/** Real-time frame analysis: send a single JPEG snapshot + policy, get report back. */
export async function analyzeFrame(
  imageBase64: string,
  policy: Policy,
  provider: AIProvider = "openai",
): Promise<AnalyzeResponse> {
  try {
    const res = await api.post<AnalyzeResponse>("/analyze/frame", {
      image_base64: imageBase64,
      policy_json: JSON.stringify(policy),
      provider,
    });
    return res.data;
  } catch (err: any) {
    const msg = err.response?.data?.detail || err.message || "Unknown error";
    return { status: "error", report: null, error: msg };
  }
}

/** DGX batch frame analysis: send multiple JPEG frames (captured over ~3s) as a video clip. */
export async function analyzeFrameBatch(
  frames: string[],
  policy: Policy,
): Promise<AnalyzeResponse> {
  try {
    const res = await api.post<AnalyzeResponse>("/analyze/frame", {
      image_base64: "",
      frames,
      policy_json: JSON.stringify(policy),
      provider: "dgx",
    });
    return res.data;
  } catch (err: any) {
    const msg = err.response?.data?.detail || err.message || "Unknown error";
    return { status: "error", report: null, error: msg };
  }
}

/** DGX parallel batch analysis: send multiple frame batches concurrently for maximum speed. */
export async function analyzeFrameBatchParallel(
  batches: string[][],
  policy: Policy,
  maxConcurrent: number = 3,
): Promise<AnalyzeResponse> {
  try {
    const res = await api.post<AnalyzeResponse>("/analyze/frame/parallel", {
      batches,
      policy_json: JSON.stringify(policy),
      max_concurrent: maxConcurrent,
    });
    return res.data;
  } catch (err: any) {
    const msg = err.response?.data?.detail || err.message || "Unknown error";
    return { status: "error", report: null, error: msg };
  }
}

/** Send an audio blob for Whisper transcription (background audio recording). */
export async function transcribeAudio(
  audioBlob: Blob,
): Promise<{ status: string; transcript: { full_text: string; segments: { start: number; end: number; text: string }[]; language: string; duration: number } | null; error?: string }> {
  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, `audio-${Date.now()}.webm`);
    const res = await api.post("/analyze/transcribe", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 30_000,
    });
    return res.data;
  } catch (err: any) {
    const msg = err.response?.data?.detail || err.message || "Transcription failed";
    return { status: "error", transcript: null, error: msg };
  }
}

/** Reset backend compliance state (call on session clear). */
export async function resetComplianceState(): Promise<void> {
  try {
    await api.post("/analyze/reset");
  } catch (err) {
    console.warn("Failed to reset compliance state:", err);
  }
}

export async function healthCheck(): Promise<{ status: string; openai_key_set: boolean; dgx?: { status: string; url?: string; error?: string } }> {
  const res = await api.get("/health");
  return res.data;
}

export interface PollyMessage {
  role: "user" | "assistant";
  content: string;
}

export interface PollyResponse {
  message: string;
  policy: Policy;
  suggestions: string[];
}

export async function pollyChatApi(
  message: string,
  currentPolicy: Policy,
  history: PollyMessage[]
): Promise<PollyResponse> {
  const res = await api.post<PollyResponse>("/polly/chat", {
    message,
    current_policy: currentPolicy,
    history,
  });
  return res.data;
}
