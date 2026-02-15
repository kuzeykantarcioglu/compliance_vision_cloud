import { Wifi, WifiOff, AlertCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { healthCheck } from "../api";

/** Compact inline status indicators — used inside the side panel, not as a header. */
export default function StatusBar() {
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [keySet, setKeySet] = useState(false);

  useEffect(() => {
    healthCheck()
      .then((d) => {
        setApiOk(true);
        setKeySet(d.openai_key_set);
      })
      .catch(() => setApiOk(false));
  }, []);

  // Don't render anything if everything is fine
  if (apiOk === true && keySet) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {apiOk === null && (
        <span className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded"
          style={{ background: "var(--color-surface-2)", color: "var(--color-text-dim)" }}>
          Connecting...
        </span>
      )}
      {apiOk === false && (
        <span className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded"
          style={{ background: "rgba(220,38,38,0.08)", color: "var(--color-critical)" }}>
          <WifiOff className="w-3 h-3" />
          API offline
        </span>
      )}
      {apiOk === true && !keySet && (
        <span className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded"
          style={{ background: "rgba(202,138,4,0.1)", color: "var(--color-medium)" }}>
          <AlertCircle className="w-3 h-3" />
          OpenAI key not set
        </span>
      )}
      {apiOk === true && (
        <span className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded"
          style={{ background: "rgba(22,163,74,0.08)", color: "var(--color-compliant)" }}>
          <Wifi className="w-3 h-3" />
          Connected
        </span>
      )}
    </div>
  );
}
