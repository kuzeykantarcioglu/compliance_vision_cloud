import { Users, CreditCard, Package } from "lucide-react";
import { useState } from "react";
import type { ReferenceImage, ReferenceCategory } from "../types";
import ReferenceImages from "./ReferenceImages";

interface Props {
  images: ReferenceImage[];
  onChange: (images: ReferenceImage[]) => void;
  disabled?: boolean;
}

const CATEGORIES: { key: ReferenceCategory; label: string; icon: typeof Users; description: string }[] = [
  {
    key: "people",
    label: "People",
    icon: Users,
    description: "Authorized or unauthorized personnel — faces, uniforms",
  },
  {
    key: "badges",
    label: "Badges",
    icon: CreditCard,
    description: "Approved badge designs, ID cards, access passes",
  },
  {
    key: "objects",
    label: "Objects",
    icon: Package,
    description: "Equipment, vehicles, PPE, or items to look for",
  },
];

export default function ReferencesPanel({ images, onChange, disabled }: Props) {
  const [activeCategory, setActiveCategory] = useState<ReferenceCategory>("people");

  const categoryImages = images.filter((img) => img.category === activeCategory);
  const categoryCounts = {
    people: images.filter((i) => i.category === "people").length,
    badges: images.filter((i) => i.category === "badges").length,
    objects: images.filter((i) => i.category === "objects").length,
  };

  const handleCategoryChange = (newImages: ReferenceImage[]) => {
    // Replace images of the active category, keep others
    const otherImages = images.filter((img) => img.category !== activeCategory);
    onChange([...otherImages, ...newImages]);
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold" style={{ color: "var(--color-text)" }}>
          Visual References
        </h3>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-dim)" }}>
          Upload images of authorized people, approved badges, or specific objects.
          These will be compared against video frames during analysis.
        </p>
      </div>

      {/* Category tabs */}
      <div className="flex gap-1 p-1 rounded border" style={{ borderColor: "var(--color-border)", background: "var(--color-surface-2)" }}>
        {CATEGORIES.map((cat) => {
          const Icon = cat.icon;
          const isActive = activeCategory === cat.key;
          const count = categoryCounts[cat.key];
          return (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded text-xs font-medium transition-all"
              style={{
                background: isActive ? "var(--color-bg)" : "transparent",
                color: isActive ? "var(--color-text)" : "var(--color-text-dim)",
                boxShadow: isActive ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
              }}
            >
              <Icon className="w-3.5 h-3.5" />
              {cat.label}
              {count > 0 && (
                <span
                  className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                  style={{
                    background: isActive ? "var(--color-accent)" : "var(--color-border)",
                    color: isActive ? "white" : "var(--color-text-dim)",
                  }}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Category description */}
      <p className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
        {CATEGORIES.find((c) => c.key === activeCategory)?.description}
      </p>

      {/* Reference images for active category */}
      <ReferenceImages
        images={categoryImages}
        onChange={handleCategoryChange}
        disabled={disabled}
        defaultCategory={activeCategory}
      />

      {/* Summary footer */}
      {images.length > 0 && (
        <div className="flex items-center justify-between pt-2 border-t" style={{ borderColor: "var(--color-border)" }}>
          <span className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
            {images.length} total reference{images.length !== 1 ? "s" : ""} across all categories
          </span>
          {!disabled && (
            <button
              onClick={() => onChange([])}
              className="text-[10px] hover:underline"
              style={{ color: "var(--color-critical)" }}
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
