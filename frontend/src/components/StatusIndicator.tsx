import { Circle } from "lucide-react";
import { useEffect, useState } from "react";
import { healthCheck } from "../api";

type Status = "connecting" | "online" | "offline";

const statusConfig: Record<Status, { color: string; label: string; pulse: boolean }> = {
  online:     { color: "#22c55e", label: "Online",  pulse: false },
  connecting: { color: "#eab308", label: "Connecting", pulse: true },
  offline:    { color: "#ef4444", label: "Offline", pulse: false },
};

const dgxConfig: Record<Status, { color: string; label: string; pulse: boolean }> = {
  online:     { color: "#22c55e", label: "DGX",        pulse: false },
  connecting: { color: "#eab308", label: "DGX",        pulse: true },
  offline:    { color: "#ef4444", label: "DGX",        pulse: false },
};

function Dot({ color, pulse }: { color: string; pulse: boolean }) {
  return (
    <Circle
      className={`w-2 h-2 fill-current shrink-0 ${pulse ? "animate-pulse" : ""}`}
      style={{ color }}
    />
  );
}

export default function StatusIndicator() {
  const [apiStatus, setApiStatus] = useState<Status>("connecting");
  const [dgxStatus, setDgxStatus] = useState<Status>("connecting");

  useEffect(() => {
    const check = async () => {
      try {
        const data = await healthCheck();
        setApiStatus("online");
        if (data.dgx) {
          setDgxStatus(data.dgx.status === "connected" ? "online" : data.dgx.status === "checking" ? "connecting" : "offline");
        } else {
          setDgxStatus("offline");
        }
      } catch {
        setApiStatus("offline");
        setDgxStatus("offline");
      }
    };

    check();
    const interval = setInterval(check, 60_000);
    return () => clearInterval(interval);
  }, []);

  const api = statusConfig[apiStatus];
  const dgx = dgxConfig[dgxStatus];

  return (
    <div className="flex items-center gap-2.5 text-[9px] font-medium mt-0.5">
      <div className="flex items-center gap-1" style={{ color: api.color }}>
        <Dot color={api.color} pulse={api.pulse} />
        {api.label}
      </div>
      <div className="flex items-center gap-1" style={{ color: dgx.color }}>
        <Dot color={dgx.color} pulse={dgx.pulse} />
        {dgx.label}
      </div>
    </div>
  );
}
