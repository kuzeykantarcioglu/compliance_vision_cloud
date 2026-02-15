import { useState, useRef, useCallback, useEffect } from "react";
import { Scan, ScrollText, Image, Shield, Sparkles, Camera } from "lucide-react";
import type { ReferenceImage } from "./types";
import StatusBar from "./components/Header";
import ThemeToggle, { applyTheme } from "./components/ThemeToggle";
import VideoInput, { type InputMode } from "./components/VideoInput";
import PolicyConfig from "./components/PolicyConfig";
import ReferencesPanel from "./components/ReferencesPanel";
import PollyChat from "./components/PollyChat";
import PipelineStatus from "./components/PipelineStatus";
import ReportView from "./components/ReportView";
import LiveReportView from "./components/LiveReportView";
import { analyzeVideo, healthCheck } from "./api";
import type { Policy, Report, PipelineStage } from "./types";

// Apply saved theme before first paint to avoid flash
applyTheme((localStorage.getItem("compliance_vision_theme") || "light") as "light" | "night" | "dark" | "high-contrast");

type LeftTab = "policy" | "references" | "polly";

const CHUNK_DURATION_MS = 6_000;  // 6s chunks — good balance of context vs speed
const FIRST_CHUNK_DURATION_MS = 2_000; // 2s first chunk for fast initial result
const REFS_STORAGE_KEY = "compliance_vision_references";

