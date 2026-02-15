import { Sun, Moon, SunMoon, Contrast } from "lucide-react";
import { useState, useEffect } from "react";

type Theme = "light" | "night" | "dark" | "high-contrast";

const THEMES: { key: Theme; label: string; icon: typeof Sun }[] = [
  { key: "light", label: "Light", icon: Sun },
  { key: "night", label: "Night", icon: Moon },
  { key: "dark", label: "Dark", icon: SunMoon },
  { key: "high-contrast", label: "Hi-Con", icon: Contrast },
];

const STORAGE_KEY = "compliance_vision_theme";

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && THEMES.some((t) => t.key === stored)) return stored as Theme;
  } catch {}
  return "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(STORAGE_KEY, theme);
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getStoredTheme);

  // Apply on mount
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <div
      className="flex rounded overflow-hidden border"
      style={{ borderColor: "var(--color-border)" }}
    >
      {THEMES.map((t) => {
        const Icon = t.icon;
        const isActive = theme === t.key;
        return (
          <button
            key={t.key}
            onClick={() => setTheme(t.key)}
            className="flex items-center gap-1 text-[9px] px-2 py-1.5 transition-colors"
            style={{
              background: isActive ? "var(--color-accent)" : "transparent",
              color: isActive ? "var(--color-bg)" : "var(--color-text-dim)",
            }}
            title={t.label}
          >
            <Icon className="w-3 h-3" />
          </button>
        );
      })}
    </div>
  );
}
