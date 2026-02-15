import { Plus, Trash2, ChevronDown, Mic, MicOff, Save, Download, Upload, X, Star, Image } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import type { Policy, PolicyRule } from "../types";

interface Props {
  policy: Policy;
  onChange: (policy: Policy) => void;
  disabled?: boolean;
}

const STORAGE_KEY = "compliance_vision_presets";

const BUILT_IN_PRESETS: Record<string, Policy> = {
  "Audio: I Love TreeHacks": {
    rules: [
      { type: "speech", description: "The phrase 'I love TreeHacks' must be said at least 3 times", severity: "critical" },
      { type: "speech", description: "The speaker must sound enthusiastic when saying 'I love TreeHacks'", severity: "medium" },
      { type: "speech", description: "No long silences — the speaker should be actively talking", severity: "low" },
    ],
    custom_prompt: "Count exactly how many times 'I love TreeHacks' (or very close variants like 'I love tree hacks') is spoken. The requirement is at least 3 times. Report the exact count. Quote the relevant transcript segments.",
    include_audio: true,
    reference_images: [],
    enabled_reference_ids: [],
  },
  "TreeHacks Badge + Wave": {
    rules: [
      { type: "badge", description: "Person must be wearing a dark green, tree-shaped badge", severity: "critical" },
      { type: "action", description: "Person with the badge must be waving", severity: "high" },
      { type: "presence", description: "Only persons with the tree-shaped badge should be present", severity: "medium" },
    ],
    custom_prompt: "Look specifically for a dark green badge shaped like a tree (like a pine/evergreen). Check if the person wearing it is actively waving their hand. Report clearly whether the badge is visible and whether they are waving or not.",
    include_audio: false,
    reference_images: [],
    enabled_reference_ids: [],
  },
  "PPE Compliance": {
    rules: [
      { type: "ppe", description: "All persons must wear a hard hat", severity: "critical" },
      { type: "ppe", description: "All persons must wear a high-visibility safety vest", severity: "high" },
      { type: "ppe", description: "Safety goggles must be worn near machinery", severity: "high" },
    ],
    custom_prompt: "Focus on personal protective equipment compliance in an industrial/construction setting.",
    include_audio: false,
    reference_images: [],
    enabled_reference_ids: [],
  },
  "Badge & Access Control": {
    rules: [
      { type: "badge", description: "All persons must have a visible ID badge", severity: "high" },
      { type: "presence", description: "No unauthorized persons in the area", severity: "critical" },
      { type: "environment", description: "All doors to restricted areas must be closed", severity: "medium" },
    ],
    custom_prompt: "Focus on badge visibility and access control in a secure facility. Compare all badges against the reference image if provided.",
    include_audio: false,
    reference_images: [],
    enabled_reference_ids: [],
  },
  "Workspace Safety + Audio": {
    rules: [
      { type: "environment", description: "Emergency exits must be unobstructed", severity: "critical" },
      { type: "speech", description: "Safety briefing must be delivered verbally", severity: "high" },
      { type: "speech", description: "No hostile or aggressive language", severity: "critical" },
      { type: "ppe", description: "Closed-toe shoes required at all times", severity: "medium" },
    ],
    custom_prompt: "General workplace safety audit. Pay attention to verbal safety briefings and communications.",
    include_audio: true,
    reference_images: [],
    enabled_reference_ids: [],
  },
};

const SEVERITY_COLORS: Record<string, string> = {
  low: "var(--color-low)",
  medium: "var(--color-medium)",
  high: "var(--color-high)",
  critical: "var(--color-critical)",
};

const RULE_TYPES = ["ppe", "badge", "presence", "action", "environment", "speech", "custom"];

function loadCustomPresets(): Record<string, Policy> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveCustomPresets(presets: Record<string, Policy>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}

