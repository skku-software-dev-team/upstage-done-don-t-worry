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

  const { data: items = [] } = useQuery({
    queryKey: ["canonical-items"],
    queryFn: checklistApi.list,
  });

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

  return (
    <div style={{ padding: "2rem", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1.5rem" }}>
        체크리스트
      </h1>
      {items.length === 0 ? (
        <p style={{ color: "#6b7280" }}>항목이 없습니다. 문서를 먼저 업로드하세요.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "0.75rem 1rem" }}>항목</th>
              <th style={{ padding: "0.75rem 1rem", width: 180 }}>상태</th>
              <th style={{ padding: "0.75rem 1rem", width: 140 }}>Jira</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const cur = statusMap.get(item.id);
              const curStatus: Status = (cur?.status as Status) ?? "not_started";
              return (
                <tr key={item.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "0.75rem 1rem" }}>{item.merged_title}</td>
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
                  <td style={{ padding: "0.75rem 1rem", color: "#6b7280", fontSize: "0.8rem" }}>
                    {cur?.jira_key ?? "-"}
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
