import { Routes, Route, NavLink } from "react-router-dom";
import DocumentsPage from "@/pages/DocumentsPage";
import LawsPage from "@/pages/LawsPage";
import ChecklistPage from "@/pages/ChecklistPage";
import HistoryPage from "@/pages/HistoryPage";
import ChatPage from "@/pages/ChatPage";
import LoginPage from "@/pages/LoginPage";
import SignupPage from "@/pages/SignupPage";
import ProtectedRoute from "@/components/ProtectedRoute";
import { ChatProvider } from "@/context/ChatContext";
import { AuthProvider, useAuth } from "@/context/AuthContext";

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

function Header() {
  const { isAuthenticated, organization, logout } = useAuth();

  return (
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
      {isAuthenticated && (
        <>
          <NavLink to="/" end style={({ isActive }) => navStyle(isActive)}>
            문서
          </NavLink>
          <NavLink to="/laws" style={({ isActive }) => navStyle(isActive)}>
            법령
          </NavLink>
          <NavLink to="/checklist" style={({ isActive }) => navStyle(isActive)}>
            체크리스트
          </NavLink>
          <NavLink to="/history" style={({ isActive }) => navStyle(isActive)}>
            히스토리
          </NavLink>
          <NavLink to="/chat" style={({ isActive }) => navStyle(isActive)}>
            AI 도우미
          </NavLink>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.9rem" }}>
            {organization && (
              <span style={{ fontSize: "0.82rem", color: "#6b7280", fontWeight: 600 }}>
                {organization.name}
              </span>
            )}
            <button
              onClick={logout}
              style={{
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "#6b7280",
                background: "none",
                border: "1px solid #d1d5db",
                borderRadius: 6,
                padding: "0.4rem 0.8rem",
                cursor: "pointer",
              }}
            >
              로그아웃
            </button>
          </div>
        </>
      )}
    </header>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <div style={{ fontFamily: "system-ui, sans-serif", minHeight: "100vh", background: "#fafafa" }}>
        <Header />

        <main>
          <ChatProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignupPage />} />
              <Route path="/" element={<ProtectedRoute><DocumentsPage /></ProtectedRoute>} />
              <Route path="/laws" element={<ProtectedRoute><LawsPage /></ProtectedRoute>} />
              <Route path="/checklist" element={<ProtectedRoute><ChecklistPage /></ProtectedRoute>} />
              <Route path="/history" element={<ProtectedRoute><HistoryPage /></ProtectedRoute>} />
              <Route path="/history/:periodId" element={<ProtectedRoute><ChecklistPage /></ProtectedRoute>} />
              <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
            </Routes>
          </ChatProvider>
        </main>
      </div>
    </AuthProvider>
  );
}