/** Load saved reference images from localStorage */
function loadSavedReferences(): ReferenceImage[] {
  try {
    const raw = localStorage.getItem(REFS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** Save reference images to localStorage */
function saveReferences(images: ReferenceImage[]) {
  try {
    localStorage.setItem(REFS_STORAGE_KEY, JSON.stringify(images));
  } catch (e) {
    console.warn("Failed to save references to localStorage (may exceed quota):", e);
  }
}

export default function App() {
  const [inputMode, setInputMode] = useState<InputMode>("file");
  const [leftTab, setLeftTab] = useState<LeftTab>("policy");

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [stage, setStage] = useState<PipelineStage>("idle");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [isMonitoring, setIsMonitoring] = useState(false);
  const [liveReports, setLiveReports] = useState<Report[]>([]);
  const [sessionStart, setSessionStart] = useState<number | null>(null);
  const [liveStage, setLiveStage] = useState<PipelineStage>("idle");
  const [liveError, setLiveError] = useState<string | null>(null);
  const [chunksProcessed, setChunksProcessed] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const monitoringRef = useRef(false);
  const sessionIdRef = useRef(0); // incremented each session to discard stale in-flight results
  const liveReportsRef = useRef<Report[]>([]);

  const [policy, setPolicy] = useState<Policy>(() => {
    const savedRefs = loadSavedReferences();
    return { rules: [], custom_prompt: "", include_audio: false, reference_images: savedRefs, enabled_reference_ids: [] };
  });
  const policyRef = useRef<Policy>(policy);

  // Persist reference images to localStorage whenever they change
  useEffect(() => {
    saveReferences(policy.reference_images);
  }, [policy.reference_images]);

  // Keep liveReportsRef in sync for use in analyzeChunk (avoids stale closure)
  useEffect(() => {
    liveReportsRef.current = liveReports;
  }, [liveReports]);

  const handlePolicyChange = useCallback((p: Policy) => {
    setPolicy(p);
    policyRef.current = p;
  }, []);

  // Stable callback for reference image changes — avoids stale closure over `policy`
  const handleReferenceImagesChange = useCallback((imgs: ReferenceImage[]) => {
    setPolicy(prev => {
      // Ensure all references have ids
      const withIds = imgs.map(img => img.id ? img : { ...img, id: crypto.randomUUID() });
      const updated = { ...prev, reference_images: withIds };
      policyRef.current = updated;
      return updated;
    });
  }, []);

  const canAnalyze =
    inputMode === "file" &&
    videoFile !== null &&
    (policy.rules.length > 0 || policy.custom_prompt.trim().length > 0) &&
    policy.rules.every((r) => r.description.trim().length > 0) &&
    stage === "idle";

  const handleAnalyze = async () => {
    if (!videoFile) return;
    setStage("uploading");
    setReport(null);
    setError(null);
    const result = await analyzeVideo(videoFile, policy, (s) => setStage(s as PipelineStage));
    if (result.status === "complete" && result.report) {
      setReport(result.report);
      setStage("complete");
    } else {
      setError(result.error || "Analysis failed.");
      setStage("error");
    }
  };

  const handleReset = () => { setStage("idle"); setReport(null); setError(null); };

  // --- Pipelined monitoring: record chunk N+1 while analyzing chunk N ---

  /** Record a single webcam chunk. Returns a File or null if session ended. */
  const recordChunk = useCallback(async (mySession: number, durationMs: number = CHUNK_DURATION_MS): Promise<File | null> => {
    const videoEl = document.querySelector("video[autoplay]") as HTMLVideoElement | null;
    if (!videoEl || !videoEl.srcObject) return null;
    const stream = videoEl.srcObject as MediaStream;
    streamRef.current = stream;
    const parts: Blob[] = [];
    const recorder = new MediaRecorder(stream, {
      mimeType: MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm",
    });
    recorderRef.current = recorder;
    recorder.ondataavailable = (e) => { if (e.data.size > 0) parts.push(e.data); };
    const blob = await new Promise<Blob>((resolve) => {
      recorder.onstop = () => resolve(new Blob(parts, { type: "video/webm" }));
      recorder.start();
      setTimeout(() => { if (recorder.state === "recording") recorder.stop(); }, durationMs);
    });
    if (!monitoringRef.current || sessionIdRef.current !== mySession) return null;
    return new File([blob], `chunk-${Date.now()}.webm`, { type: "video/webm" });
  }, []);

  /**
   * Build prior_context string from accumulated reports.
   * Tells the LLM which "at least once" rules are already satisfied per person.
   * Uses person_summaries (per-person compliance) for accurate attribution.
   */
  const buildPriorContext = useCallback((reports: Report[]): string => {
    if (reports.length === 0) return "";
    const lines: string[] = [];

    // Track which people were compliant in ANY chunk (person-level, from person_summaries)
    const personCompliant = new Map<string, boolean>();  // person_id → ever compliant
    const personViolations = new Map<string, Set<string>>();  // person_id → unsatisfied rule descriptions

    for (const r of reports) {
      for (const ps of r.person_summaries ?? []) {
        if (ps.compliant) {
          personCompliant.set(ps.person_id, true);
        }
        // Track violations that are NOT yet satisfied
        if (!ps.compliant) {
          if (!personViolations.has(ps.person_id)) {
            personViolations.set(ps.person_id, new Set());
          }
          for (const v of ps.violations) {
            personViolations.get(ps.person_id)?.add(v);
          }
        }
      }
    }

    // Collect rules that were satisfied (compliant verdict in ANY chunk) — per the whole session
    const satisfiedRules = new Set<string>();
    for (const r of reports) {
      for (const v of r.all_verdicts ?? []) {
        if (v.compliant) {
          satisfiedRules.add(v.rule_description);
        }
      }
    }

    // Build context: for each satisfied rule, list which people satisfied it
    if (satisfiedRules.size > 0) {
      lines.push("ALREADY SATISFIED RULES (do NOT flag these as violations again):");
      for (const rule of satisfiedRules) {
        const whoSatisfied: string[] = [];
        for (const [pid, isCompliant] of personCompliant) {
          if (isCompliant) whoSatisfied.push(pid);
        }
        lines.push(`  - "${rule}" → SATISFIED by ${whoSatisfied.length > 0 ? whoSatisfied.join(", ") : "at least one person"}`);
      }
      lines.push("Mark these rules as COMPLIANT. Do NOT generate incidents for them.");
    }

    return lines.join("\n");
  }, []);

  /** Upload + analyze a single chunk. Fire-and-forget friendly. */
  const analyzeChunk = useCallback(async (file: File, mySession: number) => {
    setLiveStage("uploading");

    // Inject prior_context from accumulated reports into the policy for this chunk
    const currentPolicy = { ...policyRef.current };
    const priorCtx = buildPriorContext(liveReportsRef.current);
    if (priorCtx) {
      currentPolicy.prior_context = priorCtx;
    }

    const result = await analyzeVideo(file, currentPolicy, (s) => {
      if (sessionIdRef.current === mySession) setLiveStage(s as PipelineStage);
    });
    if (!monitoringRef.current || sessionIdRef.current !== mySession) return;
    if (result.status === "complete" && result.report) {
      setLiveReports((prev) => [...prev, result.report!]);
      setChunksProcessed((prev) => prev + 1);
      setLiveStage("complete");
      setLiveError(null);
    } else {
      setLiveError(result.error || "Chunk analysis failed.");
      setLiveStage("error");
    }
  }, [buildPriorContext]);

  /**
   * Pipelined loop: overlaps recording and analysis.
   *
   * First chunk is shorter (3s) for a fast initial result.
   * Health check runs in parallel with first chunk recording.
   *
   * Timeline:
   *   record(3s) ──→ fire analyze ──→ record(8s) ──→ wait prev ──→ fire analyze ──→ ...
   *   healthCheck() ──┘ (parallel)     └── runs in background ──┘
   */
  const runMonitoringLoop = useCallback(async () => {
    const mySession = sessionIdRef.current;
    let isFirst = true;
    let pendingAnalysis: Promise<void> | null = null;

    // Warm-start health check runs in parallel with first chunk recording (not awaited upfront)
    const warmup = healthCheck().catch(() => {});

    while (monitoringRef.current && sessionIdRef.current === mySession) {
      // 1. Record chunk — first chunk is short for fast initial result
      const duration = isFirst ? FIRST_CHUNK_DURATION_MS : CHUNK_DURATION_MS;
      const file = await recordChunk(mySession, duration);
      if (!file || !monitoringRef.current || sessionIdRef.current !== mySession) break;

      // Wait for warmup only on first chunk (should be done by now — ran in parallel)
      if (isFirst) {
        await warmup;
        isFirst = false;
      }

      // 2. If previous analysis is still running, wait for it (max 1 in-flight)
      if (pendingAnalysis) {
        await pendingAnalysis;
        pendingAnalysis = null;
      }
      if (!monitoringRef.current || sessionIdRef.current !== mySession) break;

      // 3. Fire analysis for this chunk — DON'T await, immediately loop to record next chunk
      pendingAnalysis = analyzeChunk(file, mySession);
    }

    // Drain: wait for last in-flight analysis to finish
    if (pendingAnalysis) await pendingAnalysis;
  }, [recordChunk, analyzeChunk]);

  const canStartMonitoring =
    (policy.rules.length > 0 || policy.custom_prompt.trim().length > 0) &&
    policy.rules.every((r) => r.description.trim().length > 0);

  const handleStartMonitoring = () => {
    if (!canStartMonitoring) return;
    sessionIdRef.current += 1; // new session — stale in-flight results from old session are discarded
    setIsMonitoring(true);
    monitoringRef.current = true;
    setLiveReports([]);
    liveReportsRef.current = [];
    setSessionStart(Date.now());
    setChunksProcessed(0);
    setLiveStage("idle");
    setLiveError(null);
    runMonitoringLoop();
  };

  const handleStopMonitoring = () => {
    monitoringRef.current = false;
    sessionIdRef.current += 1; // invalidate any in-flight requests from this session
    setIsMonitoring(false);
    setLiveStage("idle");
    if (recorderRef.current && recorderRef.current.state === "recording") recorderRef.current.stop();
  };

  const isFileRunning = inputMode === "file" && !["idle", "complete", "error"].includes(stage);

  return (
    <div className="min-h-screen flex" style={{ background: "var(--color-bg)" }}>
      {/* Floating side panel */}
      <div
        className="w-[400px] shrink-0 flex flex-col m-3 rounded-lg border overflow-hidden"
        style={{
          borderColor: "var(--color-border)",
          background: "var(--color-surface)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03)",
          height: "calc(100vh - 24px)",
        }}
      >
        {/* Panel header: logo + tabs + status */}
        <div className="shrink-0 border-b" style={{ borderColor: "var(--color-border)" }}>
          {/* Logo row */}
          <div className="flex items-center justify-between px-4 pt-4 pb-3">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded" style={{ background: "var(--color-accent)" }}>
                <Shield className="w-4 h-4" style={{ color: "var(--color-bg)" }} />
              </div>
              <span className="text-sm font-bold tracking-tight" style={{ color: "var(--color-text)" }}>
                Compliance Vision
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusBar />
              <ThemeToggle />
            </div>
          </div>

          {/* Tab bar */}
          <div className="flex px-4 gap-1">
            {([
              { key: "policy" as LeftTab, label: "Policy", icon: ScrollText },
              { key: "references" as LeftTab, label: "References", icon: Image },
              { key: "polly" as LeftTab, label: "Polly", icon: Sparkles },
            ]).map((tab) => {
              const Icon = tab.icon;
              const isActive = leftTab === tab.key;
              const refCount = tab.key === "references" ? policy.reference_images.length : 0;
              return (
                <button
                  key={tab.key}
                  onClick={() => setLeftTab(tab.key)}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px"
                  style={{
                    borderBottomColor: isActive ? "var(--color-accent)" : "transparent",
                    color: isActive ? "var(--color-text)" : "var(--color-text-dim)",
                  }}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {tab.label}
                  {refCount > 0 && tab.key === "references" && (
                    <span
                      className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                      style={{ background: "var(--color-accent)", color: "white" }}
                    >
                      {refCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Tab content — scrollable, no horizontal overflow */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-4 space-y-4">
          {leftTab === "polly" ? (
            <PollyChat
              policy={policy}
              onPolicyChange={(p) => { handlePolicyChange(p); setLeftTab("policy"); }}
              disabled={isFileRunning || isMonitoring}
            />
          ) : leftTab === "policy" ? (
            <>
              <VideoInput
                mode={inputMode}
                onModeChange={setInputMode}
                file={videoFile}
                onFileChange={setVideoFile}
                isMonitoring={isMonitoring}
                onStartMonitoring={handleStartMonitoring}
                onStopMonitoring={handleStopMonitoring}
                disabled={isFileRunning || (inputMode === "webcam" && !canStartMonitoring)}
              />

              <PolicyConfig
                policy={policy}
                onChange={handlePolicyChange}
                disabled={isFileRunning || isMonitoring}
              />

              {inputMode === "file" && (
                <>
                  <button
                    onClick={handleAnalyze}
                    disabled={!canAnalyze}
                    className="w-full flex items-center justify-center gap-2 py-3 rounded text-sm font-semibold text-white transition-all"
                    style={{
                      background: canAnalyze ? "var(--color-accent)" : "var(--color-surface-2)",
                      opacity: canAnalyze ? 1 : 0.4,
                      cursor: canAnalyze ? "pointer" : "not-allowed",
                    }}
                  >
                    <Scan className="w-4 h-4" />
                    Analyze Video
                  </button>

                  {stage !== "idle" && <PipelineStatus stage={stage} error={error} />}

                  {(stage === "complete" || stage === "error") && (
                    <button
                      onClick={handleReset}
                      className="w-full text-xs py-2 rounded border border-dashed hover:bg-black/5 transition-colors"
                      style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}
                    >
                      Run New Analysis
                    </button>
                  )}
                </>
              )}

              {inputMode === "webcam" && isMonitoring && liveStage !== "idle" && (
                <PipelineStatus stage={liveStage} error={liveError} />
              )}

              {inputMode === "webcam" && isMonitoring && (
                <div className="text-xs space-y-1 p-3 rounded border"
                  style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)", color: "var(--color-text-dim)" }}>
                  <p>Chunks: <span style={{ color: "var(--color-text)" }}>{chunksProcessed}</span></p>
                  <p>Incidents: <span style={{ color: liveReports.some(r => !r.overall_compliant) ? "var(--color-critical)" : "var(--color-compliant)" }}>
                    {liveReports.reduce((sum, r) => sum + r.incidents.length, 0)}
                  </span></p>
                </div>
              )}

              {inputMode === "webcam" && !isMonitoring && liveReports.length > 0 && (
                <button
                  onClick={() => { sessionIdRef.current += 1; setLiveReports([]); setSessionStart(null); setChunksProcessed(0); }}
                  className="w-full text-xs py-2 rounded border border-dashed hover:bg-black/5 transition-colors"
                  style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}
                >
                  Clear Session
                </button>
              )}
            </>
          ) : (
            <ReferencesPanel
              images={policy.reference_images}
              onChange={handleReferenceImagesChange}
              disabled={isFileRunning || isMonitoring}
            />
          )}
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-y-auto p-6">
        {inputMode === "file" ? (
          report ? (
            <ReportView report={report} />
          ) : (
            <div className="flex items-center justify-center h-full">
              <div className="text-center space-y-5 max-w-sm mx-auto">
                {isFileRunning ? (
                  <>
                    <div className="relative mx-auto w-16 h-16">
                      <Scan className="w-16 h-16 animate-pulse-glow" style={{ color: "var(--color-accent)" }} />
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
                        Analyzing video...
                      </p>
                      <p className="text-xs" style={{ color: "var(--color-text-dim)" }}>
                        Running change detection, VLM analysis, and policy evaluation.
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <div
                      className="mx-auto w-20 h-20 rounded-2xl flex items-center justify-center"
                      style={{ background: "var(--color-surface-2)", border: "2px dashed var(--color-border)" }}
                    >
                      <Scan className="w-9 h-9" style={{ color: "var(--color-border)" }} />
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-base font-semibold" style={{ color: "var(--color-text)" }}>
                        Waiting for Analysis
                      </p>
                      <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
                        Upload a video and configure your compliance policy on the left, then hit <span className="font-medium" style={{ color: "var(--color-text)" }}>Analyze Video</span> to generate a report.
                      </p>
                    </div>
                    <div className="flex items-center justify-center gap-4 pt-2">
                      {[
                        { icon: "1", text: "Upload video" },
                        { icon: "2", text: "Set policy" },
                        { icon: "3", text: "Run analysis" },
                      ].map((step) => (
                        <div key={step.icon} className="flex items-center gap-1.5">
                          <span
                            className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold"
                            style={{ background: "var(--color-surface-2)", color: "var(--color-text-dim)", border: "1px solid var(--color-border)" }}
                          >
                            {step.icon}
                          </span>
                          <span className="text-[11px]" style={{ color: "var(--color-text-dim)" }}>{step.text}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          )
        ) : liveReports.length > 0 || isMonitoring ? (
          <LiveReportView
            reports={liveReports}
            isMonitoring={isMonitoring}
            sessionStart={sessionStart}
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center space-y-5 max-w-sm mx-auto">
              <div
                className="mx-auto w-20 h-20 rounded-2xl flex items-center justify-center"
                style={{ background: "var(--color-surface-2)", border: "2px dashed var(--color-border)" }}
              >
                <Camera className="w-9 h-9" style={{ color: "var(--color-border)" }} />
              </div>
              <div className="space-y-1.5">
                <p className="text-base font-semibold" style={{ color: "var(--color-text)" }}>
                  Ready to Monitor
                </p>
                <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
                  Configure your compliance policy and start webcam monitoring. Live results will stream here in real time.
                </p>
              </div>
              <div className="flex items-center justify-center gap-4 pt-2">
                {[
                  { icon: "1", text: "Set policy" },
                  { icon: "2", text: "Start webcam" },
                  { icon: "3", text: "View live" },
                ].map((step) => (
                  <div key={step.icon} className="flex items-center gap-1.5">
                    <span
                      className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold"
                      style={{ background: "var(--color-surface-2)", color: "var(--color-text-dim)", border: "1px solid var(--color-border)" }}
                    >
                      {step.icon}
                    </span>
                    <span className="text-[11px]" style={{ color: "var(--color-text-dim)" }}>{step.text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
