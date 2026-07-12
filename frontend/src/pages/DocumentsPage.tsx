import { useQuery } from "@tanstack/react-query";
import { documentsApi } from "@/api/compliance";

export default function DocumentsPage() {
  const { data: docs = [], isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list,
  });

  if (isLoading) return <p style={{ padding: "2rem" }}>로딩 중...</p>;

  return (
    <div style={{ padding: "2rem", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1.5rem" }}>문서 목록</h1>
      {docs.length === 0 ? (
        <p style={{ color: "#6b7280" }}>등록된 문서가 없습니다.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "0.75rem 1rem" }}>문서명</th>
              <th style={{ padding: "0.75rem 1rem" }}>유형</th>
              <th style={{ padding: "0.75rem 1rem" }}>버전</th>
              <th style={{ padding: "0.75rem 1rem" }}>등록일</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "0.75rem 1rem", fontWeight: 500 }}>{doc.name}</td>
                <td style={{ padding: "0.75rem 1rem", color: "#6b7280" }}>{doc.doc_type}</td>
                <td style={{ padding: "0.75rem 1rem", color: "#6b7280" }}>{doc.version}</td>
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
