import { Upload, Video, Camera, X, Circle, Square } from "lucide-react";
import { useRef, useState, useCallback, useEffect } from "react";

export type InputMode = "file" | "webcam";

interface Props {
  mode: InputMode;
  onModeChange: (mode: InputMode) => void;
  file: File | null;
  onFileChange: (file: File | null) => void;
  isMonitoring: boolean;
  onStartMonitoring: () => void;
  onStopMonitoring: () => void;
  disabled?: boolean;
}

export default function VideoInput({
  mode,
  onModeChange,
  file,
  onFileChange,
  isMonitoring,
  onStartMonitoring,
  onStopMonitoring,
  disabled,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [camError, setCamError] = useState<string | null>(null);

  const videoUrl = file ? URL.createObjectURL(file) : null;

  // Start/stop webcam when mode changes
  useEffect(() => {
    if (mode === "webcam" && !stream) {
      navigator.mediaDevices
        .getUserMedia({ video: { width: 640, height: 480 }, audio: true })
        .then((s) => {
          setStream(s);
          setCamError(null);
        })
        .catch((err) => {
          setCamError(err.message || "Camera access denied");
        });
    }
    if (mode === "file" && stream) {
      stream.getTracks().forEach((t) => t.stop());
      setStream(null);
    }
    // Cleanup on unmount
    return () => {
      if (mode === "webcam" && stream) {
        // don't stop here, let mode change handle it
      }
    };
  }, [mode]);

  // Attach stream to video element
  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f && f.type.startsWith("video/")) onFileChange(f);
    },
    [onFileChange]
  );

  const handleModeSwitch = (newMode: InputMode) => {
    if (isMonitoring) return; // Can't switch while monitoring
    if (newMode === "file" && stream) {
      stream.getTracks().forEach((t) => t.stop());
      setStream(null);
    }
    onModeChange(newMode);
  };

  return (
    <div className="space-y-3">
      {/* Mode toggle */}
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
          Video Input
        </label>
        <div
          className="flex rounded overflow-hidden border"
          style={{ borderColor: "var(--color-border)" }}
        >
          <button
            onClick={() => handleModeSwitch("file")}
            disabled={isMonitoring}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 transition-colors"
            style={{
              background: mode === "file" ? "var(--color-accent)" : "transparent",
              color: mode === "file" ? "white" : "var(--color-text-dim)",
              opacity: isMonitoring && mode !== "file" ? 0.3 : 1,
            }}
          >
            <Upload className="w-3 h-3" /> File
          </button>
          <button
            onClick={() => handleModeSwitch("webcam")}
            disabled={isMonitoring}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 transition-colors"
            style={{
              background: mode === "webcam" ? "var(--color-accent)" : "transparent",
              color: mode === "webcam" ? "white" : "var(--color-text-dim)",
              opacity: isMonitoring && mode !== "webcam" ? 0.3 : 1,
            }}
          >
            <Camera className="w-3 h-3" /> Webcam
          </button>
        </div>
      </div>

      {/* File mode */}
      {mode === "file" && (
        <>
          {!file ? (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => !disabled && inputRef.current?.click()}
              className="flex flex-col items-center justify-center gap-3 p-8 rounded border-2 border-dashed cursor-pointer transition-all"
              style={{
                borderColor: dragOver ? "var(--color-accent)" : "var(--color-border)",
                background: dragOver ? "rgba(15,23,42,0.04)" : "var(--color-surface-2)",
                opacity: disabled ? 0.5 : 1,
              }}
            >
              <Upload className="w-8 h-8" style={{ color: "var(--color-text-dim)" }} />
              <div className="text-center">
                <p className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
                  Drop video here or click to browse
                </p>
                <p className="text-xs mt-1" style={{ color: "var(--color-text-dim)" }}>
                  MP4, WebM, MOV — any length
                </p>
              </div>
              <input
                ref={inputRef}
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onFileChange(f);
                }}
              />
            </div>
          ) : (
            <div className="rounded overflow-hidden border"
              style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}>
              <video src={videoUrl!} controls className="w-full max-h-48 object-contain bg-black" />
              <div className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-2">
                  <Video className="w-4 h-4" style={{ color: "var(--color-accent)" }} />
                  <span className="text-xs truncate max-w-[200px]" style={{ color: "var(--color-text)" }}>
                    {file.name}
                  </span>
                  <span className="text-xs" style={{ color: "var(--color-text-dim)" }}>
                    ({(file.size / 1024 / 1024).toFixed(1)} MB)
                  </span>
                </div>
                {!disabled && (
                  <button onClick={() => onFileChange(null)} className="p-1 rounded hover:bg-black/5 transition-colors">
                    <X className="w-4 h-4" style={{ color: "var(--color-text-dim)" }} />
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* Webcam mode */}
      {mode === "webcam" && (
        <div className="space-y-3">
          {camError ? (
            <div className="flex flex-col items-center justify-center gap-2 p-8 rounded border"
              style={{ borderColor: "var(--color-critical)", background: "rgba(239,68,68,0.06)" }}>
              <Camera className="w-8 h-8" style={{ color: "var(--color-critical)" }} />
              <p className="text-xs text-center" style={{ color: "var(--color-critical)" }}>
                {camError}
              </p>
              <p className="text-xs text-center" style={{ color: "var(--color-text-dim)" }}>
                Allow camera access in your browser settings.
              </p>
            </div>
          ) : (
            <>
              <div className="rounded overflow-hidden border relative"
                style={{ borderColor: isMonitoring ? "var(--color-critical)" : "var(--color-border)", background: "black" }}>
                <video
                  ref={videoRef}
                  autoPlay
                  muted
                  playsInline
                  className="w-full max-h-48 object-contain"
                />
                {isMonitoring && (
                  <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-bold"
                    style={{ background: "rgba(239,68,68,0.9)", color: "white" }}>
                    <Circle className="w-2 h-2 fill-current animate-pulse-glow" />
                    LIVE MONITORING
                  </div>
                )}
              </div>

              {/* Start/Stop button */}
              <button
                onClick={isMonitoring ? onStopMonitoring : onStartMonitoring}
                disabled={disabled && !isMonitoring}
                className="w-full flex items-center justify-center gap-2 py-2.5 rounded text-xs font-semibold text-white transition-all"
                style={{
                  background: isMonitoring ? "var(--color-critical)" : "var(--color-compliant)",
                  opacity: disabled && !isMonitoring ? 0.4 : 1,
                }}
              >
                {isMonitoring ? (
                  <><Square className="w-3.5 h-3.5" /> Stop Monitoring</>
                ) : (
                  <><Circle className="w-3.5 h-3.5 fill-current" /> Start Monitoring</>
                )}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
