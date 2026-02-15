import { ImagePlus, X, Check, Ban, Plus, ChevronDown, ChevronRight } from "lucide-react";
import { useRef, useCallback, useState } from "react";
import type { ReferenceImage, ReferenceCategory } from "../types";

interface Props {
  images: ReferenceImage[];
  onChange: (images: ReferenceImage[]) => void;
  disabled?: boolean;
  defaultCategory?: ReferenceCategory;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(",")[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** Auto-generate default checks based on category */
function defaultChecks(category: ReferenceCategory): string[] {
  switch (category) {
    case "people":
      return [
        "Is this specific person visible in the frame?",
        "Is anyone else present who is NOT this person?",
      ];
    case "badges":
      return [
        "Does any badge in the frame match this design?",
        "Are there badges that do NOT match this reference?",
      ];
    case "objects":
      return [
        "Is this object/item present in the frame?",
      ];
  }
}

export default function ReferenceImages({ images, onChange, disabled, defaultCategory = "objects" }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  const addImage = useCallback(
    async (file: File) => {
      const base64 = await fileToBase64(file);
      onChange([
        ...images,
        {
          id: crypto.randomUUID(),
          label: file.name.replace(/\.[^.]+$/, ""),
          image_base64: base64,
          match_mode: "must_match",
          category: defaultCategory,
          checks: defaultChecks(defaultCategory),
        },
      ]);
      // Auto-expand the newly added image
      setExpandedIndex(images.length);
    },
    [images, onChange, defaultCategory]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith("image/")) addImage(file);
    },
    [addImage]
  );

  const updateImage = (index: number, updates: Partial<ReferenceImage>) => {
    const updated = [...images];
    updated[index] = { ...updated[index], ...updates };
    onChange(updated);
  };

  const removeImage = (index: number) => {
    onChange(images.filter((_, i) => i !== index));
    if (expandedIndex === index) setExpandedIndex(null);
  };

  const addCheck = (imgIndex: number) => {
    const img = images[imgIndex];
    updateImage(imgIndex, { checks: [...img.checks, ""] });
  };

  const updateCheck = (imgIndex: number, checkIndex: number, value: string) => {
    const img = images[imgIndex];
    const checks = [...img.checks];
    checks[checkIndex] = value;
    updateImage(imgIndex, { checks });
  };

  const removeCheck = (imgIndex: number, checkIndex: number) => {
    const img = images[imgIndex];
    updateImage(imgIndex, { checks: img.checks.filter((_, i) => i !== checkIndex) });
  };

