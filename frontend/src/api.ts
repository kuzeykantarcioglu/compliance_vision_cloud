import axios from "axios";
import type { Policy, AnalyzeResponse } from "./types";

const api = axios.create({
  baseURL: "/api",
  timeout: 300_000, // 5 min — VLM calls can take a while
});

export async function analyzeVideo(
  videoFile: File,
  policy: Policy,
  onStageChange?: (stage: string) => void
): Promise<AnalyzeResponse> {
  onStageChange?.("uploading");

  const formData = new FormData();
  formData.append("video", videoFile);
  formData.append("policy_json", JSON.stringify(policy));

  // Stage transitions are approximate — we can't see inside the backend
  // but we know the pipeline order
  const stageTimer = setTimeout(() => onStageChange?.("detecting"), 1000);
  const stageTimer2 = setTimeout(() => onStageChange?.("analyzing"), 5000);
  const stageTimer3 = setTimeout(() => onStageChange?.("evaluating"), 15000);

  try {
    const res = await api.post<AnalyzeResponse>("/analyze/", formData, {
      headers: { "Content-Type": "multipart/form-data" },
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
): Promise<AnalyzeResponse> {
  try {
    const res = await api.post<AnalyzeResponse>("/analyze/frame", {
      image_base64: imageBase64,
      policy_json: JSON.stringify(policy),
    });
    return res.data;
  } catch (err: any) {
    const msg = err.response?.data?.detail || err.message || "Unknown error";
    return { status: "error", report: null, error: msg };
  }
}

export async function healthCheck(): Promise<{ status: string; openai_key_set: boolean }> {
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
