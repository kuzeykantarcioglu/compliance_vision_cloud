import { Send, Bot, User, Sparkles, Loader2, Check } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { pollyChatApi, type PollyMessage } from "../api";
import type { Policy } from "../types";

interface Props {
  policy: Policy;
  onPolicyChange: (policy: Policy) => void;
  disabled?: boolean;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  suggestions?: string[];
  policyApplied?: boolean;
  policySnapshot?: Policy;
}

const WELCOME_SUGGESTIONS = [
  "Create a PPE compliance policy for a construction site",
  "I need to check that only authorized people enter a restricted zone",
  "Set up audio monitoring for safety briefings",
  "Monitor a warehouse for proper equipment usage",
];

export default function PollyChat({ policy, onPolicyChange, disabled }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return;

    const userMsg: ChatMessage = { role: "user", content: text.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    // Build history for API
    const history: PollyMessage[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    try {
      const res = await pollyChatApi(text.trim(), policy, history);
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: res.message,
        suggestions: res.suggestions,
        policyApplied: false,
        policySnapshot: res.policy,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
        },
      ]);
    }

    setLoading(false);
    inputRef.current?.focus();
  };

  const applyPolicy = (msgIndex: number) => {
    const msg = messages[msgIndex];
    if (!msg.policySnapshot) return;
    onPolicyChange(msg.policySnapshot);
    setMessages((prev) =>
      prev.map((m, i) => (i === msgIndex ? { ...m, policyApplied: true } : m))
    );
  };

  return (
    <div className="flex flex-col h-full -m-4" style={{ height: "calc(100% + 32px)" }}>
      {/* Chat header */}
      <div className="shrink-0 px-4 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded" style={{ background: "var(--color-accent)" }}>
            <Sparkles className="w-3.5 h-3.5 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: "var(--color-text)" }}>Polly</h3>
            <p className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
              Policy Creation Assistant
            </p>
          </div>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 space-y-3">
        {/* Welcome state */}
        {messages.length === 0 && (
          <div className="space-y-3 pt-2">
            <p className="text-xs leading-relaxed" style={{ color: "var(--color-text-dim)" }}>
              Tell me what you want to monitor and I'll create a compliance policy for you.
              You can describe your scenario in plain English.
            </p>
            <div className="space-y-1.5">
              <p className="text-[10px] font-medium" style={{ color: "var(--color-text-dim)" }}>
                Try something like:
              </p>
              {WELCOME_SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(s)}
                  disabled={loading}
                  className="w-full text-left text-xs px-3 py-2 rounded border hover:bg-black/5 transition-colors"
                  style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
                >
                  "{s}"
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Message list */}
        {messages.map((msg, i) => (
          <div key={i} className="animate-slide-up">
            {/* Message bubble */}
            <div className="flex gap-2">
              <div className="shrink-0 mt-0.5">
                {msg.role === "user" ? (
                  <div className="w-5 h-5 rounded flex items-center justify-center"
                    style={{ background: "var(--color-surface-2)" }}>
                    <User className="w-3 h-3" style={{ color: "var(--color-text-dim)" }} />
                  </div>
                ) : (
                  <div className="w-5 h-5 rounded flex items-center justify-center"
                    style={{ background: "var(--color-accent)" }}>
                    <Bot className="w-3 h-3 text-white" />
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs leading-relaxed" style={{ color: "var(--color-text)" }}>
                  {msg.content}
                </p>

                {/* Apply policy button (for assistant messages with policy) */}
                {msg.role === "assistant" && msg.policySnapshot && (
                  <button
                    onClick={() => applyPolicy(i)}
                    disabled={msg.policyApplied || disabled}
                    className="flex items-center gap-1.5 text-[10px] font-medium px-2.5 py-1.5 rounded mt-2 transition-colors"
                    style={{
                      background: msg.policyApplied ? "rgba(22,163,74,0.1)" : "var(--color-surface-2)",
                      color: msg.policyApplied ? "var(--color-compliant)" : "var(--color-accent)",
                      border: `1px solid ${msg.policyApplied ? "var(--color-compliant)" : "var(--color-border)"}`,
                    }}
                  >
                    {msg.policyApplied ? (
                      <><Check className="w-3 h-3" /> Applied to Policy tab</>
                    ) : (
                      <><Sparkles className="w-3 h-3" /> Apply this policy</>
                    )}
                  </button>
                )}

                {/* Suggestions */}
                {msg.suggestions && msg.suggestions.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {msg.suggestions.map((s, si) => (
                      <button
                        key={si}
                        onClick={() => sendMessage(s)}
                        disabled={loading}
                        className="text-[10px] px-2 py-1 rounded border hover:bg-black/5 transition-colors"
                        style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div className="flex gap-2 animate-slide-up">
            <div className="w-5 h-5 rounded flex items-center justify-center shrink-0"
              style={{ background: "var(--color-accent)" }}>
              <Bot className="w-3 h-3 text-white" />
            </div>
            <div className="flex items-center gap-1.5 py-1">
              <Loader2 className="w-3 h-3 animate-spin" style={{ color: "var(--color-text-dim)" }} />
              <span className="text-[10px]" style={{ color: "var(--color-text-dim)" }}>
                Polly is thinking...
              </span>
            </div>
          </div>
        )}

        <div ref={scrollRef} />
      </div>

      {/* Input bar */}
      <div className="shrink-0 p-3 border-t" style={{ borderColor: "var(--color-border)" }}>
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
            disabled={loading || disabled}
            placeholder="Describe what you want to monitor..."
            className="flex-1 text-xs px-3 py-2 rounded border bg-transparent placeholder:text-gray-400"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading || disabled}
            className="px-3 py-2 rounded text-white transition-colors"
            style={{
              background: input.trim() && !loading ? "var(--color-accent)" : "var(--color-border)",
            }}
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
