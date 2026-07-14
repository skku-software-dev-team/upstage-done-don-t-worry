import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { checklistApi, type ChecklistItemDetail, type OrgStatus } from "@/api/compliance";

const DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001";

const STATUS_OPTIONS = ["not_started", "in_progress", "completed", "not_applicable"] as const;
type Status = (typeof STATUS_OPTIONS)[number];

const statusLabel: Record<Status, string> = {
  not_started: "미시작",
  in_progress: "진행중",
  completed: "완료",
  not_applicable: "해당없음",
};

const UNCATEGORIZED_ID = "__uncategorized__";

interface CategoryGroup {
  id: string;
  name: string;
  items: ChecklistItemDetail[];
}

export default function ChecklistPage() {
  const qc = useQueryClient();
  const [orgId] = useState(DEFAULT_ORG_ID);
  const [docType, setDocType] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [openStatusFor, setOpenStatusFor] = useState<string | null>(null);

  const { data: allItems = [] } = useQuery({
    queryKey: ["checklist-items"],
    queryFn: () => checklistApi.list(),
  });

  const presentDocTypes = Array.from(
    new Set(allItems.flatMap((i) => i.documents.map((d) => d.doc_type))),
  ).sort((a, b) => a.localeCompare(b, "ko"));

  const presentCategories = Array.from(
    new Map(
      allItems
        .filter((i) => i.category_id && i.category_name)
        .map((i) => [i.category_id!, i.category_name!]),
    ).entries(),
  ).sort((a, b) => a[1].localeCompare(b[1], "ko"));

  const query = search.trim().toLowerCase();
  const items = allItems.filter(
    (i) =>
      (docType === null || i.documents.some((d) => d.doc_type === docType)) &&
      (categoryId === null || i.category_id === categoryId) &&
      (query === "" || i.merged_title.toLowerCase().includes(query)),
  );

  const { data: statuses = [] } = useQuery({
    queryKey: ["org-status", orgId],
    queryFn: () => checklistApi.orgStatus(orgId),
  });

  const statusMap = new Map<string, OrgStatus>(statuses.map((s) => [s.canonical_id, s]));
  const statusOf = (item: ChecklistItemDetail): Status =>
    (statusMap.get(item.id)?.status as Status) ?? "not_started";

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

  const groups: CategoryGroup[] = [];
  const groupById = new Map<string, CategoryGroup>();
  for (const item of items) {
    const id = item.category_id ?? UNCATEGORIZED_ID;
    const name = item.category_name ?? "미분류";
    let group = groupById.get(id);
    if (!group) {
      group = { id, name, items: [] };
      groupById.set(id, group);
      groups.push(group);
    }
    group.items.push(item);
  }
  groups.sort((a, b) => a.name.localeCompare(b.name, "ko"));

  const toggleCollapse = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const matchesQuery = (i: ChecklistItemDetail) =>
    query === "" || i.merged_title.toLowerCase().includes(query);

  const countForDoc = (dt: string | null) =>
    allItems.filter(
      (i) =>
        (dt === null || i.documents.some((d) => d.doc_type === dt)) &&
        (categoryId === null || i.category_id === categoryId) &&
        matchesQuery(i),
    ).length;
  const countForCat = (cid: string | null) =>
    allItems.filter(
      (i) =>
        (docType === null || i.documents.some((d) => d.doc_type === docType)) &&
        (cid === null || i.category_id === cid) &&
        matchesQuery(i),
    ).length;

  return (
    <div style={{ padding: "2rem", maxWidth: 720, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1rem" }}>체크리스트</h1>

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="항목 검색..."
        style={{
          width: "100%",
          padding: "0.55rem 0.9rem",
          borderRadius: 8,
          border: "1px solid #d1d5db",
          fontSize: "0.88rem",
          marginBottom: "1.25rem",
          boxSizing: "border-box",
        }}
      />

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

      {groups.length === 0 ? (
        <p style={{ color: "#6b7280" }}>
          {allItems.length === 0
            ? "항목이 없습니다. 문서를 먼저 업로드하세요."
            : "선택한 필터에 해당하는 항목이 없습니다."}
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {groups.map((group) => {
            const isCollapsed = collapsed.has(group.id);
            const applicableItems = group.items.filter((i) => statusOf(i) !== "not_applicable");
            const doneCount = applicableItems.filter((i) => statusOf(i) === "completed").length;
            const isAllDone = applicableItems.length > 0 && doneCount === applicableItems.length;
            return (
              <div
                key={group.id}
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: 10,
                  background: "white",
                  overflow: "visible",
                }}
              >
                <button
                  onClick={() => toggleCollapse(group.id)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.9rem 1.1rem",
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>
                      {isCollapsed ? "›" : "⌄"}
                    </span>
                    <span style={{ fontWeight: 600, color: "#111827" }}>{group.name}</span>
                  </span>
                  <span
                    style={
                      isAllDone
                        ? {
                            fontSize: "0.8rem",
                            fontWeight: 600,
                            color: "white",
                            background: "#16a34a",
                            padding: "0.25rem 0.75rem",
                            borderRadius: 999,
                          }
                        : { fontSize: "0.8rem", color: "#6b7280" }
                    }
                  >
                    {doneCount}/{applicableItems.length} 완료
                  </span>
                </button>

                {!isCollapsed && (
                  <div style={{ padding: "0 1.1rem 0.75rem" }}>
                    {group.items.map((item) => (
                      <ChecklistRow
                        key={item.id}
                        item={item}
                        status={statusOf(item)}
                        isOpen={openStatusFor === item.id}
                        onToggleOpen={() =>
                          setOpenStatusFor(openStatusFor === item.id ? null : item.id)
                        }
                        onSelect={(status) => {
                          updateStatus({ canonicalId: item.id, status });
                          setOpenStatusFor(null);
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
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
    not_started: { border: "#d1d5db", bg: "white", fg: "white" },
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

function ChecklistRow({
  item,
  status,
  isOpen,
  onToggleOpen,
  onSelect,
}: {
  item: ChecklistItemDetail;
  status: Status;
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
        <button onClick={onToggleOpen} style={checkboxStyle(status)}>
          {checkboxGlyph(status)}
        </button>

        {isOpen && (
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

      {item.documents.length > 0 && (
        <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
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
