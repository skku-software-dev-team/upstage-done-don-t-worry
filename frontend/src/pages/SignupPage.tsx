import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function SignupPage() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await signup(orgName, email, password);
      navigate("/checklist");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "가입에 실패했습니다. 다시 시도하세요.");
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
        <h1 style={{ fontSize: "1.3rem", fontWeight: 700, marginBottom: "0.25rem" }}>회원가입</h1>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>
          조직명
          <input
            type="text"
            required
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            placeholder="예: 성균소프트웨어"
            style={{ padding: "0.55rem 0.7rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
          />
        </label>

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
            minLength={8}
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
          {isSubmitting ? "가입 중..." : "회원가입"}
        </button>

        <div style={{ fontSize: "0.8rem", color: "#6b7280", textAlign: "center" }}>
          이미 계정이 있으신가요? <Link to="/login" style={{ color: "#2563eb", fontWeight: 600 }}>로그인</Link>
        </div>
      </form>
    </div>
  );
}
