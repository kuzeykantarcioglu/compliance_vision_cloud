import {
  ShieldCheck,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  Clock,
  Download,
  Eye,
  Lightbulb,
  AlertTriangle,
  Mic,
  X,
  Camera,
} from "lucide-react";
import { useState } from "react";
import type { Report, Verdict, FrameObservation, TranscriptResult } from "../types";

interface Props {
  report: Report;
}

const SEVERITY_COLORS: Record<string, string> = {
  low: "var(--color-low)",
  medium: "var(--color-medium)",
  high: "var(--color-high)",
  critical: "var(--color-critical)",
};

const SEVERITY_BG: Record<string, string> = {
  low: "rgba(34,197,94,0.1)",
  medium: "rgba(234,179,8,0.1)",
  high: "rgba(249,115,22,0.1)",
  critical: "rgba(239,68,68,0.1)",
};

function formatTimestamp(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

/** Find the nearest keyframe observation for a given incident timestamp */
function findEvidenceFrame(
  timestamp: number | null,
  observations: FrameObservation[]
): FrameObservation | null {
  if (timestamp === null || observations.length === 0) return null;
  let best = observations[0];
  let bestDist = Math.abs(best.timestamp - timestamp);
  for (const obs of observations) {
    const dist = Math.abs(obs.timestamp - timestamp);
    if (dist < bestDist) {
      best = obs;
      bestDist = dist;
    }
  }
  return best.image_base64 ? best : null;
}

// ---- Evidence Modal ----

function EvidenceModal({
  evidence,
  verdict,
  onClose,
}: {
  evidence: FrameObservation;
  verdict: Verdict;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "rgba(0,0,0,0.8)" }}
      onClick={onClose}
    >
      <div
        className="relative max-w-3xl w-full rounded border overflow-hidden animate-slide-up"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 p-1.5 rounded hover:bg-black/5 transition-colors"
          style={{ background: "rgba(0,0,0,0.5)" }}
        >
          <X className="w-4 h-4 text-white" />
        </button>

        {/* Image */}
        <img
          src={`data:image/jpeg;base64,${evidence.image_base64}`}
          alt="Evidence frame"
          className="w-full max-h-[50vh] object-contain bg-black"
        />

        {/* Verdict overlay */}
        <div className="p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span
              className="text-xs font-bold px-2 py-0.5 rounded uppercase"
              style={{
                background: SEVERITY_COLORS[verdict.severity] + "20",
                color: SEVERITY_COLORS[verdict.severity],
              }}
            >
              {verdict.severity}
            </span>
            <span className="text-xs px-2 py-0.5 rounded uppercase"
              style={{ background: "var(--color-surface-2)", color: "var(--color-text-dim)" }}>
              {verdict.rule_type}
            </span>
            <span className="text-xs font-mono" style={{ color: "var(--color-text-dim)" }}>
              t={formatTimestamp(verdict.timestamp)}
            </span>
          </div>
          <p className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
            {verdict.rule_description}
          </p>
          <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
            {verdict.reason}
          </p>
          <div className="pt-2 border-t" style={{ borderColor: "var(--color-border)" }}>
            <p className="text-[10px] font-medium mb-1" style={{ color: "var(--color-text-dim)" }}>
              VLM Observation at {formatTimestamp(evidence.timestamp)}:
            </p>
            <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
              {evidence.description}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Summary Card ----

function SummaryCard({ report }: { report: Report }) {
  const incidentCount = report.incidents.length;
  const totalRules = report.all_verdicts.length;
  const passedRules = report.all_verdicts.filter((v) => v.compliant).length;

  return (
    <div
      className="p-5 rounded border"
      style={{
        borderColor: report.overall_compliant ? "var(--color-compliant)" : "var(--color-non-compliant)",
        background: report.overall_compliant
          ? "rgba(34,197,94,0.06)"
          : "rgba(239,68,68,0.06)",
      }}
    >
      <div className="flex items-start gap-4">
        {report.overall_compliant ? (
          <ShieldCheck className="w-10 h-10 shrink-0" style={{ color: "var(--color-compliant)" }} />
        ) : (
          <ShieldAlert className="w-10 h-10 shrink-0" style={{ color: "var(--color-non-compliant)" }} />
        )}
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <span
              className="text-sm font-bold px-2.5 py-0.5 rounded-full"
              style={{
                background: report.overall_compliant
                  ? "rgba(34,197,94,0.2)"
                  : "rgba(239,68,68,0.2)",
                color: report.overall_compliant
                  ? "var(--color-compliant)"
                  : "var(--color-non-compliant)",
              }}
            >
              {report.overall_compliant ? "COMPLIANT" : "NON-COMPLIANT"}
            </span>
          </div>
          <p className="text-sm leading-relaxed" style={{ color: "var(--color-text)" }}>
            {report.summary}
          </p>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3 text-xs" style={{ color: "var(--color-text-dim)" }}>
            <span>{passedRules}/{totalRules} rules passed</span>
            <span>{incidentCount} incident{incidentCount !== 1 ? "s" : ""}</span>
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {report.video_duration.toFixed(1)}s analyzed
            </span>
            <span>{report.total_frames_analyzed} frames</span>
            {report.transcript && report.transcript.full_text && (
              <span className="flex items-center gap-1">
                <Mic className="w-3 h-3" />
                Audio analyzed
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Verdict Card (with evidence thumbnail) ----

function VerdictCard({
  verdict,
  evidence,
  onViewEvidence,
}: {
  verdict: Verdict;
  evidence: FrameObservation | null;
  onViewEvidence?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="rounded border overflow-hidden transition-all"
      style={{
        borderColor: verdict.compliant ? "var(--color-border)" : SEVERITY_COLORS[verdict.severity] + "40",
        background: verdict.compliant ? "var(--color-surface-2)" : SEVERITY_BG[verdict.severity],
      }}
    >
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Evidence thumbnail */}
        {evidence && evidence.image_base64 && !verdict.compliant ? (
          <img
            src={`data:image/jpeg;base64,${evidence.image_base64}`}
            alt="Evidence"
            className="w-10 h-10 rounded object-cover shrink-0 border cursor-zoom-in"
            style={{ borderColor: SEVERITY_COLORS[verdict.severity] + "60" }}
            onClick={(e) => {
              e.stopPropagation();
              onViewEvidence?.();
            }}
          />
        ) : verdict.compliant ? (
          <ShieldCheck className="w-4 h-4 shrink-0" style={{ color: "var(--color-compliant)" }} />
        ) : (
          <AlertTriangle className="w-4 h-4 shrink-0" style={{ color: SEVERITY_COLORS[verdict.severity] }} />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase"
              style={{
                background: SEVERITY_COLORS[verdict.severity] + "20",
                color: SEVERITY_COLORS[verdict.severity],
              }}
            >
              {verdict.severity}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded uppercase"
              style={{ background: "var(--color-surface)", color: "var(--color-text-dim)" }}>
              {verdict.rule_type}
            </span>
            {evidence && !verdict.compliant && (
              <span className="text-[10px] flex items-center gap-0.5"
                style={{ color: "var(--color-accent)" }}>
                <Camera className="w-2.5 h-2.5" /> evidence
              </span>
            )}
          </div>
          <p className="text-sm mt-1 truncate" style={{ color: "var(--color-text)" }}>
            {verdict.rule_description}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {verdict.timestamp !== null && (
            <span className="text-xs font-mono" style={{ color: "var(--color-text-dim)" }}>
              {formatTimestamp(verdict.timestamp)}
            </span>
          )}
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </div>
      {expanded && (
        <div className="px-4 pb-3 pt-0 space-y-2">
          <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
            {verdict.reason}
          </p>
          {evidence && evidence.image_base64 && (
            <img
              src={`data:image/jpeg;base64,${evidence.image_base64}`}
              alt="Evidence"
              className="w-full max-h-40 object-contain rounded border cursor-zoom-in"
              style={{ borderColor: "var(--color-border)" }}
              onClick={() => onViewEvidence?.()}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ---- Observations Timeline (with thumbnails) ----

function ObservationsTimeline({ observations }: { observations: FrameObservation[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? observations : observations.slice(0, 3);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-3">
        <Eye className="w-4 h-4" style={{ color: "var(--color-accent)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
          Frame Observations ({observations.length})
        </span>
      </div>
      {shown.map((obs, i) => (
        <div
          key={i}
          className="flex gap-3 p-3 rounded border animate-slide-up"
          style={{
            borderColor: "var(--color-border)",
            background: "var(--color-surface-2)",
            animationDelay: `${i * 50}ms`,
          }}
        >
          {obs.image_base64 && (
            <img
              src={`data:image/jpeg;base64,${obs.image_base64}`}
              alt={`Frame at ${obs.timestamp}s`}
              className="w-16 h-12 rounded object-cover shrink-0 border"
              style={{ borderColor: "var(--color-border)" }}
            />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-mono font-bold" style={{ color: "var(--color-accent)" }}>
                {formatTimestamp(obs.timestamp)}
              </span>
              <span className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
                {obs.trigger}
              </span>
            </div>
            <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
              {obs.description}
            </p>
          </div>
        </div>
      ))}
      {observations.length > 3 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs w-full py-2 rounded border border-dashed hover:bg-black/5 transition-colors"
          style={{ borderColor: "var(--color-border)", color: "var(--color-accent)" }}
        >
          {expanded ? "Show less" : `Show all ${observations.length} observations`}
        </button>
      )}
    </div>
  );
}

// ---- Transcript View ----

function TranscriptView({ transcript }: { transcript: TranscriptResult }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? transcript.segments : transcript.segments.slice(0, 4);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-3">
        <Mic className="w-4 h-4" style={{ color: "var(--color-accent)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
          Audio Transcript
        </span>
        <span className="text-[10px] px-1.5 py-0.5 rounded"
          style={{ background: "var(--color-surface)", color: "var(--color-text-dim)" }}>
          {transcript.language.toUpperCase()} | {transcript.duration.toFixed(1)}s
        </span>
      </div>

      {transcript.full_text && (
        <div className="p-3 rounded border"
          style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}>
          <p className="text-xs italic leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
            "{transcript.full_text}"
          </p>
        </div>
      )}

      {transcript.segments.length > 0 && (
        <>
          {shown.map((seg, i) => (
            <div
              key={i}
              className="flex gap-3 p-3 rounded border animate-slide-up"
              style={{
                borderColor: "var(--color-border)",
                background: "var(--color-surface-2)",
                animationDelay: `${i * 50}ms`,
              }}
            >
              <div className="shrink-0 text-center" style={{ minWidth: 70 }}>
                <span className="text-xs font-mono font-bold" style={{ color: "var(--color-accent)" }}>
                  {formatTimestamp(seg.start)}
                </span>
                <span className="text-[10px] mx-0.5" style={{ color: "var(--color-text-dim)" }}>-</span>
                <span className="text-xs font-mono" style={{ color: "var(--color-text-dim)" }}>
                  {formatTimestamp(seg.end)}
                </span>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
                {seg.text}
              </p>
            </div>
          ))}
          {transcript.segments.length > 4 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs w-full py-2 rounded border border-dashed hover:bg-black/5 transition-colors"
              style={{ borderColor: "var(--color-border)", color: "var(--color-accent)" }}
            >
              {expanded ? "Show less" : `Show all ${transcript.segments.length} segments`}
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ---- Main Report View ----

export default function ReportView({ report }: Props) {
  const [evidenceModal, setEvidenceModal] = useState<{
    evidence: FrameObservation;
    verdict: Verdict;
  } | null>(null);

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `compliance-report-${report.video_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4 animate-slide-up">
      {/* Evidence modal */}
      {evidenceModal && (
        <EvidenceModal
          evidence={evidenceModal.evidence}
          verdict={evidenceModal.verdict}
          onClose={() => setEvidenceModal(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold" style={{ color: "var(--color-text)" }}>
          Compliance Report
        </h2>
        <button
          onClick={handleExport}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded transition-colors hover:bg-black/5"
          style={{ color: "var(--color-accent)", border: "1px solid var(--color-border)" }}
        >
          <Download className="w-3.5 h-3.5" /> Export JSON
        </button>
      </div>

      {/* Summary */}
      <SummaryCard report={report} />

      {/* Incidents with evidence */}
      {report.incidents.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium flex items-center gap-2" style={{ color: "var(--color-non-compliant)" }}>
            <AlertTriangle className="w-4 h-4" />
            Incidents ({report.incidents.length})
          </h3>
          {report.incidents.map((v, i) => {
            const evidence = findEvidenceFrame(v.timestamp, report.frame_observations);
            return (
              <VerdictCard
                key={`inc-${i}`}
                verdict={v}
                evidence={evidence}
                onViewEvidence={
                  evidence
                    ? () => setEvidenceModal({ evidence, verdict: v })
                    : undefined
                }
              />
            );
          })}
        </div>
      )}

      {/* All verdicts */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
          All Rule Evaluations ({report.all_verdicts.length})
        </h3>
        {report.all_verdicts.map((v, i) => {
          const evidence = findEvidenceFrame(v.timestamp, report.frame_observations);
          return (
            <VerdictCard
              key={`all-${i}`}
              verdict={v}
              evidence={evidence}
              onViewEvidence={
                evidence
                  ? () => setEvidenceModal({ evidence, verdict: v })
                  : undefined
              }
            />
          );
        })}
      </div>

      {/* Recommendations */}
      {report.recommendations.length > 0 && (
        <div className="p-4 rounded border"
          style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}>
          <div className="flex items-center gap-2 mb-3">
            <Lightbulb className="w-4 h-4" style={{ color: "var(--color-medium)" }} />
            <span className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
              Recommendations
            </span>
          </div>
          <ul className="space-y-1.5">
            {report.recommendations.map((rec, i) => (
              <li key={i} className="text-xs flex items-start gap-2"
                style={{ color: "var(--color-text-dim)" }}>
                <span style={{ color: "var(--color-medium)" }}>-</span>
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Audio Transcript */}
      {report.transcript && report.transcript.full_text && (
        <TranscriptView transcript={report.transcript} />
      )}

      {/* Observations Timeline */}
      {report.frame_observations.length > 0 && (
        <ObservationsTimeline observations={report.frame_observations} />
      )}

      {/* Metadata footer */}
      <div className="flex gap-4 text-[10px] pt-2" style={{ color: "var(--color-text-dim)" }}>
        <span>Video ID: {report.video_id}</span>
        <span>Analyzed: {new Date(report.analyzed_at).toLocaleString()}</span>
      </div>
    </div>
  );
}
