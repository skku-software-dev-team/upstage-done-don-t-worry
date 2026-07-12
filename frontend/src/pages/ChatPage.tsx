import { useState, useRef, useEffect } from "react";
import { chatApi, type Clause } from "@/api/compliance";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Clause[];
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    try {
      const res = await chatApi.send(text);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.answer, sources: res.sources },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "오류가 발생했습니다. 잠시 후 다시 시도해주세요." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 64px)", maxWidth: 800, margin: "0 auto", padding: "1rem" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1rem" }}>
        인증 도우미
      </h1>

      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "1rem", paddingBottom: "1rem" }}>
        {messages.length === 0 && (
          <p style={{ color: "#9ca3af", textAlign: "center", marginTop: "4rem" }}>
            ISMS-P, CSAP, ISO27001 관련 질문을 입력해주세요.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "80%",
            }}
          >
            <div
              style={{
                padding: "0.75rem 1rem",
                borderRadius: 12,
                background: m.role === "user" ? "#2563eb" : "#f3f4f6",
                color: m.role === "user" ? "white" : "#111827",
                whiteSpace: "pre-wrap",
                lineHeight: 1.6,
              }}
            >
              {m.content}
            </div>
            {m.sources && m.sources.length > 0 && (
              <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", color: "#6b7280" }}>
                참고: {m.sources.map((s) => s.clause_no ?? s.id.slice(0, 8)).join(", ")}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ alignSelf: "flex-start", padding: "0.75rem 1rem", background: "#f3f4f6", borderRadius: 12, color: "#6b7280" }}>
            답변 생성 중...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", gap: "0.5rem", paddingTop: "0.5rem", borderTop: "1px solid #e5e7eb" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          placeholder="질문을 입력하세요..."
          style={{
            flex: 1,
            padding: "0.75rem 1rem",
            borderRadius: 8,
            border: "1px solid #d1d5db",
            fontSize: "0.9rem",
            outline: "none",
          }}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          style={{
            padding: "0.75rem 1.5rem",
            borderRadius: 8,
            background: "#2563eb",
            color: "white",
            border: "none",
            fontWeight: 600,
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading || !input.trim() ? 0.6 : 1,
          }}
        >
          전송
        </button>
      </div>
    </div>
  );
}
