import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  checklistApi,
  orgApi,
  type ChecklistItemDetail,
  type JiraConnectInput,
  type OrgStatus,
} from "@/api/compliance";

const STATUS_OPTIONS = ["not_started", "in_progress", "completed", "not_applicable"] as const;
type Status = (typeof STATUS_OPTIONS)[number];
// "untouched" = no org_status row yet (nothing checked, no Jira ticket).
type DisplayStatus = Status | "untouched";

const statusLabel: Record<DisplayStatus, string> = {
  untouched: "미설정",
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
  const { periodId } = useParams<{ periodId?: string }>();
  const [selectedDocTypes, setSelectedDocTypes] = useState<Set<string>>(new Set());
  const [selectedCategoryIds, setSelectedCategoryIds] = useState<Set<string>>(new Set());
  const [multiSelectDocType, setMultiSelectDocType] = useState(false);
  const [multiSelectCategory, setMultiSelectCategory] = useState(false);
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
  const matchesQuery = (i: ChecklistItemDetail) =>
    query === "" || i.merged_title.toLowerCase().includes(query);

  const items = allItems.filter(
    (i) =>
      (selectedDocTypes.size === 0 ||
        i.documents.some((d) => selectedDocTypes.has(d.doc_type))) &&
      (selectedCategoryIds.size === 0 ||
        (i.category_id !== null && selectedCategoryIds.has(i.category_id))) &&
      matchesQuery(i),
  );

  const { data: statuses = [] } = useQuery({
    queryKey: ["org-status", periodId ?? "current"],
    queryFn: () => checklistApi.orgStatus(periodId),
  });

  const { data: periods = [] } = useQuery({
    queryKey: ["checklist-periods"],
    queryFn: () => checklistApi.periods(),
  });
  const viewingPeriod = periodId ? periods.find((p) => p.id === periodId) : undefined;

  const { data: org } = useQuery({
    queryKey: ["org"],
    queryFn: () => orgApi.get(),
  });
  const jiraBaseUrl = org?.jira_base_url ?? null;

  const statusMap = new Map<string, OrgStatus>(statuses.map((s) => [s.canonical_id, s]));
  const statusOf = (item: ChecklistItemDetail): DisplayStatus =>
    (statusMap.get(item.id)?.status as DisplayStatus) ?? "untouched";

  const { mutate: updateStatus } = useMutation({
    mutationFn: ({ canonicalId, status }: { canonicalId: string; status: Status }) =>
      checklistApi.updateStatus(canonicalId, status, undefined, periodId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["org-status", periodId ?? "current"] }),
  });

  const [showSaveForm, setShowSaveForm] = useState(false);
  const [saveLabel, setSaveLabel] = useState("");
  const [saveStart, setSaveStart] = useState("");
  const [saveEnd, setSaveEnd] = useState("");

  const { mutate: savePeriod, isPending: isSaving } = useMutation({
    mutationFn: () => checklistApi.savePeriod(saveLabel.trim(), saveStart || undefined, saveEnd || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["checklist-periods"] });
      setShowSaveForm(false);
      setSaveLabel("");
      setSaveStart("");
      setSaveEnd("");
    },
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

  const toggleSetMember = (
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    value: string,
  ) =>
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });

  const toggleCollapse = (id: string) => toggleSetMember(setCollapsed, id);

  const countForDoc = (dt: string | null) =>
    allItems.filter(
      (i) =>
        (dt === null || i.documents.some((d) => d.doc_type === dt)) &&
        (selectedCategoryIds.size === 0 ||
          (i.category_id !== null && selectedCategoryIds.has(i.category_id))) &&
        matchesQuery(i),
    ).length;
  const countForCat = (cid: string | null) =>
    allItems.filter(
      (i) =>
        (selectedDocTypes.size === 0 ||
          i.documents.some((d) => selectedDocTypes.has(d.doc_type))) &&
        (cid === null || i.category_id === cid) &&
        matchesQuery(i),
    ).length;

  return (
    <div style={{ padding: "2rem", maxWidth: 720, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "1rem",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0 }}>체크리스트</h1>
        {!viewingPeriod && (
          <button
            onClick={() => setShowSaveForm((v) => !v)}
            style={{
              padding: "0.45rem 0.9rem",
              borderRadius: 6,
              border: "1px solid #2563eb",
              background: "white",
              color: "#2563eb",
              fontSize: "0.82rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            히스토리로 저장
          </button>
        )}
      </div>

      {periodId && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.6rem",
            padding: "0.6rem 0.9rem",
            marginBottom: "1rem",
            borderRadius: 8,
            background: "#fffbeb",
            border: "1px solid #fde68a",
            fontSize: "0.82rem",
            color: "#92400e",
          }}
        >
          <span>
            📅 <strong>{viewingPeriod?.label ?? "이전 기록"}</strong> 기간 보는 중 (현재 아님)
          </span>
          <Link to="/checklist" style={{ marginLeft: "auto", color: "#2563eb", fontWeight: 600 }}>
            진행중 체크리스트로
          </Link>
        </div>
      )}

      {showSaveForm && !viewingPeriod && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.5rem",
            alignItems: "flex-end",
            padding: "0.9rem 1rem",
            marginBottom: "1.25rem",
            borderRadius: 10,
            border: "1px solid #dbeafe",
            background: "#eff6ff",
          }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.72rem", color: "#6b7280", fontWeight: 600 }}>
            라벨
            <input
              type="text"
              value={saveLabel}
              onChange={(e) => setSaveLabel(e.target.value)}
              placeholder="예: 2026년 7월 정기점검"
              style={{ padding: "0.45rem 0.6rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.82rem", minWidth: 200 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.72rem", color: "#6b7280", fontWeight: 600 }}>
            시작일
            <input
              type="date"
              value={saveStart}
              onChange={(e) => setSaveStart(e.target.value)}
              style={{ padding: "0.45rem 0.6rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.82rem" }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.72rem", color: "#6b7280", fontWeight: 600 }}>
            종료일
            <input
              type="date"
              value={saveEnd}
              onChange={(e) => setSaveEnd(e.target.value)}
              style={{ padding: "0.45rem 0.6rem", borderRadius: 6, border: "1px solid #d1d5db", fontSize: "0.82rem" }}
            />
          </label>
          <button
            disabled={!saveLabel.trim() || isSaving}
            onClick={() => savePeriod()}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: 6,
              border: "none",
              background: !saveLabel.trim() || isSaving ? "#93c5fd" : "#2563eb",
              color: "white",
              fontSize: "0.82rem",
              fontWeight: 600,
              cursor: !saveLabel.trim() || isSaving ? "default" : "pointer",
            }}
          >
            {isSaving ? "저장 중..." : "저장"}
          </button>
          <button
            onClick={() => setShowSaveForm(false)}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: 6,
              border: "1px solid #d1d5db",
              background: "white",
              color: "#374151",
              fontSize: "0.82rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            취소
          </button>
        </div>
      )}

      <JiraSettings />

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
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: 6 }}>
            <span style={{ fontSize: "0.72rem", color: "#9ca3af", fontWeight: 600 }}>
              문서 / 인증
            </span>
            <MultiSelectToggle
              checked={multiSelectDocType}
              onChange={(checked) => {
                setMultiSelectDocType(checked);
                setSelectedDocTypes(new Set());
              }}
            />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            <button
              style={chipStyle(selectedDocTypes.size === 0)}
              onClick={() => setSelectedDocTypes(new Set())}
            >
              전체 ({countForDoc(null)})
            </button>
            {presentDocTypes.map((dt) => (
              <FilterChip
                key={dt}
                label={`${dt} (${countForDoc(dt)})`}
                active={selectedDocTypes.has(dt)}
                accent="#2563eb"
                onClick={() =>
                  multiSelectDocType
                    ? toggleSetMember(setSelectedDocTypes, dt)
                    : setSelectedDocTypes(new Set([dt]))
                }
              />
            ))}
          </div>
        </div>
      )}

      {presentCategories.length > 0 && (
        <div style={{ marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: 6 }}>
            <span style={{ fontSize: "0.72rem", color: "#9ca3af", fontWeight: 600 }}>
              카테고리
            </span>
            <MultiSelectToggle
              checked={multiSelectCategory}
              onChange={(checked) => {
                setMultiSelectCategory(checked);
                setSelectedCategoryIds(new Set());
              }}
            />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            <button
              style={chipStyle(selectedCategoryIds.size === 0, "#059669")}
              onClick={() => setSelectedCategoryIds(new Set())}
            >
              전체 ({countForCat(null)})
            </button>
            {presentCategories.map(([id, name]) => (
              <FilterChip
                key={id}
                label={`${name} (${countForCat(id)})`}
                active={selectedCategoryIds.has(id)}
                accent="#059669"
                onClick={() =>
                  multiSelectCategory
                    ? toggleSetMember(setSelectedCategoryIds, id)
                    : setSelectedCategoryIds(new Set([id]))
                }
              />
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
                        jiraKey={statusMap.get(item.id)?.jira_key ?? null}
                        jiraBaseUrl={jiraBaseUrl}
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

function MultiSelectToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.3rem",
        fontSize: "0.7rem",
        color: "#9ca3af",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ cursor: "pointer" }}
      />
      복수 선택
    </label>
  );
}

function FilterChip({
  label,
  active,
  accent,
  onClick,
}: {
  label: string;
  active: boolean;
  accent: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.4rem",
        padding: "0.35rem 0.85rem",
        borderRadius: 999,
        border: `1px solid ${active ? accent : "#d1d5db"}`,
        background: active ? accent : "white",
        color: active ? "white" : "#374151",
        fontSize: "0.8rem",
        fontWeight: 600,
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      {label}
    </button>
  );
}

function checkboxGlyph(status: DisplayStatus) {
  if (status === "completed") return "✓";
  if (status === "not_applicable") return "–";
  if (status === "in_progress") return "●";
  return "";
}

function checkboxStyle(status: DisplayStatus): React.CSSProperties {
  const palette: Record<DisplayStatus, { border: string; bg: string; fg: string }> = {
    completed: { border: "#16a34a", bg: "#16a34a", fg: "white" },
    in_progress: { border: "#ca8a04", bg: "white", fg: "#ca8a04" },
    not_applicable: { border: "#d1d5db", bg: "#f3f4f6", fg: "#9ca3af" },
    not_started: { border: "#9ca3af", bg: "white", fg: "white" },
    untouched: { border: "#e5e7eb", bg: "#fafafa", fg: "white" },
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
  jiraKey,
  jiraBaseUrl,
  isOpen,
  onToggleOpen,
  onSelect,
}: {
  item: ChecklistItemDetail;
  status: DisplayStatus;
  jiraKey: string | null;
  jiraBaseUrl: string | null;
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

      {jiraKey && (
        <a
          href={jiraBaseUrl ? `${jiraBaseUrl}/browse/${jiraKey}` : undefined}
          target="_blank"
          rel="noreferrer"
          style={{
            marginLeft: item.doc_type ? 0 : "auto",
            padding: "0.15rem 0.5rem",
            borderRadius: 4,
            background: "#eff6ff",
            color: "#1d4ed8",
            fontSize: "0.7rem",
            fontWeight: 700,
            whiteSpace: "nowrap",
            textDecoration: "none",
          }}
        >
          {jiraKey}
        </a>
      )}
    </div>
  );
}

const JIRA_DEFAULTS = {
  jira_base_url: "https://personal-search-agent.atlassian.net",
  jira_email: "",
  jira_api_token: "",
  jira_project_key: "DDW",
};

function JiraSettings() {
  const qc = useQueryClient();
  const { data: org } = useQuery({
    queryKey: ["org"],
    queryFn: () => orgApi.get(),
  });

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<JiraConnectInput>(JIRA_DEFAULTS);

  const connected = org?.jira_connected ?? false;
  const showForm = editing || !connected;

  const { mutate: save, isPending, isError } = useMutation({
    mutationFn: (input: JiraConnectInput) => orgApi.connectJira(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["org"] });
      setEditing(false);
      setForm((f) => ({ ...f, jira_api_token: "" }));
    },
  });

  const {
    mutate: sync,
    isPending: isSyncing,
    data: syncResult,
  } = useMutation({
    mutationFn: () => checklistApi.syncJira(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-status"] }),
  });

  const startEditing = () => {
    setForm({
      jira_base_url: org?.jira_base_url ?? JIRA_DEFAULTS.jira_base_url,
      jira_email: org?.jira_email ?? "",
      jira_api_token: "",
      jira_project_key: org?.jira_project_key ?? JIRA_DEFAULTS.jira_project_key,
    });
    setEditing(true);
  };

  const canSave =
    form.jira_base_url.trim() &&
    form.jira_email.trim() &&
    form.jira_api_token.trim() &&
    form.jira_project_key.trim();

  const field = (
    label: string,
    key: keyof JiraConnectInput,
    placeholder: string,
    type = "text",
  ) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.72rem", color: "#6b7280", fontWeight: 600 }}>
      {label}
      <input
        type={type}
        value={form[key]}
        placeholder={placeholder}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        style={{
          padding: "0.45rem 0.6rem",
          borderRadius: 6,
          border: "1px solid #d1d5db",
          fontSize: "0.82rem",
          fontWeight: 400,
          color: "#111827",
          boxSizing: "border-box",
        }}
      />
    </label>
  );

  return (
    <div
      style={{
        border: `1px solid ${connected ? "#bbf7d0" : "#e5e7eb"}`,
        background: connected ? "#f0fdf4" : "#fafafa",
        borderRadius: 10,
        padding: "0.9rem 1rem",
        marginBottom: "1.25rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: showForm ? "0.85rem" : 0 }}>
        <span style={{ fontSize: "0.9rem", fontWeight: 700, color: "#111827" }}>Jira 연동</span>
        <span
          style={{
            fontSize: "0.72rem",
            fontWeight: 600,
            padding: "0.1rem 0.5rem",
            borderRadius: 999,
            background: connected ? "#dcfce7" : "#f3f4f6",
            color: connected ? "#15803d" : "#6b7280",
          }}
        >
          {connected ? "● 연결됨" : "○ 미연결"}
        </span>
        {connected && !editing && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
            <button
              onClick={() => sync()}
              disabled={isSyncing}
              style={{
                fontSize: "0.75rem",
                fontWeight: 600,
                color: "white",
                background: isSyncing ? "#86efac" : "#16a34a",
                border: "none",
                borderRadius: 6,
                padding: "0.35rem 0.7rem",
                cursor: isSyncing ? "default" : "pointer",
              }}
            >
              {isSyncing ? "동기화 중..." : "↻ Jira에서 동기화"}
            </button>
            <button
              onClick={startEditing}
              style={{
                fontSize: "0.75rem",
                fontWeight: 600,
                color: "#2563eb",
                background: "none",
                border: "none",
                cursor: "pointer",
              }}
            >
              재설정
            </button>
          </div>
        )}
      </div>

      {connected && !editing && (
        <div style={{ fontSize: "0.78rem", color: "#4b5563", marginTop: 6 }}>
          {org?.jira_base_url} · 프로젝트 <strong>{org?.jira_project_key}</strong> · {org?.jira_email}
          {syncResult && (
            <span style={{ marginLeft: 8, color: "#15803d", fontWeight: 600 }}>
              · {syncResult.updated}건 업데이트됨 (총 {syncResult.synced}건 확인)
            </span>
          )}
        </div>
      )}

      {showForm && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          {field("사이트 URL", "jira_base_url", "https://your-site.atlassian.net")}
          {field("이메일", "jira_email", "you@example.com")}
          {field("API 토큰", "jira_api_token", "Atlassian API token", "password")}
          {field("프로젝트 키", "jira_project_key", "DDW")}

          {isError && (
            <div style={{ fontSize: "0.75rem", color: "#dc2626" }}>저장에 실패했습니다. 다시 시도하세요.</div>
          )}

          <div style={{ display: "flex", gap: 8 }}>
            <button
              disabled={!canSave || isPending}
              onClick={() => save(form)}
              style={{
                padding: "0.5rem 1rem",
                borderRadius: 6,
                border: "none",
                background: !canSave || isPending ? "#93c5fd" : "#2563eb",
                color: "white",
                fontSize: "0.82rem",
                fontWeight: 600,
                cursor: !canSave || isPending ? "default" : "pointer",
              }}
            >
              {isPending ? "저장 중..." : "저장"}
            </button>
            {connected && editing && (
              <button
                onClick={() => setEditing(false)}
                style={{
                  padding: "0.5rem 1rem",
                  borderRadius: 6,
                  border: "1px solid #d1d5db",
                  background: "white",
                  color: "#374151",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                취소
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
