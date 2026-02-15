import { Circle } from "lucide-react";
import { useEffect, useState } from "react";
import { healthCheck } from "../api";

export default function StatusIndicator() {
  const [status, setStatus] = useState<"connecting" | "online" | "offline">("connecting");
  const [dgxStatus, setDgxStatus] = useState<string | null>(null);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const data = await healthCheck();
        setStatus("online");
        if (data.dgx) {
          setDgxStatus(data.dgx.status);
        }
      } catch {
        setStatus("offline");
      }
    };

    // Initial check
    checkStatus();

    // Check every 60 seconds (reduced from 5s to avoid log spam)
    const interval = setInterval(checkStatus, 60_000);

    return () => clearInterval(interval);
  }, []);

  const getStatusConfig = () => {
    switch (status) {
      case "online":
        return {
          color: "#22c55e", // green
          text: "Online",
          pulse: false,
        };
      case "connecting":
        return {
          color: "#eab308", // yellow
          text: "Connecting...",
          pulse: true,
        };
      case "offline":
        return {
          color: "#ef4444", // red
          text: "Offline",
          pulse: false,
        };
    }
  };

  const config = getStatusConfig();
  const dgxColor = dgxStatus === "connected" ? "#22c55e" : dgxStatus === "checking" ? "#eab308" : "#ef4444";
  const dgxLabel = dgxStatus === "connected" ? "DGX" : dgxStatus === "checking" ? "DGX..." : dgxStatus === "unreachable" ? "DGX ✗" : null;

  return (
    <div className="flex items-center gap-2 text-[10px] font-medium">
      <div className="flex items-center gap-1.5" style={{ color: config.color }}>
        <Circle 
          className={`w-2 h-2 fill-current ${config.pulse ? 'animate-pulse' : ''}`} 
          style={{ color: config.color }}
        />
        {config.text}
      </div>
      {dgxLabel && (
        <div className="flex items-center gap-1" style={{ color: dgxColor }}>
          <Circle className="w-1.5 h-1.5 fill-current" style={{ color: dgxColor }} />
          {dgxLabel}
        </div>
      )}
    </div>
  );
}