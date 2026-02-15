import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  Clock,
  Download,
  Radio,
  Eye,
  Mic,
  Camera,
} from "lucide-react";
import { useState, useEffect, useRef } from "react";
import type { Report, Verdict, TranscriptSegment, FrameObservation } from "../types";

interface Props {
  reports: Report[];
  isMonitoring: boolean;
  sessionStart: number | null; // timestamp ms
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

function SessionTimer({ start }: { start: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setElapsed(Date.now() - start), 1000);
    return () => clearInterval(interval);
  }, [start]);

  const mins = Math.floor(elapsed / 60000);
  const secs = Math.floor((elapsed % 60000) / 1000);
  return (
    <span className="font-mono">
      {mins.toString().padStart(2, "0")}:{secs.toString().padStart(2, "0")}
    </span>
  );
}

function formatTs(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function findNearestFrame(timestamp: number | null, observations: FrameObservation[]): FrameObservation | null {
  if (timestamp === null || observations.length === 0) return null;
  let best = observations[0];
  let bestDist = Math.abs(best.timestamp - timestamp);
  for (const obs of observations) {
    const dist = Math.abs(obs.timestamp - timestamp);
    if (dist < bestDist) { best = obs; bestDist = dist; }
  }
  return best.image_base64 ? best : null;
}

export default function LiveReportView({ reports, isMonitoring, sessionStart }: Props) {
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Aggregate all incidents across all chunk reports
  const allIncidents = reports.flatMap((r, ri) =>
    r.incidents.map((v) => ({ ...v, chunkIndex: ri }))
  );
  const allObservations = reports.flatMap((r) => r.frame_observations);
  const totalFrames = reports.reduce((sum, r) => sum + r.total_frames_analyzed, 0);
  const totalDuration = reports.reduce((sum, r) => sum + r.video_duration, 0);
  const hasAnyNonCompliant = reports.some((r) => !r.overall_compliant);

  // Aggregate all transcript segments
  const allTranscriptSegments: (TranscriptSegment & { chunkIndex: number })[] = reports.flatMap(
    (r, ri) =>
      r.transcript?.segments?.map((seg) => ({ ...seg, chunkIndex: ri })) ?? []
  );
  const hasTranscript = allTranscriptSegments.length > 0;

  // Auto-scroll transcript to bottom when new segments arrive
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allTranscriptSegments.length]);

  const handleExport = () => {
    const sessionData = {
      session_start: sessionStart ? new Date(sessionStart).toISOString() : null,
      total_chunks: reports.length,
      total_incidents: allIncidents.length,
      total_frames: totalFrames,
      total_duration: totalDuration,
      reports,
    };
    const blob = new Blob([JSON.stringify(sessionData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `live-session-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (reports.length === 0 && isMonitoring) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <Radio className="w-12 h-12 mx-auto animate-pulse-glow" style={{ color: "var(--color-accent)" }} />
          <p className="text-sm" style={{ color: "var(--color-text)" }}>
            Live monitoring active
          </p>
          <p className="text-xs" style={{ color: "var(--color-text-dim)" }}>
            Recording first chunk... results will appear shortly.
          </p>
          {sessionStart && (
            <p className="text-xs" style={{ color: "var(--color-text-dim)" }}>
              Session time: <SessionTimer start={sessionStart} />
            </p>
          )}
        </div>
      </div>
    );
  }

  if (reports.length === 0) return null;

  return (
    <div className="space-y-4 animate-slide-up">
      {/* Live header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold" style={{ color: "var(--color-text)" }}>
            Live Monitoring
          </h2>
          {isMonitoring && (
            <span className="flex items-center gap-1.5 text-[10px] font-bold px-2 py-0.5 rounded-full"
              style={{ background: "rgba(239,68,68,0.15)", color: "var(--color-critical)" }}>
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse-glow" />
              LIVE
            </span>
          )}
        </div>
        <button
          onClick={handleExport}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded transition-colors hover:bg-black/5"
          style={{ color: "var(--color-accent)", border: "1px solid var(--color-border)" }}
        >
          <Download className="w-3.5 h-3.5" /> Export Session
        </button>
      </div>

      {/* Aggregate stats bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          {
            label: "Status",
            value: hasAnyNonCompliant ? "VIOLATION" : "COMPLIANT",
            color: hasAnyNonCompliant ? "var(--color-non-compliant)" : "var(--color-compliant)",
            Icon: hasAnyNonCompliant ? ShieldAlert : ShieldCheck,
          },
          {
            label: "Incidents",
            value: allIncidents.length.toString(),
            color: allIncidents.length > 0 ? "var(--color-high)" : "var(--color-compliant)",
            Icon: AlertTriangle,
          },
          {
            label: "Chunks",
            value: reports.length.toString(),
            color: "var(--color-accent)",
            Icon: Eye,
          },
          {
            label: "Session",
            value: sessionStart ? undefined : "--:--",
            color: "var(--color-text-dim)",
            Icon: Clock,
            timer: sessionStart,
          },
        ].map((stat, i) => (
          <div
            key={i}
            className="p-3 rounded border text-center"
            style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}
          >
            <stat.Icon className="w-4 h-4 mx-auto mb-1" style={{ color: stat.color }} />
            <div className="text-lg font-bold" style={{ color: stat.color }}>
              {stat.timer ? <SessionTimer start={stat.timer} /> : stat.value}
            </div>
            <div className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
              {stat.label}
            </div>
          </div>
        ))}
      </div>

      {/* Incident feed — newest first, with evidence thumbnails */}
      {allIncidents.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium flex items-center gap-2"
            style={{ color: "var(--color-non-compliant)" }}>
            <AlertTriangle className="w-4 h-4" />
            Incident Feed ({allIncidents.length})
          </h3>
          {[...allIncidents].reverse().map((v, i) => {
            const chunkObs = reports[v.chunkIndex]?.frame_observations ?? [];
            const evidence = findNearestFrame(v.timestamp, chunkObs);
            return (
              <div
                key={i}
                className="flex gap-3 p-3 rounded border animate-slide-up"
                style={{
                  borderColor: SEVERITY_COLORS[v.severity] + "40",
                  background: SEVERITY_BG[v.severity],
                }}
              >
                {/* Evidence thumbnail */}
                {evidence && evidence.image_base64 && (
                  <img
                    src={`data:image/jpeg;base64,${evidence.image_base64}`}
                    alt="Evidence"
                    className="w-16 h-12 rounded object-cover shrink-0 border"
                    style={{ borderColor: SEVERITY_COLORS[v.severity] + "60" }}
                  />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase"
                      style={{
                        background: SEVERITY_COLORS[v.severity] + "20",
                        color: SEVERITY_COLORS[v.severity],
                      }}
                    >
                      {v.severity}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded uppercase"
                      style={{ background: "var(--color-surface)", color: "var(--color-text-dim)" }}>
                      chunk #{v.chunkIndex + 1}
                    </span>
                    {evidence && (
                      <span className="text-[10px] flex items-center gap-0.5"
                        style={{ color: "var(--color-accent)" }}>
                        <Camera className="w-2.5 h-2.5" /> evidence
                      </span>
                    )}
                  </div>
                  <p className="text-xs font-medium" style={{ color: "var(--color-text)" }}>
                    {v.rule_description}
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--color-text-dim)" }}>
                    {v.reason}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Live transcript feed */}
      {hasTranscript && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium flex items-center gap-2"
            style={{ color: "var(--color-text)" }}>
            <Mic className="w-4 h-4" style={{ color: "var(--color-accent)" }} />
            Live Transcript ({allTranscriptSegments.length} segments)
          </h3>
          <div
            className="max-h-48 overflow-y-auto rounded border p-3 space-y-1"
            style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}
          >
            {allTranscriptSegments.map((seg, i) => (
              <div key={i} className="flex gap-2 animate-slide-up" style={{ animationDelay: `${Math.min(i * 30, 300)}ms` }}>
                <span className="text-[10px] font-mono shrink-0 pt-0.5"
                  style={{ color: "var(--color-accent)", minWidth: 32 }}>
                  {formatTs(seg.start)}
                </span>
                <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
                  {seg.text}
                </p>
              </div>
            ))}
            {isMonitoring && (
              <div className="flex items-center gap-2 pt-1">
                <span className="w-1.5 h-1.5 rounded-full animate-pulse-glow" style={{ background: "var(--color-accent)" }} />
                <span className="text-[10px] italic" style={{ color: "var(--color-text-dim)" }}>
                  Listening...
                </span>
              </div>
            )}
            <div ref={transcriptEndRef} />
          </div>
        </div>
      )}

      {/* Latest chunk report summary */}
      {reports.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
            Chunk Reports ({reports.length})
          </h3>
          {[...reports].reverse().map((r, i) => (
            <div
              key={i}
              className="p-3 rounded border"
              style={{
                borderColor: r.overall_compliant ? "var(--color-border)" : "var(--color-non-compliant)" + "30",
                background: r.overall_compliant ? "var(--color-surface-2)" : "rgba(239,68,68,0.04)",
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                {r.overall_compliant ? (
                  <ShieldCheck className="w-3.5 h-3.5" style={{ color: "var(--color-compliant)" }} />
                ) : (
                  <ShieldAlert className="w-3.5 h-3.5" style={{ color: "var(--color-non-compliant)" }} />
                )}
                <span className="text-xs font-medium" style={{ color: "var(--color-text)" }}>
                  Chunk #{reports.length - i}
                </span>
                <span className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
                  {r.incidents.length} incident{r.incidents.length !== 1 ? "s" : ""} | {r.total_frames_analyzed} frames
                </span>
              </div>
              <p className="text-xs" style={{ color: "var(--color-text-dim)" }}>
                {r.summary}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
