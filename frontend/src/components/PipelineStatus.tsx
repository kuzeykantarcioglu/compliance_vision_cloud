import { CheckCircle, Loader2, AlertCircle, Video, Eye, Scale, FileText } from "lucide-react";
import type { PipelineStage } from "../types";

interface Props {
  stage: PipelineStage;
  error?: string | null;
}

const STAGES = [
  { key: "uploading", label: "Uploading Video", icon: Video },
  { key: "detecting", label: "Detecting Changes", icon: Video },
  { key: "analyzing", label: "VLM Analysis", icon: Eye },
  { key: "evaluating", label: "Policy Evaluation", icon: Scale },
  { key: "complete", label: "Report Ready", icon: FileText },
] as const;

export default function PipelineStatus({ stage, error }: Props) {
  if (stage === "idle") return null;

  if (stage === "error") {
    return (
      <div className="flex items-start gap-3 p-4 rounded border"
        style={{ borderColor: "var(--color-critical)", background: "rgba(239,68,68,0.08)" }}>
        <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: "var(--color-critical)" }} />
        <div>
          <p className="text-sm font-medium" style={{ color: "var(--color-critical)" }}>
            Analysis Failed
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--color-text-dim)" }}>
            {error || "An unknown error occurred."}
          </p>
        </div>
      </div>
    );
  }

  const activeIndex = STAGES.findIndex((s) => s.key === stage);

  return (
    <div className="p-4 rounded border space-y-3"
      style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}>
      <p className="text-xs font-medium" style={{ color: "var(--color-text-dim)" }}>
        Pipeline Progress
      </p>
      <div className="space-y-2">
        {STAGES.map((s, i) => {
          const Icon = s.icon;
          const isDone = i < activeIndex || stage === "complete";
          const isActive = i === activeIndex && stage !== "complete";
          const isPending = i > activeIndex && stage !== "complete";

          return (
            <div key={s.key} className="flex items-center gap-3">
              {isDone ? (
                <CheckCircle className="w-4 h-4 shrink-0" style={{ color: "var(--color-compliant)" }} />
              ) : isActive ? (
                <Loader2 className="w-4 h-4 shrink-0 animate-spin" style={{ color: "var(--color-accent)" }} />
              ) : (
                <Icon className="w-4 h-4 shrink-0" style={{ color: "var(--color-border)" }} />
              )}
              <span
                className="text-xs"
                style={{
                  color: isDone
                    ? "var(--color-compliant)"
                    : isActive
                    ? "var(--color-text)"
                    : "var(--color-border)",
                  fontWeight: isActive ? 600 : 400,
                }}
              >
                {s.label}
                {isActive && (
                  <span className="animate-pulse-glow ml-1.5" style={{ color: "var(--color-text-dim)" }}>
                    ...
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
