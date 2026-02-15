import { Shield, Eye, Scale, FileText } from "lucide-react";
import { useEffect, useState } from "react";

export default function EmptyStateAnimation() {
  const [activeIndex, setActiveIndex] = useState(0);
  
  const icons = [
    { Icon: Shield, label: "Security Monitoring", color: "#3b82f6" },
    { Icon: Eye, label: "Visual Analysis", color: "#8b5cf6" },
    { Icon: Scale, label: "Compliance Evaluation", color: "#10b981" },
    { Icon: FileText, label: "Report Generation", color: "#f59e0b" },
  ];

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % icons.length);
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        {/* Rotating icon display */}
        <div className="relative w-32 h-32 mx-auto mb-8">
          {/* Background circle */}
          <div className="absolute inset-0 rounded-full bg-gradient-to-r from-blue-500/10 to-purple-500/10 animate-pulse" />
          
          {/* Icons */}
          {icons.map((item, index) => {
            const { Icon, color } = item;
            const isActive = index === activeIndex;
            const angle = (index * 360) / icons.length;
            const radius = 40;
            const x = Math.cos((angle * Math.PI) / 180) * radius;
            const y = Math.sin((angle * Math.PI) / 180) * radius;
            
            return (
              <div
                key={index}
                className={`absolute top-1/2 left-1/2 transition-all duration-500 ${
                  isActive ? 'scale-125' : 'scale-75 opacity-30'
                }`}
                style={{
                  transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`,
                }}
              >
                <Icon 
                  className="w-8 h-8" 
                  style={{ color: isActive ? color : '#94a3b8' }}
                />
              </div>
            );
          })}
          
          {/* Center pulse */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <div className="w-4 h-4 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full">
              <div className="w-4 h-4 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full animate-ping" />
            </div>
          </div>
        </div>
        
        {/* Text */}
        <h3 className="text-lg font-semibold mb-2" style={{ color: "var(--color-text)" }}>
          {icons[activeIndex].label}
        </h3>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--color-text-dim)" }}>
          Upload a video or start webcam monitoring to begin compliance analysis
        </p>
        
        {/* Progress dots */}
        <div className="flex items-center justify-center gap-2 mt-6">
          {icons.map((_, index) => (
            <div
              key={index}
              className={`h-1.5 rounded-full transition-all duration-500 ${
                index === activeIndex ? 'w-8 bg-gradient-to-r from-blue-500 to-purple-500' : 'w-1.5 bg-gray-300'
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}