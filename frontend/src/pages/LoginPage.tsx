import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      navigate("/checklist");
    } catch {
      setError("이메일 또는 비밀번호가 올바르지 않습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "4rem 1rem" }}>
      <form
        onSubmit={handleSubmit}
        style={{
          width: "100%",
          maxWidth: 360,
          display: "flex",
          flexDirection: "column",
          gap: "0.9rem",
          padding: "2rem",
          borderRadius: 12,
          border: "1px solid #e5e7eb",
          background: "white",
        }}
      >
        <h1 style={{ fontSize: "1.3rem", fontWeight: 700, marginBottom: "0.25rem" }}>로그인</h1>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>
          이메일
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ padding: "0.55rem 0.7rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>
          비밀번호
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ padding: "0.55rem 0.7rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
          />
        </label>

        {error && <div style={{ fontSize: "0.8rem", color: "#dc2626" }}>{error}</div>}

        <button
          type="submit"
          disabled={isSubmitting}
          style={{
            padding: "0.6rem 1rem",
            borderRadius: 6,
            border: "none",
            background: isSubmitting ? "#93c5fd" : "#2563eb",
            color: "white",
            fontSize: "0.9rem",
            fontWeight: 600,
            cursor: isSubmitting ? "default" : "pointer",
          }}
        >
          {isSubmitting ? "로그인 중..." : "로그인"}
        </button>

        <div style={{ fontSize: "0.8rem", color: "#6b7280", textAlign: "center" }}>
          계정이 없으신가요? <Link to="/signup" style={{ color: "#2563eb", fontWeight: 600 }}>회원가입</Link>
        </div>
      </form>
    </div>
  );
}
