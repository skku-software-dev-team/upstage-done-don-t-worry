import { Link } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { checklistApi } from "@/api/compliance";

function formatDateRange(start: string | null, end: string | null): string | null {
  if (!start && !end) return null;
  if (start && end) return `${start} ~ ${end}`;
  return start ?? end;
}

export default function HistoryPage() {
  const { data: periods = [] } = useQuery({
    queryKey: ["checklist-periods"],
    queryFn: () => checklistApi.periods(),
  });

  const { data: allItems = [] } = useQuery({
    queryKey: ["checklist-items"],
    queryFn: () => checklistApi.list(),
  });

  const savedPeriods = periods.filter((p) => !p.is_current);

  const statusQueries = useQueries({
    queries: savedPeriods.map((p) => ({
      queryKey: ["org-status", p.id],
      queryFn: () => checklistApi.orgStatus(p.id),
    })),
  });

  return (
    <div style={{ padding: "2rem", maxWidth: 720, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.4rem" }}>히스토리</h1>
      <p style={{ fontSize: "0.85rem", color: "#6b7280", marginBottom: "1.5rem" }}>
        저장된 기간의 체크리스트 스냅샷을 조회하고 수정할 수 있습니다.
      </p>

      {savedPeriods.length === 0 ? (
        <p style={{ color: "#6b7280" }}>
          아직 저장된 히스토리가 없습니다. 체크리스트 화면에서 "히스토리로 저장"을 눌러보세요.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {savedPeriods.map((period, idx) => {
            const statuses = statusQueries[idx]?.data ?? [];
            const doneCount = statuses.filter((s) => s.status === "completed").length;
            const dateRange = formatDateRange(period.start_date, period.end_date);
            return (
              <Link
                key={period.id}
                to={`/history/${period.id}`}
                style={{
                  display: "block",
                  padding: "1rem 1.1rem",
                  borderRadius: 10,
                  border: "1px solid #e5e7eb",
                  background: "white",
                  textDecoration: "none",
                  color: "inherit",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 700, color: "#111827" }}>{period.label}</span>
                  <span
                    style={{
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      color: "#374151",
                      background: "#f3f4f6",
                      padding: "0.2rem 0.7rem",
                      borderRadius: 999,
                    }}
                  >
                    {doneCount}/{allItems.length} 완료
                  </span>
                </div>
                <div style={{ marginTop: "0.35rem", fontSize: "0.78rem", color: "#6b7280" }}>
                  {dateRange && <span>{dateRange} · </span>}
                  저장일 {new Date(period.created_at).toLocaleDateString("ko-KR")}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
