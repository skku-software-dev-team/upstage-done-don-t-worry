import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { checklistApi, type ChecklistItemDetail, type OrgStatus } from "@/api/compliance";
import { exportChecklistToExcel } from "@/lib/exportExcel";

const STATUS_OPTIONS = ["not_started", "in_progress", "completed", "not_applicable"] as const;
type Status = (typeof STATUS_OPTIONS)[number];

const statusLabel: Record<Status, string> = {
  not_started: "진행 예정",
  in_progress: "진행 중",
  completed: "진행 완료",
  not_applicable: "비활성화",
};

const PROGRESS_STATUSES = ["not_started", "in_progress", "completed"] as const;
type ProgressStatus = (typeof PROGRESS_STATUSES)[number];

const statusAccent: Record<ProgressStatus, string> = {
  not_started: "#6b7280",
  in_progress: "#ca8a04",
  completed: "#16a34a",
};

function progressBucketOf(status: Status): ProgressStatus | null {
  if (status === "not_applicable") return null;
  return status;
}

export default function ProgressPage() {
  const qc = useQueryClient();
  const { periodId } = useParams<{ periodId?: string }>();
  const [openStatusFor, setOpenStatusFor] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<ProgressStatus>>(new Set());
  // History snapshots start read-only — editing a past record shouldn't be
  // one accidental click away. Only relevant when viewing a saved period
  // (periodId set); the live/current view is always freely editable.
  const [editMode, setEditMode] = useState(false);
  const locked = Boolean(periodId) && !editMode;

  const toggleCollapse = (s: ProgressStatus) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });

  const {
    data: allItems = [],
    isLoading: itemsLoading,
    isError: itemsError,
  } = useQuery({
    queryKey: ["checklist-items"],
    queryFn: () => checklistApi.list(),
  });

  const {
    data: statuses = [],
    isLoading: statusesLoading,
    isError: statusesError,
  } = useQuery({
    queryKey: ["org-status", periodId ?? "current"],
    queryFn: () => checklistApi.orgStatus(periodId),
  });

  const { data: periods = [] } = useQuery({
    queryKey: ["checklist-periods"],
    queryFn: () => checklistApi.periods(),
  });
  const viewingPeriod = periodId ? periods.find((p) => p.id === periodId) : undefined;

  const isLoading = itemsLoading || statusesLoading;
  const isError = itemsError || statusesError;

  const statusMap = new Map<string, OrgStatus>(statuses.map((s) => [s.canonical_id, s]));
  const statusOf = (item: ChecklistItemDetail): Status =>
    (statusMap.get(item.id)?.status as Status) ?? "not_applicable";

  const { mutate: updateStatus } = useMutation({
    mutationFn: ({ canonicalId, status }: { canonicalId: string; status: Status }) =>
      checklistApi.updateStatus(canonicalId, status, undefined, periodId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-status", periodId ?? "current"] }),
  });

  const buckets: Record<ProgressStatus, ChecklistItemDetail[]> = {
    not_started: [],
    in_progress: [],
    completed: [],
  };
  let total = 0;
  for (const item of allItems) {
    const bucket = progressBucketOf(statusOf(item));
    if (bucket === null) continue;
    buckets[bucket].push(item);
    total++;
  }

  const completedCount = buckets.completed.length;
  const progressPct = total > 0 ? Math.round((completedCount / total) * 100) : 0;

  return (
    <div style={{ padding: "2rem", maxWidth: 1100, margin: "0 auto" }}>
      <style>{`
        @media print {
          .no-print { display: none !important; }
          body { background: white; }
          * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        }
      `}</style>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.75rem",
          marginBottom: "1.5rem",
          padding: periodId ? "0.75rem 1rem" : 0,
          borderRadius: periodId ? 10 : 0,
          background: periodId ? "#fffbeb" : "transparent",
          border: periodId ? "1px solid #fde68a" : "none",
        }}
      >
        <h1
          style={{
            fontSize: "1.5rem",
            fontWeight: 700,
            margin: 0,
            color: periodId ? "#92400e" : "#111827",
          }}
        >
          {periodId ? `📅 ${viewingPeriod?.label ?? "이전 기록"} 스냅샷` : "진행상황"}
        </h1>
        {periodId && (
          <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "#92400e" }}>
            (현재 아님)
          </span>
        )}

        <button
          className="no-print"
          onClick={() => window.print()}
          style={{
            padding: "0.4rem 0.9rem",
            borderRadius: 8,
            border: `1px solid ${periodId ? "#fde68a" : "#d1d5db"}`,
            background: "white",
            color: "#374151",
            fontSize: "0.82rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          PDF로 저장
        </button>
        <button
          className="no-print"
          onClick={() =>
            exportChecklistToExcel(
              allItems,
              (item) => {
                const bucket = progressBucketOf(statusOf(item));
                return bucket === null ? null : statusLabel[bucket];
              },
              "진행상황",
              "진행상황.xlsx",
            )
          }
          style={{
            padding: "0.4rem 0.9rem",
            borderRadius: 8,
            border: `1px solid ${periodId ? "#fde68a" : "#d1d5db"}`,
            background: "white",
            color: "#374151",
            fontSize: "0.82rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          엑셀로 추출
        </button>

        {periodId && (
          <>
            <button
              className="no-print"
              onClick={() => setEditMode((v) => !v)}
              style={{
                marginLeft: "auto",
                padding: "0.4rem 0.9rem",
                borderRadius: 8,
                border: `1px solid ${editMode ? "#b45309" : "#d97706"}`,
                background: editMode ? "#fde68a" : "white",
                color: "#92400e",
                fontSize: "0.82rem",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {editMode ? "🔓 수정 중 (잠그기)" : "🔒 수정하기"}
            </button>
            <Link className="no-print" to="/progress" style={{ color: "#2563eb", fontWeight: 600, fontSize: "0.82rem" }}>
              현재 진행상황으로
            </Link>
          </>
        )}
      </div>

      {isLoading ? (
        <p style={{ color: "#6b7280" }}>불러오는 중...</p>
      ) : isError ? (
        <p style={{ color: "#dc2626" }}>데이터를 불러오지 못했습니다. 새로고침 해주세요.</p>
      ) : total === 0 ? (
        <p style={{ color: "#6b7280" }}>
          준수 대상 항목이 없습니다. 체크리스트에서 상태를 설정해보세요.
        </p>
      ) : (
        <>
          <div
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 10,
              background: "white",
              padding: "1.1rem 1.25rem",
              marginBottom: "1.5rem",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 8,
              }}
            >
              <span style={{ fontSize: "0.85rem", color: "#6b7280" }}>
                준수 대상 {total}건 중 {completedCount}건 완료
              </span>
              <span style={{ fontSize: "1.1rem", fontWeight: 700, color: "#16a34a" }}>
                {progressPct}%
              </span>
            </div>
            <div style={{ height: 8, background: "#e5e7eb", borderRadius: 99, overflow: "hidden" }}>
              <div
                style={{
                  height: "100%",
                  width: `${progressPct}%`,
                  background: "#16a34a",
                  borderRadius: 99,
                  transition: "width 0.3s ease",
                }}
              />
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: "1rem",
            }}
          >
            {PROGRESS_STATUSES.map((s) => {
              const isCollapsed = collapsed.has(s);
              return (
                <div
                  key={s}
                  style={{
                    border: "1px solid #e5e7eb",
                    borderRadius: 10,
                    background: "white",
                    overflow: "hidden",
                  }}
                >
                  <button
                    onClick={() => toggleCollapse(s)}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "0.75rem 1rem",
                      borderBottom: isCollapsed ? "none" : "1px solid #f3f4f6",
                      background: "#fafafa",
                      border: "none",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>
                        {isCollapsed ? "›" : "⌄"}
                      </span>
                      <span style={{ fontWeight: 600, color: statusAccent[s], fontSize: "0.9rem" }}>
                        {statusLabel[s]}
                      </span>
                    </span>
                    <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>{buckets[s].length}건</span>
                  </button>
                  {!isCollapsed && (
                    <div style={{ padding: "0 1rem" }}>
                      {buckets[s].length === 0 ? (
                        <p style={{ color: "#9ca3af", fontSize: "0.85rem", padding: "0.75rem 0" }}>
                          해당 항목이 없습니다.
                        </p>
                      ) : (
                        buckets[s].map((item) => (
                          <ProgressRow
                            key={item.id}
                            item={item}
                            status={statusOf(item)}
                            locked={locked}
                            isOpen={openStatusFor === item.id}
                            onToggleOpen={() =>
                              setOpenStatusFor(openStatusFor === item.id ? null : item.id)
                            }
                            onSelect={(status) => {
                              updateStatus({ canonicalId: item.id, status });
                              setOpenStatusFor(null);
                            }}
                          />
                        ))
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function checkboxGlyph(status: Status) {
  if (status === "completed") return "✓";
  if (status === "not_applicable") return "–";
  if (status === "in_progress") return "●";
  return "";
}

function checkboxStyle(status: Status): React.CSSProperties {
  const palette: Record<Status, { border: string; bg: string; fg: string }> = {
    completed: { border: "#16a34a", bg: "#16a34a", fg: "white" },
    in_progress: { border: "#ca8a04", bg: "white", fg: "#ca8a04" },
    not_applicable: { border: "#d1d5db", bg: "#f3f4f6", fg: "#9ca3af" },
    not_started: { border: "#9ca3af", bg: "white", fg: "white" },
  };
  const c = palette[status];
  return {
    width: 20,
    height: 20,
    minWidth: 20,
    borderRadius: 5,
    border: `1.5px solid ${c.border}`,
    background: c.bg,
    color: c.fg,
    fontSize: "0.75rem",
    fontWeight: 700,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    padding: 0,
    flexShrink: 0,
  };
}

function ProgressRow({
  item,
  status,
  locked = false,
  isOpen,
  onToggleOpen,
  onSelect,
}: {
  item: ChecklistItemDetail;
  status: Status;
  locked?: boolean;
  isOpen: boolean;
  onToggleOpen: () => void;
  onSelect: (status: Status) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.65rem",
        padding: "0.65rem 0",
        borderBottom: "1px solid #f3f4f6",
      }}
    >
      <div style={{ position: "relative" }}>
        <button
          onClick={locked ? undefined : onToggleOpen}
          disabled={locked}
          title={locked ? "잠겨있습니다 — 상단의 '수정하기'를 눌러야 변경할 수 있어요" : undefined}
          style={{
            ...checkboxStyle(status),
            cursor: locked ? "not-allowed" : "pointer",
            opacity: locked ? 0.6 : 1,
          }}
        >
          {checkboxGlyph(status)}
        </button>

        {isOpen && !locked && (
          <>
            <div onClick={onToggleOpen} style={{ position: "fixed", inset: 0, zIndex: 20 }} />
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 4px)",
                left: 0,
                zIndex: 21,
                background: "white",
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
                minWidth: 110,
                overflow: "hidden",
              }}
            >
              {STATUS_OPTIONS.map((s) => (
                <div
                  key={s}
                  onClick={() => onSelect(s)}
                  style={{
                    padding: "0.5rem 0.8rem",
                    fontSize: "0.82rem",
                    fontWeight: s === status ? 700 : 400,
                    color: s === status ? "#111827" : "#4b5563",
                    background: s === status ? "#f3f4f6" : "white",
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {statusLabel[s]}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <span
        style={{
          fontSize: "0.9rem",
          color: status === "completed" ? "#9ca3af" : "#111827",
          textDecoration: status === "completed" ? "line-through" : "none",
        }}
      >
        {item.merged_title}
      </span>

      {(item.documents.length > 0 || item.department_name) && (
        <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
          {item.department_name && (
            <span
              style={{
                padding: "0.15rem 0.55rem",
                borderRadius: 4,
                background: "#f5f3ff",
                color: "#6d28d9",
                fontSize: "0.7rem",
                fontWeight: 600,
                whiteSpace: "nowrap",
              }}
            >
              {item.department_name}
            </span>
          )}
          {item.documents.map((d) => (
            <span
              key={d.document_id}
              title={d.document_name}
              style={{
                padding: "0.15rem 0.55rem",
                borderRadius: 4,
                background: "#eef2ff",
                color: "#4338ca",
                fontSize: "0.7rem",
                fontWeight: 600,
                whiteSpace: "nowrap",
              }}
            >
              {d.doc_type}
            </span>
          ))}
        </span>
      )}
    </div>
  );
}