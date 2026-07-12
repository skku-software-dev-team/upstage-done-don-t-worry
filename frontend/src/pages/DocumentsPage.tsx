import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { documentsApi } from "@/api/compliance";

const DOC_TYPES = ["ISMS-P", "CSAP", "ISO27001", "KISA", "기타"];

type UploadStatus = "idle" | "creating" | "parsing" | "success" | "error";

export default function DocumentsPage() {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [docType, setDocType] = useState(DOC_TYPES[0]);
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [message, setMessage] = useState("");

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list,
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
    setDocType(DOC_TYPES[0]);
    setFile(null);
    setStatus("idle");
    setMessage("");
    setShowForm(false);
  };

  const handleSubmit = async () => {
    if (!name.trim() || !file) return;
    try {
      setStatus("creating");
      const doc = await documentsApi.create({ name: name.trim(), doc_type: docType });

      setStatus("parsing");
      const formData = new FormData();
      formData.append("file", file);
      const result = await documentsApi.upload(doc.id, formData);

      setStatus("success");
      setMessage(`파싱 완료! 조항 ${result.pages ?? "?"}개가 저장되었습니다.`);
      qc.invalidateQueries({ queryKey: ["documents"] });
      setTimeout(resetForm, 3000);
    } catch {
      setStatus("error");
      setMessage("업로드 중 오류가 발생했습니다.");
    }
  };

  const isUploading = status === "creating" || status === "parsing";

  const statusLabel: Record<UploadStatus, string> = {
    idle: "파싱 시작",
    creating: "⏳ 문서 생성 중...",
    parsing: "⚙️ Document AI 파싱 중...",
    success: "✅ 완료",
    error: "다시 시도",
  };

  return (
    <div style={{ padding: "2rem", maxWidth: 900, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0 }}>문서 목록</h1>
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
          {showForm ? "✕ 닫기" : "+ 새 문서 추가"}
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
          {/* Name + Type */}
          <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
            <div style={{ flex: 2 }}>
              <label style={labelStyle}>문서명</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="예) ISMS-P 2024 가이드라인"
                style={inputStyle}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>문서 유형</label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                style={{ ...inputStyle, background: "white", cursor: "pointer" }}
              >
                {DOC_TYPES.map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
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
                <span>{status === "creating" ? "문서 생성" : "Document AI 파싱"}</span>
                <span>{status === "creating" ? "1 / 2" : "2 / 2"}</span>
              </div>
              <div style={{ height: 6, background: "#e5e7eb", borderRadius: 99, overflow: "hidden" }}>
                <div style={{
                  height: "100%",
                  width: status === "creating" ? "30%" : "80%",
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
            disabled={!name.trim() || !file || isUploading || status === "success"}
            style={{
              width: "100%",
              padding: "0.75rem",
              borderRadius: 8,
              background: status === "success" ? "#10b981" : isUploading ? "#93c5fd" : "#2563eb",
              color: "white",
              border: "none",
              fontWeight: 600,
              fontSize: "0.95rem",
              cursor: (!name.trim() || !file || isUploading || status === "success") ? "not-allowed" : "pointer",
              opacity: !name.trim() || !file ? 0.5 : 1,
              transition: "background 0.2s",
            }}
          >
            {statusLabel[status]}
          </button>
        </div>
      )}

      {/* Document list */}
      {isLoading ? (
        <p style={{ color: "#6b7280" }}>로딩 중...</p>
      ) : docs.length === 0 ? (
        <div style={{ textAlign: "center", padding: "4rem 0", color: "#9ca3af" }}>
          <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>📋</div>
          <div>등록된 문서가 없습니다.</div>
          <div style={{ fontSize: "0.875rem", marginTop: 4 }}>위 버튼으로 첫 번째 문서를 추가해보세요.</div>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left", color: "#6b7280" }}>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>문서명</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>유형</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>등록일</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "0.75rem 1rem", fontWeight: 500, color: "#111827" }}>{doc.name}</td>
                <td style={{ padding: "0.75rem 1rem" }}>
                  <span style={{
                    padding: "0.2rem 0.6rem",
                    borderRadius: 4,
                    background: "#eff6ff",
                    color: "#1d4ed8",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                  }}>
                    {doc.doc_type}
                  </span>
                </td>
                <td style={{ padding: "0.75rem 1rem", color: "#6b7280" }}>
                  {new Date(doc.created_at).toLocaleDateString("ko-KR")}
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
