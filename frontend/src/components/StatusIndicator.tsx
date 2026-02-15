import { Circle } from "lucide-react";
import { useEffect, useState } from "react";
import { healthCheck } from "../api";

export default function StatusIndicator() {
  const [status, setStatus] = useState<"connecting" | "online" | "offline">("connecting");

  useEffect(() => {
    const checkStatus = async () => {
      try {
        await healthCheck();
        setStatus("online");
      } catch {
        setStatus("offline");
      }
    };

    // Initial check
    checkStatus();

    // Check every 5 seconds
    const interval = setInterval(checkStatus, 5000);

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

  return (
    <div className="flex items-center gap-1.5 text-[10px] font-medium" style={{ color: config.color }}>
      <Circle 
        className={`w-2 h-2 fill-current ${config.pulse ? 'animate-pulse' : ''}`} 
        style={{ color: config.color }}
      />
      {config.text}
    </div>
  );
}