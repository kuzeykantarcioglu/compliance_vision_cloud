// Mirrors backend/models/schemas.py

export interface PolicyRule {
  type: string;
  description: string;
  severity: "low" | "medium" | "high" | "critical";
  
  // Dual-mode compliance fields
  mode?: "incident" | "checklist";
  validity_duration?: number; // seconds
  recheck_prompt?: string;
  
  // Legacy fields
  frequency?: "always" | "at_least_once" | "at_least_n";
  frequency_count?: number;
}

export type ReferenceCategory = "people" | "badges" | "objects";

export interface ReferenceImage {
  id?: string; // Unique id for referencing in policy; generated on creation
  label: string;
  image_base64: string;
  match_mode: "must_match" | "must_not_match";
  category: ReferenceCategory;
  checks: string[];
}

export interface Policy {
  rules: PolicyRule[];
  custom_prompt: string;
  include_audio: boolean;
  reference_images: ReferenceImage[];
  /** IDs of references that should be checked. Only these are sent to VLM. Omit/empty = none checked. */
  enabled_reference_ids?: string[];
  /** Context from prior monitoring chunks about already-satisfied frequency rules. */
  prior_context?: string;
}

export interface PersonDetail {
  person_id: string;
  appearance: string;
  details: string;
}

export interface FrameObservation {
  timestamp: number;
  description: string;
  trigger: string;
  change_score: number;
  image_base64: string;
  people: PersonDetail[];
}

export interface Verdict {
  rule_type: string;
  rule_description: string;
  compliant: boolean;
  severity: "low" | "medium" | "high" | "critical";
  reason: string;
  timestamp: number | null;
  
  // Dual-mode fields
  mode?: "incident" | "checklist";
  checklist_status?: "pending" | "compliant" | "expired";
  expires_at?: number;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface TranscriptResult {
  full_text: string;
  segments: TranscriptSegment[];
  language: string;
  duration: number;
}

export interface PersonSummary {
  person_id: string;
  appearance: string;
  first_seen: number;
  last_seen: number;
  frames_seen: number;
  compliant: boolean;
  violations: string[];
  thumbnail_base64: string;
}

export interface Report {
  video_id: string;
  summary: string;
  overall_compliant: boolean;
  incidents: Verdict[];
  all_verdicts: Verdict[];
  recommendations: string[];
  frame_observations: FrameObservation[];
  person_summaries: PersonSummary[];
  transcript: TranscriptResult | null;
  analyzed_at: string;
  total_frames_analyzed: number;
  video_duration: number;
}

export interface AnalyzeResponse {
  status: "complete" | "error";
  report: Report | null;
  error: string | null;
}

// Pipeline stage tracking for loading UI
export type PipelineStage =
  | "idle"
  | "uploading"
  | "detecting"
  | "analyzing"
  | "evaluating"
  | "complete"
  | "error";

// AI provider selection
export type AIProvider = "openai" | "dgx";