  return (
    <div className="space-y-2">
      {images.map((img, i) => {
        const isExpanded = expandedIndex === i;
        return (
          <div
            key={i}
            className="rounded border animate-slide-up overflow-hidden"
            style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}
          >
            {/* Main row: thumbnail + label + mode + expand */}
            <div className="flex items-start gap-2.5 p-2.5">
              <img
                src={`data:image/jpeg;base64,${img.image_base64}`}
                alt={img.label}
                className="w-14 h-14 rounded object-cover shrink-0 border"
                style={{ borderColor: "var(--color-border)" }}
              />

              <div className="flex-1 min-w-0 space-y-1.5">
                <input
                  type="text"
                  value={img.label}
                  onChange={(e) => updateImage(i, { label: e.target.value })}
                  disabled={disabled}
                  placeholder="Name this reference..."
                  className="w-full text-xs px-2 py-1.5 rounded border bg-transparent placeholder:text-gray-500 font-medium"
                  style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
                />
                <div className="flex gap-1.5">
                  <button
                    onClick={() => updateImage(i, { match_mode: "must_match" })}
                    disabled={disabled}
                    className="flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors"
                    style={{
                      background: img.match_mode === "must_match" ? "rgba(22,163,74,0.12)" : "transparent",
                      color: img.match_mode === "must_match" ? "var(--color-compliant)" : "var(--color-text-dim)",
                      border: `1px solid ${img.match_mode === "must_match" ? "var(--color-compliant)" : "var(--color-border)"}`,
                    }}
                  >
                    <Check className="w-2.5 h-2.5" /> Authorized
                  </button>
                  <button
                    onClick={() => updateImage(i, { match_mode: "must_not_match" })}
                    disabled={disabled}
                    className="flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-colors"
                    style={{
                      background: img.match_mode === "must_not_match" ? "rgba(220,38,38,0.12)" : "transparent",
                      color: img.match_mode === "must_not_match" ? "var(--color-critical)" : "var(--color-text-dim)",
                      border: `1px solid ${img.match_mode === "must_not_match" ? "var(--color-critical)" : "var(--color-border)"}`,
                    }}
                  >
                    <Ban className="w-2.5 h-2.5" /> Unauthorized
                  </button>
                </div>
              </div>

              <div className="flex flex-col items-center gap-1 shrink-0">
                {!disabled && (
                  <button
                    onClick={() => removeImage(i)}
                    className="p-1 rounded hover:bg-black/5 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" style={{ color: "var(--color-text-dim)" }} />
                  </button>
                )}
                <button
                  onClick={() => setExpandedIndex(isExpanded ? null : i)}
                  className="p-1 rounded hover:bg-black/5 transition-colors"
                  title={isExpanded ? "Collapse checks" : "Expand checks"}
                >
                  {isExpanded
                    ? <ChevronDown className="w-3.5 h-3.5" style={{ color: "var(--color-text-dim)" }} />
                    : <ChevronRight className="w-3.5 h-3.5" style={{ color: "var(--color-text-dim)" }} />
                  }
                </button>
              </div>
            </div>

            {/* Checks count badge (when collapsed) */}
            {!isExpanded && img.checks.length > 0 && (
              <div
                className="px-3 pb-2 -mt-1 cursor-pointer"
                onClick={() => setExpandedIndex(i)}
              >
                <span className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
                  {img.checks.length} check{img.checks.length !== 1 ? "s" : ""} configured
                </span>
              </div>
            )}

            {/* Expanded: per-reference checks */}
            {isExpanded && (
              <div className="px-3 pb-3 space-y-1.5 border-t pt-2" style={{ borderColor: "var(--color-border)" }}>
                <p className="text-[10px] font-medium" style={{ color: "var(--color-text-dim)" }}>
                  What should the AI check for this reference?
                </p>
                {img.checks.map((check, ci) => (
                  <div key={ci} className="flex gap-1.5 items-center">
                    <span className="text-[10px] shrink-0 w-4 text-right" style={{ color: "var(--color-text-dim)" }}>
                      {ci + 1}.
                    </span>
                    <input
                      type="text"
                      value={check}
                      onChange={(e) => updateCheck(i, ci, e.target.value)}
                      disabled={disabled}
                      placeholder="e.g. Is this person present in the frame?"
                      className="flex-1 text-[11px] px-2 py-1.5 rounded border bg-transparent placeholder:text-gray-400"
                      style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
                    />
                    {!disabled && (
                      <button
                        onClick={() => removeCheck(i, ci)}
                        className="p-0.5 rounded hover:bg-black/5 transition-colors shrink-0"
                      >
                        <X className="w-3 h-3" style={{ color: "var(--color-text-dim)" }} />
                      </button>
                    )}
                  </div>
                ))}
                {!disabled && (
                  <button
                    onClick={() => addCheck(i)}
                    className="flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-dashed w-full justify-center hover:bg-black/5 transition-colors"
                    style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}
                  >
                    <Plus className="w-2.5 h-2.5" /> Add check
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* Drop zone */}
      {!disabled && (
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className="flex items-center justify-center gap-2 p-4 rounded border-2 border-dashed cursor-pointer transition-all hover:bg-black/5"
          style={{ borderColor: "var(--color-border)" }}
        >
          <ImagePlus className="w-4 h-4" style={{ color: "var(--color-text-dim)" }} />
          <span className="text-xs" style={{ color: "var(--color-text-dim)" }}>
            Drop reference image or click to browse
          </span>
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) addImage(f);
              e.target.value = "";
            }}
          />
        </div>
      )}
    </div>
  );
}
