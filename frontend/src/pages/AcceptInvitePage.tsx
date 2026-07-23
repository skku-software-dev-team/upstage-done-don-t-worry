import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { authApi, type AuthDepartment } from "@/api/auth";

export default function AcceptInvitePage() {
  const { token } = useParams<{ token: string }>();
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [departments, setDepartments] = useState<AuthDepartment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    authApi.departments().then(setDepartments).catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await acceptInvite(token, email, password, name, departmentId || undefined);
      navigate("/checklist");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "초대 수락에 실패했습니다. 다시 시도하세요.");
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
        <h1 style={{ fontSize: "1.3rem", fontWeight: 700, marginBottom: "0.25rem" }}>초대 수락</h1>
        <p style={{ fontSize: "0.85rem", color: "#6b7280", marginTop: "-0.5rem" }}>
          이메일과 비밀번호를 설정해 팀에 합류하세요.
        </p>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>
          이름
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ padding: "0.55rem 0.7rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.9rem" }}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>
          부서
          <select
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
            style={{ padding: "0.55rem 0.7rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.9rem", background: "white" }}
          >
            <option value="">선택 안 함</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
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
          {isSubmitting ? "합류 중..." : "합류하기"}
        </button>
      </form>
    </div>
  );
}
