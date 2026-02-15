import { Cpu, Cloud, Zap } from "lucide-react";
import type { AIProvider } from "../types";

interface ProviderToggleProps {
  provider: AIProvider;
  onChange: (provider: AIProvider) => void;
  disabled?: boolean;
}

export default function ProviderToggle({ provider, onChange, disabled }: ProviderToggleProps) {

  const providers: { key: AIProvider; label: string; icon: typeof Cloud; desc: string }[] = [
    { key: "openai", label: "OpenAI", icon: Cloud, desc: "GPT-4o-mini" },
    { key: "dgx", label: "DGX Spark", icon: Cpu, desc: "Cosmos + Nemotron" },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Zap className="w-3.5 h-3.5" style={{ color: "var(--color-text-dim)" }} />
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-dim)" }}>
          AI Provider
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {providers.map((p) => {
          const Icon = p.icon;
          const isActive = provider === p.key;

          return (
            <button
              key={p.key}
              onClick={() => !disabled && onChange(p.key)}
              disabled={disabled}
              className="relative flex flex-col items-center gap-1.5 px-3 py-3 rounded border text-xs transition-all"
              style={{
                borderColor: isActive ? "var(--color-accent)" : "var(--color-border)",
                background: isActive ? "var(--color-accent-bg, rgba(59,130,246,0.08))" : "var(--color-surface)",
                opacity: disabled ? 0.5 : 1,
                cursor: disabled ? "not-allowed" : "pointer",
              }}
            >
              {/* Active indicator dot */}
              {isActive && (
                <div
                  className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full"
                  style={{ background: "var(--color-accent)" }}
                />
              )}

              <Icon
                className="w-5 h-5"
                style={{ color: isActive ? "var(--color-accent)" : "var(--color-text-dim)" }}
              />

              <span
                className="font-semibold"
                style={{ color: isActive ? "var(--color-text)" : "var(--color-text-dim)" }}
              >
                {p.label}
              </span>

              <span
                className="text-[10px]"
                style={{ color: "var(--color-text-dim)" }}
              >
                {p.desc}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
