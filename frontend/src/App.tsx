import { Routes, Route, NavLink } from "react-router-dom";
import DocumentsPage from "@/pages/DocumentsPage";
import LawsPage from "@/pages/LawsPage";
import ChecklistPage from "@/pages/ChecklistPage";
import ChatPage from "@/pages/ChatPage";
import { ChatProvider } from "@/context/ChatContext";

const navStyle = (isActive: boolean): React.CSSProperties => ({
  padding: "0.5rem 1rem",
  borderRadius: 6,
  textDecoration: "none",
  fontWeight: 500,
  fontSize: "0.9rem",
  color: isActive ? "white" : "#374151",
  background: isActive ? "#2563eb" : "transparent",
  transition: "background 0.15s",
});

export default function App() {
  return (
    <div style={{ fontFamily: "system-ui, sans-serif", minHeight: "100vh", background: "#fafafa" }}>
      <header
        style={{
          height: 64,
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0 2rem",
          borderBottom: "1px solid #e5e7eb",
          background: "white",
          position: "sticky",
          top: 0,
          zIndex: 10,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: "1.1rem", marginRight: "1.5rem", color: "#111827" }}>
          Compliance Checker
        </span>
        <NavLink to="/" end style={({ isActive }) => navStyle(isActive)}>
          문서
        </NavLink>
        <NavLink to="/laws" style={({ isActive }) => navStyle(isActive)}>
          법령
        </NavLink>
        <NavLink to="/checklist" style={({ isActive }) => navStyle(isActive)}>
          체크리스트
        </NavLink>
        <NavLink to="/chat" style={({ isActive }) => navStyle(isActive)}>
          AI 도우미
        </NavLink>
      </header>

      <main>
        <ChatProvider>
          <Routes>
            <Route path="/" element={<DocumentsPage />} />
            <Route path="/laws" element={<LawsPage />} />
            <Route path="/checklist" element={<ChecklistPage />} />
            <Route path="/chat" element={<ChatPage />} />
          </Routes>
        </ChatProvider>
      </main>
    </div>
  );
}