export default function PolicyConfig({ policy, onChange, disabled }: Props) {
  const [showPresets, setShowPresets] = useState(false);
  const [customPresets, setCustomPresets] = useState<Record<string, Policy>>({});
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveName, setSaveName] = useState("");
  const importRef = useRef<HTMLInputElement>(null);

  // Load custom presets from localStorage on mount
  useEffect(() => {
    setCustomPresets(loadCustomPresets());
  }, []);

  const allPresets = { ...BUILT_IN_PRESETS, ...customPresets };

  const handleSavePreset = () => {
    const name = saveName.trim();
    if (!name) return;
    const updated = { ...customPresets, [name]: { ...policy } };
    setCustomPresets(updated);
    saveCustomPresets(updated);
    setSaveName("");
    setShowSaveDialog(false);
  };

  const handleDeletePreset = (name: string) => {
    const updated = { ...customPresets };
    delete updated[name];
    setCustomPresets(updated);
    saveCustomPresets(updated);
  };

  const handleExportPolicy = () => {
    const exportData = {
      name: "Exported Policy",
      policy: { ...policy, reference_images: [] }, // Strip base64 images for clean export
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `policy-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImportPolicy = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result as string);
        const imported: Policy = data.policy || data;
        // Validate it has the right shape
        if (imported.rules && Array.isArray(imported.rules)) {
          onChange({
            rules: imported.rules,
            custom_prompt: imported.custom_prompt || "",
            include_audio: imported.include_audio || false,
            reference_images: imported.reference_images || [],
            enabled_reference_ids: imported.enabled_reference_ids ?? [],
          });
        }
      } catch {
        alert("Invalid policy JSON file.");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const addRule = () => {
    onChange({
      ...policy,
      rules: [...policy.rules, { type: "custom", description: "", severity: "high" }],
    });
  };

  const updateRule = (index: number, updates: Partial<PolicyRule>) => {
    const rules = [...policy.rules];
    rules[index] = { ...rules[index], ...updates };
    onChange({ ...policy, rules });
  };

  const removeRule = (index: number) => {
    onChange({ ...policy, rules: policy.rules.filter((_, i) => i !== index) });
  };

  const toggleReferenceRule = (refId: string) => {
    const current = policy.enabled_reference_ids ?? [];
    const next = current.includes(refId)
      ? current.filter((id) => id !== refId)
      : [...current, refId];
    onChange({ ...policy, enabled_reference_ids: next });
  };

  const isBuiltIn = (name: string) => name in BUILT_IN_PRESETS;

  return (
    <div className="space-y-4">
      {/* Header row: label + action buttons */}
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
          Compliance Policy
        </label>
        <div className="flex items-center gap-1.5">
          {/* Import */}
          <button
            onClick={() => importRef.current?.click()}
            disabled={disabled}
            className="flex items-center gap-1 text-[10px] px-2 py-1.5 rounded transition-colors hover:bg-black/5"
            style={{ color: "var(--color-text-dim)", opacity: disabled ? 0.5 : 1 }}
            title="Import policy from JSON file"
          >
            <Upload className="w-3 h-3" />
          </button>
          <input
            ref={importRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImportPolicy}
          />

          {/* Export */}
          <button
            onClick={handleExportPolicy}
            disabled={disabled || policy.rules.length === 0}
            className="flex items-center gap-1 text-[10px] px-2 py-1.5 rounded transition-colors hover:bg-black/5"
            style={{ color: "var(--color-text-dim)", opacity: disabled || policy.rules.length === 0 ? 0.3 : 1 }}
            title="Export current policy as JSON"
          >
            <Download className="w-3 h-3" />
          </button>

          {/* Save as preset */}
          <button
            onClick={() => setShowSaveDialog(true)}
            disabled={disabled || policy.rules.length === 0}
            className="flex items-center gap-1 text-[10px] px-2 py-1.5 rounded transition-colors hover:bg-black/5"
            style={{ color: "var(--color-text-dim)", opacity: disabled || policy.rules.length === 0 ? 0.3 : 1 }}
            title="Save current policy as preset"
          >
            <Save className="w-3 h-3" />
          </button>

          {/* Load preset dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowPresets(!showPresets)}
              disabled={disabled}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded transition-colors"
              style={{
                background: "var(--color-surface-2)",
                color: "var(--color-accent)",
                border: "1px solid var(--color-border)",
                opacity: disabled ? 0.5 : 1,
              }}
            >
              Load <ChevronDown className="w-3 h-3" />
            </button>
            {showPresets && (
              <div className="absolute right-0 top-full mt-1 w-60 rounded border shadow-xl z-20 max-h-72 overflow-y-auto"
                style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }}>

                {/* Custom presets first */}
                {Object.keys(customPresets).length > 0 && (
                  <>
                    <div className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide"
                      style={{ color: "var(--color-text-dim)", background: "var(--color-surface-2)" }}>
                      Your Presets
                    </div>
                    {Object.entries(customPresets).map(([name, preset]) => (
                      <div key={name} className="flex items-center group">
                        <button
                          onClick={() => { onChange(preset); setShowPresets(false); }}
                          className="flex-1 text-left text-xs px-3 py-2.5 hover:bg-black/5 transition-colors flex items-center gap-2"
                          style={{ color: "var(--color-text)" }}
                        >
                          <Star className="w-3 h-3 shrink-0" style={{ color: "var(--color-accent)" }} />
                          {name}
                          <span className="text-[9px] ml-auto" style={{ color: "var(--color-text-dim)" }}>
                            {preset.rules.length} rules
                          </span>
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeletePreset(name); }}
                          className="px-2 py-2.5 hover:bg-black/5 transition-colors opacity-0 group-hover:opacity-100"
                          title="Delete preset"
                        >
                          <X className="w-3 h-3" style={{ color: "var(--color-critical)" }} />
                        </button>
                      </div>
                    ))}
                  </>
                )}

                {/* Built-in presets */}
                <div className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide"
                  style={{ color: "var(--color-text-dim)", background: "var(--color-surface-2)" }}>
                  Built-in
                </div>
                {Object.entries(BUILT_IN_PRESETS).map(([name, preset]) => (
                  <button
                    key={name}
                    onClick={() => { onChange(preset); setShowPresets(false); }}
                    className="w-full text-left text-xs px-3 py-2.5 hover:bg-black/5 transition-colors flex items-center gap-2"
                    style={{ color: "var(--color-text)" }}
                  >
                    <span className="flex-1">{name}</span>
                    <span className="text-[9px]" style={{ color: "var(--color-text-dim)" }}>
                      {preset.rules.length} rules
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Save dialog */}
      {showSaveDialog && (
        <div className="flex gap-2 p-3 rounded border animate-slide-up"
          style={{ borderColor: "var(--color-accent)", background: "var(--color-surface-2)" }}>
          <input
            type="text"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSavePreset()}
            placeholder="Preset name..."
            className="flex-1 text-xs px-3 py-1.5 rounded border bg-transparent"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
            autoFocus
          />
          <button
            onClick={handleSavePreset}
            disabled={!saveName.trim()}
            className="text-xs px-3 py-1.5 rounded text-white font-medium"
            style={{ background: saveName.trim() ? "var(--color-accent)" : "var(--color-border)" }}
          >
            Save
          </button>
          <button
            onClick={() => { setShowSaveDialog(false); setSaveName(""); }}
            className="text-xs px-2 py-1.5 rounded hover:bg-black/5"
            style={{ color: "var(--color-text-dim)" }}
          >
            Cancel
          </button>
        </div>
      )}

      {/* Rules list */}
      <div className="space-y-2">
        {policy.rules.map((rule, i) => (
          <div
            key={i}
            className="flex items-start gap-2 p-3 rounded border animate-slide-up"
            style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}
          >
            <div className="flex-1 space-y-2">
              <div className="flex gap-2">
                <select
                  value={rule.type}
                  onChange={(e) => updateRule(i, { type: e.target.value })}
                  disabled={disabled}
                  className="text-xs px-2 py-1.5 rounded border bg-transparent"
                  style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
                >
                  {RULE_TYPES.map((t) => (
                    <option key={t} value={t} style={{ background: "var(--color-surface)" }}>
                      {t.toUpperCase()}
                    </option>
                  ))}
                </select>
                <select
                  value={rule.severity}
                  onChange={(e) => updateRule(i, { severity: e.target.value as PolicyRule["severity"] })}
                  disabled={disabled}
                  className="text-xs px-2 py-1.5 rounded border bg-transparent font-medium"
                  style={{
                    borderColor: "var(--color-border)",
                    color: SEVERITY_COLORS[rule.severity],
                  }}
                >
                  {["low", "medium", "high", "critical"].map((s) => (
                    <option key={s} value={s} style={{ background: "var(--color-surface)" }}>
                      {s.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
              <input
                type="text"
                value={rule.description}
                onChange={(e) => updateRule(i, { description: e.target.value })}
                disabled={disabled}
                placeholder="Describe the compliance rule..."
                className="w-full text-sm px-3 py-2 rounded border bg-transparent placeholder:text-gray-500"
                style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
              />
            </div>
            {!disabled && (
              <button
                onClick={() => removeRule(i)}
                className="p-1.5 rounded hover:bg-black/5 transition-colors mt-1"
              >
                <Trash2 className="w-3.5 h-3.5" style={{ color: "var(--color-text-dim)" }} />
              </button>
            )}
          </div>
        ))}
      </div>

        {!disabled && (
        <button
          onClick={addRule}
          className="flex items-center gap-2 text-xs px-3 py-2 rounded border border-dashed w-full justify-center transition-colors hover:bg-black/5"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}
        >
          <Plus className="w-3.5 h-3.5" /> Add Rule
        </button>
      )}

      {/* Reference Rules — toggle which references are checked */}
      {policy.reference_images.length > 0 && (
        <div className="space-y-2">
          <label className="text-xs font-medium flex items-center gap-1.5" style={{ color: "var(--color-text-dim)" }}>
            <Image className="w-3.5 h-3.5" />
            Reference Rules
          </label>
          <p className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
            Enable references to check during analysis. Uses checks from the References tab.
          </p>
          <div className="space-y-2">
            {policy.reference_images.map((ref) => {
              const refId = ref.id || `fallback-${ref.label}`;
              const enabled = (policy.enabled_reference_ids ?? []).includes(refId);
              return (
                <div
                  key={refId}
                  onClick={() => !disabled && toggleReferenceRule(refId)}
                  className="flex items-center gap-3 p-2.5 rounded border transition-all cursor-pointer"
                  style={{
                    borderColor: enabled ? "var(--color-accent)" : "var(--color-border)",
                    background: enabled ? "rgba(15,23,42,0.06)" : "var(--color-surface-2)",
                    opacity: disabled ? 0.5 : 1,
                    cursor: disabled ? "not-allowed" : "pointer",
                  }}
                >
                  <img
                    src={`data:image/jpeg;base64,${ref.image_base64}`}
                    alt={ref.label}
                    className="w-10 h-10 rounded object-cover shrink-0 border"
                    style={{ borderColor: "var(--color-border)" }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate" style={{ color: "var(--color-text)" }}>
                      {ref.label}
                    </p>
                    <p className="text-[10px] truncate" style={{ color: "var(--color-text-dim)" }}>
                      {ref.checks.filter((c) => c.trim()).length} check{ref.checks.filter((c) => c.trim()).length !== 1 ? "s" : ""} from References
                    </p>
                  </div>
                  <div
                    className="w-8 h-4.5 rounded-full relative shrink-0"
                    style={{
                      background: enabled ? "var(--color-accent)" : "var(--color-border)",
                      padding: "2px",
                    }}
                  >
                    <div
                      className="w-3.5 h-3.5 rounded-full bg-white transition-transform"
                      style={{ transform: enabled ? "translateX(14px)" : "translateX(0)" }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Custom prompt */}
      <div className="space-y-1.5">
        <label className="text-xs" style={{ color: "var(--color-text-dim)" }}>
          Additional context (optional)
        </label>
        <textarea
          value={policy.custom_prompt}
          onChange={(e) => onChange({ ...policy, custom_prompt: e.target.value })}
          disabled={disabled}
          placeholder="Add any extra context for the AI... e.g. 'This is a construction site near heavy machinery'"
          rows={2}
          className="w-full text-sm px-3 py-2 rounded border bg-transparent placeholder:text-gray-500 resize-none"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
        />
      </div>

      {/* Audio analysis toggle */}
      <button
        onClick={() => !disabled && onChange({ ...policy, include_audio: !policy.include_audio })}
        disabled={disabled}
        className="w-full flex items-center gap-3 px-3 py-2.5 rounded border transition-all"
        style={{
          borderColor: policy.include_audio ? "var(--color-accent)" : "var(--color-border)",
          background: policy.include_audio ? "rgba(15,23,42,0.06)" : "var(--color-surface-2)",
          opacity: disabled ? 0.5 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
      >
        {policy.include_audio ? (
          <Mic className="w-4 h-4 shrink-0" style={{ color: "var(--color-accent)" }} />
        ) : (
          <MicOff className="w-4 h-4 shrink-0" style={{ color: "var(--color-text-dim)" }} />
        )}
        <div className="flex-1 text-left">
          <p className="text-xs font-medium" style={{ color: "var(--color-text)" }}>
            Audio Analysis (Whisper)
          </p>
          <p className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
            {policy.include_audio
              ? "Enabled — audio will be transcribed and evaluated against policy"
              : "Disabled — only visual analysis will be performed"}
          </p>
        </div>
        <div
          className="w-8 h-4.5 rounded-full relative transition-colors"
          style={{
            background: policy.include_audio ? "var(--color-accent)" : "var(--color-border)",
            padding: "2px",
          }}
        >
          <div
            className="w-3.5 h-3.5 rounded-full bg-white transition-transform"
            style={{
              transform: policy.include_audio ? "translateX(14px)" : "translateX(0)",
            }}
          />
        </div>
      </button>

    </div>
  );
}
