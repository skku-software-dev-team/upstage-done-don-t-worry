import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { lawsApi, withParseTimeoutRetry } from "@/api/compliance";

type UploadStatus = "idle" | "creating" | "parsing" | "linking" | "success" | "error";

export default function LawsPage() {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [enactedDate, setEnactedDate] = useState("");
  const [supersedesId, setSupersedesId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [message, setMessage] = useState("");

  const { data: laws = [], isLoading } = useQuery({
    queryKey: ["laws"],
    queryFn: lawsApi.list,
  });

  const activeLaws = laws.filter((l) => l.is_active);

  const { mutate: deleteLaw } = useMutation({
    mutationFn: (lawId: string) => lawsApi.delete(lawId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["laws"] }),
  });

  const { mutate: setActive } = useMutation({
    mutationFn: ({ lawId, isActive }: { lawId: string; isActive: boolean }) =>
      lawsApi.setActive(lawId, isActive),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["laws"] }),
  });

  const handleFileSelect = (f: File) => {
    if (f.type !== "application/pdf") {
      setMessage("PDF 파일만 업로드할 수 있습니다.");
      setStatus("error");
      return;
    }
    setFile(f);
    setStatus("idle");
    setMessage("");
    if (!name) setName(f.name.replace(/\.pdf$/i, ""));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) handleFileSelect(dropped);
  };

  const resetForm = () => {
    setName("");
    setVersion("");
    setEnactedDate("");
    setSupersedesId("");
    setFile(null);
    setStatus("idle");
    setMessage("");
    setShowForm(false);
  };

  const handleSubmit = async () => {
    if (!name.trim() || !version.trim() || !file) return;
    try {
      setStatus("creating");
      const law = await lawsApi.create({
        name: name.trim(),
        version: version.trim(),
        enacted_date: enactedDate || null,
        supersedes_law_id: supersedesId || undefined,
      });

      setStatus("parsing");
      const formData = new FormData();
      formData.append("file", file);
      setStatus("linking");
      const result = await withParseTimeoutRetry(() => lawsApi.upload(law.id, formData));

      setStatus("success");
      setMessage(
        `완료! 조문 ${result.articles ?? "?"}개, 연결된 조항 ${result.linked_clauses ?? "?"}개`
      );
      qc.invalidateQueries({ queryKey: ["laws"] });
      setTimeout(resetForm, 4000);
    } catch {
      setStatus("error");
      setMessage("업로드 중 오류가 발생했습니다.");
    }
  };

  const isUploading = status === "creating" || status === "parsing" || status === "linking";

  const statusLabel: Record<UploadStatus, string> = {
    idle: "파싱 시작",
    creating: "⏳ 법률 등록 중...",
    parsing: "⚙️ Document AI 파싱 중...",
    linking: "🔗 관련 조항 연결 중...",
    success: "✅ 완료",
    error: "다시 시도",
  };

  return (
    <div style={{ padding: "2rem", maxWidth: 900, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0 }}>법령 목록</h1>
        <button
          onClick={() => { setShowForm(!showForm); setStatus("idle"); setMessage(""); }}
          style={{
            padding: "0.5rem 1.25rem",
            borderRadius: 8,
            background: showForm ? "#f3f4f6" : "#2563eb",
            color: showForm ? "#374151" : "white",
            border: "none",
            fontWeight: 600,
            cursor: "pointer",
            fontSize: "0.9rem",
          }}
        >
          {showForm ? "✕ 닫기" : "+ 새 법령 추가"}
        </button>
      </div>

      {/* Upload form */}
      {showForm && (
        <div style={{
          background: "white",
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: "1.5rem",
          marginBottom: "2rem",
          boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
        }}>
          {/* Name + Version + Date */}
          <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
            <div style={{ flex: 2 }}>
              <label style={labelStyle}>법률명</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="예) 개인정보 보호법"
                style={inputStyle}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>버전(시행 회차 등)</label>
              <input
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="예) 2025.10 개정"
                style={inputStyle}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>시행일 (선택)</label>
              <input
                type="date"
                value={enactedDate}
                onChange={(e) => setEnactedDate(e.target.value)}
                style={inputStyle}
              />
            </div>
          </div>

          {/* Supersedes (optional) */}
          <div style={{ marginBottom: "1rem" }}>
            <label style={labelStyle}>대체할 기존 법령 (개정된 경우, 선택)</label>
            <select
              value={supersedesId}
              onChange={(e) => setSupersedesId(e.target.value)}
              style={inputStyle}
            >
              <option value="">없음 (신규 법령)</option>
              {activeLaws.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.version})
                </option>
              ))}
            </select>
          </div>

          {/* Drop zone */}
          <div
            onClick={() => !isUploading && fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            style={{
              border: `2px dashed ${isDragging ? "#2563eb" : file ? "#10b981" : "#d1d5db"}`,
              borderRadius: 10,
              padding: "2.5rem 1.5rem",
              textAlign: "center",
              cursor: isUploading ? "not-allowed" : "pointer",
              background: isDragging ? "#eff6ff" : file ? "#f0fdf4" : "#fafafa",
              transition: "border-color 0.15s, background 0.15s",
              marginBottom: "1rem",
              userSelect: "none",
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileSelect(f); }}
            />
            {file ? (
              <>
                <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>📄</div>
                <div style={{ fontWeight: 600, color: "#059669", marginBottom: 4 }}>{file.name}</div>
                <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                  {!isUploading && <> · <span style={{ textDecoration: "underline" }}>다시 선택</span></>}
                </div>
              </>
            ) : (
              <>
                <div style={{ fontSize: "2.5rem", marginBottom: "0.75rem" }}>📂</div>
                <div style={{ color: "#374151", fontWeight: 500, marginBottom: 4 }}>
                  PDF 파일을 드래그하거나 클릭해서 선택
                </div>
                <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>PDF 형식만 지원</div>
              </>
            )}
          </div>

          {/* Status message */}
          {message && (
            <div style={{
              padding: "0.75rem 1rem",
              borderRadius: 8,
              background: status === "error" ? "#fef2f2" : "#f0fdf4",
              color: status === "error" ? "#dc2626" : "#059669",
              fontSize: "0.875rem",
              marginBottom: "1rem",
              fontWeight: 500,
            }}>
              {message}
            </div>
          )}

          {/* Progress bar while parsing */}
          {isUploading && (
            <div style={{ marginBottom: "1rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "#6b7280", marginBottom: 6 }}>
                <span>
                  {status === "creating" ? "법률 등록" : status === "parsing" ? "Document AI 파싱" : "조항 연결"}
                </span>
                <span>
                  {status === "creating" ? "1 / 3" : status === "parsing" ? "2 / 3" : "3 / 3"}
                </span>
              </div>
              <div style={{ height: 6, background: "#e5e7eb", borderRadius: 99, overflow: "hidden" }}>
                <div style={{
                  height: "100%",
                  width: status === "creating" ? "20%" : status === "parsing" ? "55%" : "90%",
                  background: "#2563eb",
                  borderRadius: 99,
                  transition: "width 0.4s ease",
                }} />
              </div>
            </div>
          )}

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={!name.trim() || !version.trim() || !file || isUploading || status === "success"}
            style={{
              width: "100%",
              padding: "0.75rem",
              borderRadius: 8,
              background: status === "success" ? "#10b981" : isUploading ? "#93c5fd" : "#2563eb",
              color: "white",
              border: "none",
              fontWeight: 600,
              fontSize: "0.95rem",
              cursor: (!name.trim() || !version.trim() || !file || isUploading || status === "success") ? "not-allowed" : "pointer",
              opacity: !name.trim() || !version.trim() || !file ? 0.5 : 1,
              transition: "background 0.2s",
            }}
          >
            {statusLabel[status]}
          </button>
        </div>
      )}

      {/* Law list */}
      {isLoading ? (
        <p style={{ color: "#6b7280" }}>로딩 중...</p>
      ) : laws.length === 0 ? (
        <div style={{ textAlign: "center", padding: "4rem 0", color: "#9ca3af" }}>
          <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>⚖️</div>
          <div>등록된 법령이 없습니다.</div>
          <div style={{ fontSize: "0.875rem", marginTop: 4 }}>위 버튼으로 첫 번째 법령을 추가해보세요.</div>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left", color: "#6b7280" }}>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>법률명</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>버전</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>시행일</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>상태</th>
              <th style={{ padding: "0.75rem 1rem", width: 60 }} />
            </tr>
          </thead>
          <tbody>
            {laws.map((law) => (
              <tr key={law.id} style={{ borderBottom: "1px solid #f3f4f6", opacity: law.is_active ? 1 : 0.6 }}>
                <td style={{ padding: "0.75rem 1rem", fontWeight: 500, color: "#111827" }}>{law.name}</td>
                <td style={{ padding: "0.75rem 1rem" }}>
                  <span style={{
                    padding: "0.2rem 0.6rem",
                    borderRadius: 4,
                    background: "#eff6ff",
                    color: "#1d4ed8",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                  }}>
                    {law.version}
                  </span>
                </td>
                <td style={{ padding: "0.75rem 1rem", color: "#6b7280" }}>
                  {law.enacted_date ? new Date(law.enacted_date).toLocaleDateString("ko-KR") : "-"}
                </td>
                <td style={{ padding: "0.75rem 1rem" }}>
                  <button
                    onClick={() => setActive({ lawId: law.id, isActive: !law.is_active })}
                    title={law.is_active ? "구버전으로 표시" : "다시 활성화"}
                    style={{
                      padding: "0.2rem 0.6rem",
                      borderRadius: 999,
                      border: "none",
                      cursor: "pointer",
                      fontSize: "0.78rem",
                      fontWeight: 600,
                      background: law.is_active ? "#dcfce7" : "#f3f4f6",
                      color: law.is_active ? "#16a34a" : "#6b7280",
                    }}
                  >
                    {law.is_active ? "활성" : "구버전"}
                  </button>
                </td>
                <td style={{ padding: "0.75rem 1rem" }}>
                  <button
                    onClick={() => {
                      if (window.confirm(`"${law.name}" 법령을 삭제하시겠습니까?`)) {
                        deleteLaw(law.id);
                      }
                    }}
                    title="삭제"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "#9ca3af",
                      fontSize: "1rem",
                      padding: "0.25rem",
                      borderRadius: 4,
                      lineHeight: 1,
                    }}
                    onMouseOver={(e) => (e.currentTarget.style.color = "#dc2626")}
                    onMouseOut={(e) => (e.currentTarget.style.color = "#9ca3af")}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "0.8rem",
  fontWeight: 600,
  color: "#374151",
  marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.6rem 0.75rem",
  borderRadius: 6,
  border: "1px solid #d1d5db",
  fontSize: "0.9rem",
  boxSizing: "border-box",
  outline: "none",
};
