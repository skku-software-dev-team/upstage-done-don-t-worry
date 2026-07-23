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

// Exported so AuthContext can clear it on logout without needing a React
// context reference (the logout button lives outside <ChatProvider>).
export const CHAT_STORAGE_KEY = "chat_messages";

function loadStoredMessages(): Message[] {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Message[]) : [];
  } catch {
    return [];
  }
}

// Held here (above <Routes>) instead of in ChatPage's own state, so
// navigating to another tab and back doesn't unmount-and-lose the history —
// only this provider's parent (App) would reset it, and that never remounts.
// Also persisted to localStorage so a page refresh doesn't lose it either;
// it's only cleared explicitly on logout (see AuthContext.logout).
export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>(loadStoredMessages);
  const addMessage = (m: Message) =>
    setMessages((prev) => {
      const next = [...prev, m];
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  return <ChatContext.Provider value={{ messages, addMessage }}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
