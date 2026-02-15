import { useState, useRef, useCallback } from "react";
import { Scan, ScrollText, Image, Shield, Sparkles } from "lucide-react";
import type { ReferenceImage } from "./types";
import StatusBar from "./components/Header";
import VideoInput, { type InputMode } from "./components/VideoInput";
import PolicyConfig from "./components/PolicyConfig";
import ReferencesPanel from "./components/ReferencesPanel";
import PollyChat from "./components/PollyChat";
import PipelineStatus from "./components/PipelineStatus";
import ReportView from "./components/ReportView";
import LiveReportView from "./components/LiveReportView";
import { analyzeVideo, healthCheck } from "./api";
import type { Policy, Report, PipelineStage } from "./types";

type LeftTab = "policy" | "references" | "polly";

const CHUNK_DURATION_MS = 8_000;

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
  const policyRef = useRef<Policy>({ rules: [], custom_prompt: "", include_audio: false, reference_images: [], enabled_reference_ids: [] });

  const [policy, setPolicy] = useState<Policy>({ rules: [], custom_prompt: "", include_audio: false, reference_images: [], enabled_reference_ids: [] });

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
  const recordChunk = useCallback(async (mySession: number): Promise<File | null> => {
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
      setTimeout(() => { if (recorder.state === "recording") recorder.stop(); }, CHUNK_DURATION_MS);
    });
    if (!monitoringRef.current || sessionIdRef.current !== mySession) return null;
    return new File([blob], `chunk-${Date.now()}.webm`, { type: "video/webm" });
  }, []);

  /** Upload + analyze a single chunk. Fire-and-forget friendly. */
  const analyzeChunk = useCallback(async (file: File, mySession: number) => {
    setLiveStage("uploading");
    const result = await analyzeVideo(file, policyRef.current, (s) => {
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
  }, []);

  /**
   * Pipelined loop: overlaps recording and analysis.
   *
   * Timeline:
   *   record(8s) ──→ fire analyze ──→ record(8s) ──→ wait prev analyze ──→ fire analyze ──→ ...
   *                   └── runs in background ──┘
   *
   * Effective cycle = max(8s record, ~15s analyze) instead of 8s + 15s.
   */
  const runMonitoringLoop = useCallback(async () => {
    const mySession = sessionIdRef.current;

    // Warm-start: ping backend to pre-establish HTTP connection + warm any caches
    try { await healthCheck(); } catch { /* ignore */ }

    let pendingAnalysis: Promise<void> | null = null;

    while (monitoringRef.current && sessionIdRef.current === mySession) {
      // 1. Record chunk (8s of video)
      const file = await recordChunk(mySession);
      if (!file || !monitoringRef.current || sessionIdRef.current !== mySession) break;

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
                <Shield className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-bold tracking-tight" style={{ color: "var(--color-text)" }}>
                Compliance Vision
              </span>
            </div>
            <StatusBar />
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

        {/* Tab content — scrollable */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
              <div className="text-center space-y-3">
                <Scan className="w-14 h-14 mx-auto" style={{ color: "var(--color-border)" }} />
                <p className="text-sm" style={{ color: "var(--color-text-dim)" }}>
                  {isFileRunning
                    ? "Analyzing video..."
                    : "Upload a video and configure a policy to get started."}
                </p>
                {!isFileRunning && (
                  <p className="text-xs" style={{ color: "var(--color-border)" }}>
                    The compliance report will appear here.
                  </p>
                )}
              </div>
            </div>
          )
        ) : (
          <LiveReportView
            reports={liveReports}
            isMonitoring={isMonitoring}
            sessionStart={sessionStart}
          />
        )}
      </div>
    </div>
  );
}
