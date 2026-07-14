import { createContext, useContext, useState, type ReactNode } from "react";
import type { ChatSource } from "@/api/compliance";

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
}

interface ChatContextValue {
  messages: Message[];
  addMessage: (m: Message) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

// Held here (above <Routes>) instead of in ChatPage's own state, so
// navigating to another tab and back doesn't unmount-and-lose the history —
// only this provider's parent (App) would reset it, and that never remounts.
export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const addMessage = (m: Message) => setMessages((prev) => [...prev, m]);
  return <ChatContext.Provider value={{ messages, addMessage }}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
