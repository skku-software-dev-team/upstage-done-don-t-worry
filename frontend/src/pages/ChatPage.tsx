import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatApi, type ChatSource } from "@/api/compliance";
import { useChat } from "@/context/ChatContext";

function sourceLabel(s: ChatSource): string {
  return [s.doc_type, s.clause_no, s.title].filter(Boolean).join(" ") || s.id.slice(0, 8);
}

// Inline style overrides for markdown elements — this project has no CSS
// files, everything is styled via the `style` prop, so react-markdown's
// default unstyled tags need explicit component overrides here too.
const markdownComponents = {
  p: (p: React.ComponentProps<"p">) => <p style={{ margin: "0 0 0.6em" }} {...p} />,
  h1: (p: React.ComponentProps<"h1">) => <h1 style={{ fontSize: "1.15rem", fontWeight: 700, margin: "0.8em 0 0.4em" }} {...p} />,
  h2: (p: React.ComponentProps<"h2">) => <h2 style={{ fontSize: "1.05rem", fontWeight: 700, margin: "0.8em 0 0.4em" }} {...p} />,
  h3: (p: React.ComponentProps<"h3">) => <h3 style={{ fontSize: "0.98rem", fontWeight: 700, margin: "0.8em 0 0.3em" }} {...p} />,
  ul: (p: React.ComponentProps<"ul">) => <ul style={{ margin: "0 0 0.6em", paddingLeft: "1.3em" }} {...p} />,
  ol: (p: React.ComponentProps<"ol">) => <ol style={{ margin: "0 0 0.6em", paddingLeft: "1.3em" }} {...p} />,
  li: (p: React.ComponentProps<"li">) => <li style={{ margin: "0.15em 0" }} {...p} />,
  strong: (p: React.ComponentProps<"strong">) => <strong style={{ fontWeight: 700 }} {...p} />,
  hr: () => <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "0.8em 0" }} />,
  code: (p: React.ComponentProps<"code">) => (
    <code style={{ background: "#e5e7eb", borderRadius: 4, padding: "0.1em 0.35em", fontSize: "0.85em" }} {...p} />
  ),
  a: (p: React.ComponentProps<"a">) => <a style={{ color: "#2563eb" }} target="_blank" rel="noreferrer" {...p} />,
  table: (p: React.ComponentProps<"table">) => (
    <div style={{ overflowX: "auto", margin: "0.4em 0" }}>
      <table style={{ borderCollapse: "collapse", fontSize: "0.85em", width: "100%" }} {...p} />
    </div>
  ),
  th: (p: React.ComponentProps<"th">) => (
    <th style={{ border: "1px solid #d1d5db", padding: "0.35em 0.6em", background: "#f3f4f6", textAlign: "left" }} {...p} />
  ),
  td: (p: React.ComponentProps<"td">) => (
    <td style={{ border: "1px solid #d1d5db", padding: "0.35em 0.6em" }} {...p} />
  ),
};

export default function ChatPage() {
  const { messages, addMessage } = useChat();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    addMessage({ role: "user", content: text });
    setInput("");
    setLoading(true);

    try {
      const res = await chatApi.send(text);
      addMessage({ role: "assistant", content: res.answer, sources: res.sources });
    } catch {
      addMessage({ role: "assistant", content: "오류가 발생했습니다. 잠시 후 다시 시도해주세요." });
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
                whiteSpace: m.role === "user" ? "pre-wrap" : "normal",
                lineHeight: 1.6,
              }}
            >
              {m.role === "assistant" ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {m.content}
                </ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
            {m.sources && m.sources.length > 0 && (
              <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", color: "#6b7280" }}>
                참고: {m.sources.map(sourceLabel).join(", ")}
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
