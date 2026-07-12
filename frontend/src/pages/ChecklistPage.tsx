import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { checklistApi, type OrgStatus } from "@/api/compliance";

const DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001";

const STATUS_OPTIONS = ["not_started", "in_progress", "completed", "not_applicable"] as const;
type Status = (typeof STATUS_OPTIONS)[number];

const statusLabel: Record<Status, string> = {
  not_started: "미시작",
  in_progress: "진행중",
  completed: "완료",
  not_applicable: "해당없음",
};

const statusColor: Record<Status, string> = {
  not_started: "#e5e7eb",
  in_progress: "#fef08a",
  completed: "#bbf7d0",
  not_applicable: "#f3f4f6",
};

export default function ChecklistPage() {
  const qc = useQueryClient();
  const [orgId] = useState(DEFAULT_ORG_ID);
  const [docType, setDocType] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);

  // Fetch all items once; derive chips + filter client-side (small list)
  const { data: allItems = [] } = useQuery({
    queryKey: ["checklist-items"],
    queryFn: () => checklistApi.list(),
  });

  // Distinct document types present in the items (e.g. ISMS-P, CSAP)
  const presentDocTypes = Array.from(
    new Set(allItems.map((i) => i.doc_type).filter((d): d is string => !!d)),
  ).sort((a, b) => a.localeCompare(b, "ko"));

  // Only categories that actually have items become filter chips
  const presentCategories = Array.from(
    new Map(
      allItems
        .filter((i) => i.category_id && i.category_name)
        .map((i) => [i.category_id!, i.category_name!]),
    ).entries(),
  ).sort((a, b) => a[1].localeCompare(b[1], "ko"));

  // Client-side filter by doc type and/or category
  const items = allItems.filter(
    (i) =>
      (docType === null || i.doc_type === docType) &&
      (categoryId === null || i.category_id === categoryId),
  );

  const { data: statuses = [] } = useQuery({
    queryKey: ["org-status", orgId],
    queryFn: () => checklistApi.orgStatus(orgId),
  });

  const statusMap = new Map<string, OrgStatus>(statuses.map((s) => [s.canonical_id, s]));

  const { mutate: updateStatus } = useMutation({
    mutationFn: ({ canonicalId, status }: { canonicalId: string; status: Status }) =>
      checklistApi.updateStatus(orgId, canonicalId, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-status", orgId] }),
  });

  const chipStyle = (active: boolean, accent = "#2563eb"): React.CSSProperties => ({
    padding: "0.35rem 0.85rem",
    borderRadius: 999,
    border: `1px solid ${active ? accent : "#d1d5db"}`,
    background: active ? accent : "white",
    color: active ? "white" : "#374151",
    fontSize: "0.8rem",
    fontWeight: 600,
    cursor: "pointer",
    transition: "all 0.15s",
  });

  // Count helper respecting the *other* active filter
  const countForDoc = (dt: string | null) =>
    allItems.filter(
      (i) => (dt === null || i.doc_type === dt) && (categoryId === null || i.category_id === categoryId),
    ).length;
  const countForCat = (cid: string | null) =>
    allItems.filter(
      (i) => (docType === null || i.doc_type === docType) && (cid === null || i.category_id === cid),
    ).length;

  return (
    <div style={{ padding: "2rem", maxWidth: 1000, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1rem" }}>체크리스트</h1>

      {/* Document (framework) filter — ISMS-P, CSAP, ... */}
      {presentDocTypes.length > 0 && (
        <div style={{ marginBottom: "0.75rem" }}>
          <div style={{ fontSize: "0.72rem", color: "#9ca3af", fontWeight: 600, marginBottom: 6 }}>
            문서 / 인증
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            <button style={chipStyle(docType === null)} onClick={() => setDocType(null)}>
              전체 ({countForDoc(null)})
            </button>
            {presentDocTypes.map((dt) => (
              <button key={dt} style={chipStyle(docType === dt)} onClick={() => setDocType(dt)}>
                {dt} ({countForDoc(dt)})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Category filter — only categories that have items */}
      {presentCategories.length > 0 && (
        <div style={{ marginBottom: "1.5rem" }}>
          <div style={{ fontSize: "0.72rem", color: "#9ca3af", fontWeight: 600, marginBottom: 6 }}>
            카테고리
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            <button
              style={chipStyle(categoryId === null, "#059669")}
              onClick={() => setCategoryId(null)}
            >
              전체 ({countForCat(null)})
            </button>
            {presentCategories.map(([id, name]) => (
              <button
                key={id}
                style={chipStyle(categoryId === id, "#059669")}
                onClick={() => setCategoryId(id)}
              >
                {name} ({countForCat(id)})
              </button>
            ))}
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <p style={{ color: "#6b7280" }}>
          {allItems.length === 0
            ? "항목이 없습니다. 문서를 먼저 업로드하세요."
            : "선택한 필터에 해당하는 항목이 없습니다."}
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left", color: "#6b7280" }}>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>항목</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600, width: 130 }}>문서</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600, width: 150 }}>카테고리</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600, width: 130 }}>상태</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const cur = statusMap.get(item.id);
              const curStatus: Status = (cur?.status as Status) ?? "not_started";
              return (
                <tr key={item.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "0.75rem 1rem", color: "#111827" }}>{item.merged_title}</td>
                  <td style={{ padding: "0.75rem 1rem" }}>
                    {item.doc_type ? (
                      <span
                        title={item.document_name ?? ""}
                        style={{
                          padding: "0.2rem 0.6rem",
                          borderRadius: 4,
                          background: "#eef2ff",
                          color: "#4338ca",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.doc_type}
                      </span>
                    ) : (
                      <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>-</span>
                    )}
                  </td>
                  <td style={{ padding: "0.75rem 1rem" }}>
                    {item.category_name ? (
                      <span
                        style={{
                          padding: "0.2rem 0.6rem",
                          borderRadius: 4,
                          background: "#ecfdf5",
                          color: "#047857",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.category_name}
                      </span>
                    ) : (
                      <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>미분류</span>
                    )}
                  </td>
                  <td style={{ padding: "0.75rem 1rem" }}>
                    <select
                      value={curStatus}
                      onChange={(e) =>
                        updateStatus({ canonicalId: item.id, status: e.target.value as Status })
                      }
                      style={{
                        padding: "0.25rem 0.5rem",
                        borderRadius: 4,
                        border: "1px solid #d1d5db",
                        background: statusColor[curStatus],
                        cursor: "pointer",
                      }}
                    >
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s} value={s}>
                          {statusLabel[s]}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
