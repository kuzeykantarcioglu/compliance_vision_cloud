import { Eye, Scale, Camera } from "lucide-react";
import { useEffect, useState } from "react";

const icons = [
  { Icon: Camera, label: "Capture", color: "#3b82f6" },
  { Icon: Eye, label: "Analyze", color: "#8b5cf6" },
  { Icon: Scale, label: "Evaluate", color: "#10b981" },
];

export default function EmptyStateAnimation() {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % icons.length);
    }, 1800);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center max-w-lg mx-auto">
        {/* Horizontal icon strip */}
        <div className="flex items-center justify-center gap-3 mb-10">
          {icons.map((item, index) => {
            const { Icon, color } = item;
            const isActive = index === activeIndex;
            const distance = Math.abs(index - activeIndex);
            // Wrap-around distance for smooth looping
            const wrappedDist = Math.min(distance, icons.length - distance);
            const dimOpacity = wrappedDist === 0 ? 1 : wrappedDist === 1 ? 0.45 : 0.15;

            return (
              <div key={index} className="flex flex-col items-center gap-2">
                {/* Icon container */}
                <div
                  className="relative flex items-center justify-center transition-all duration-500 ease-out"
                  style={{
                    width: isActive ? 56 : 40,
                    height: isActive ? 56 : 40,
                    borderRadius: isActive ? 16 : 12,
                    background: isActive
                      ? `linear-gradient(135deg, ${color}18, ${color}30)`
                      : "var(--color-surface-2)",
                    boxShadow: isActive
                      ? `0 0 20px ${color}25, 0 4px 12px ${color}15`
                      : "none",
                    border: `1.5px solid ${isActive ? color + "40" : "transparent"}`,
                    opacity: dimOpacity,
                    transform: isActive ? "translateY(-4px)" : "translateY(0)",
                  }}
                >
                  <Icon
                    className="transition-all duration-500"
                    style={{
                      width: isActive ? 24 : 18,
                      height: isActive ? 24 : 18,
                      color: isActive ? color : "var(--color-text-dim)",
                    }}
                  />
                  {/* Active glow ring */}
                  {isActive && (
                    <div
                      className="absolute inset-0 animate-ping rounded-[16px] opacity-20"
                      style={{
                        border: `2px solid ${color}`,
                        animationDuration: "1.5s",
                      }}
                    />
                  )}
                </div>
                {/* Label */}
                <span
                  className="text-[10px] font-medium transition-all duration-500"
                  style={{
                    color: isActive ? color : "var(--color-text-dim)",
                    opacity: dimOpacity,
                    transform: isActive ? "scale(1.05)" : "scale(1)",
                  }}
                >
                  {item.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* Connector line with travelling pulse */}
        <div className="relative w-64 h-px mx-auto mb-8">
          <div className="absolute inset-0" style={{ background: "var(--color-border)" }} />
          <div
            className="absolute top-1/2 -translate-y-1/2 h-0.5 w-10 rounded-full transition-all duration-500 ease-out"
            style={{
              background: `linear-gradient(90deg, transparent, ${icons[activeIndex].color}, transparent)`,
              left: `${(activeIndex / (icons.length - 1)) * 100}%`,
              transform: "translate(-50%, -50%)",
              boxShadow: `0 0 8px ${icons[activeIndex].color}50`,
            }}
          />
        </div>

        {/* Text */}
        <h3
          className="text-base font-semibold mb-2 transition-colors duration-500"
          style={{ color: "var(--color-text)" }}
        >
          {icons[activeIndex].label}
        </h3>
        <p className="text-sm" style={{ color: "var(--color-text-dim)" }}>
          Upload a video or start webcam monitoring to begin analysis
        </p>

        {/* Minimal step indicator */}
        <div className="flex items-center justify-center gap-1.5 mt-6">
          {icons.map((item, index) => (
            <div
              key={index}
              className="rounded-full transition-all duration-500"
              style={{
                width: index === activeIndex ? 20 : 5,
                height: 5,
                background:
                  index === activeIndex
                    ? `linear-gradient(90deg, ${item.color}, ${item.color}90)`
                    : "var(--color-border)",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
