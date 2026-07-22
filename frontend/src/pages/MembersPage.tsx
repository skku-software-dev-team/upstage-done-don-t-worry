import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { orgApi } from "@/api/compliance";
import { useAuth } from "@/context/AuthContext";

export default function MembersPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const { data: members = [] } = useQuery({
    queryKey: ["org-members"],
    queryFn: orgApi.members,
  });

  const { data: invites = [] } = useQuery({
    queryKey: ["org-invites"],
    queryFn: orgApi.invites,
    enabled: isAdmin,
  });

  const { mutate: createInvite, isPending: isCreating } = useMutation({
    mutationFn: orgApi.createInvite,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-invites"] }),
  });

  const { mutate: revokeInvite } = useMutation({
    mutationFn: (inviteId: string) => orgApi.revokeInvite(inviteId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-invites"] }),
  });

  const inviteLink = (token: string) => `${window.location.origin}/invite/${token}`;

  const copyLink = async (invite: { id: string; token: string }) => {
    await navigator.clipboard.writeText(inviteLink(invite.token));
    setCopiedId(invite.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const pendingInvites = invites.filter((i) => !i.accepted_at);

  return (
    <div style={{ padding: "2rem", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1.5rem" }}>멤버</h1>

      <div style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        marginBottom: "2rem",
        overflow: "hidden",
      }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ background: "#f9fafb", textAlign: "left" }}>
              <th style={thStyle}>이메일</th>
              <th style={thStyle}>역할</th>
              <th style={thStyle}>가입일</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id} style={{ borderTop: "1px solid #f3f4f6" }}>
                <td style={tdStyle}>{m.email}</td>
                <td style={tdStyle}>
                  <span style={{
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    padding: "0.2rem 0.6rem",
                    borderRadius: 999,
                    background: m.role === "admin" ? "#dbeafe" : "#f3f4f6",
                    color: m.role === "admin" ? "#1d4ed8" : "#374151",
                  }}>
                    {m.role === "admin" ? "관리자" : "멤버"}
                  </span>
                </td>
                <td style={tdStyle}>{new Date(m.created_at).toLocaleDateString("ko-KR")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isAdmin && (
        <div style={{
          background: "white",
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: "1.5rem",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: 600, margin: 0 }}>멤버 초대</h2>
            <button
              onClick={() => createInvite()}
              disabled={isCreating}
              style={{
                padding: "0.5rem 1rem",
                borderRadius: 8,
                background: "#2563eb",
                color: "white",
                border: "none",
                fontWeight: 600,
                cursor: isCreating ? "default" : "pointer",
                fontSize: "0.85rem",
              }}
            >
              {isCreating ? "생성 중..." : "+ 초대 링크 생성"}
            </button>
          </div>

          {pendingInvites.length === 0 ? (
            <p style={{ color: "#9ca3af", fontSize: "0.85rem" }}>대기 중인 초대가 없습니다.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
              {pendingInvites.map((invite) => (
                <div
                  key={invite.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "0.75rem",
                    padding: "0.6rem 0.9rem",
                    background: "#f9fafb",
                    borderRadius: 8,
                    border: "1px solid #f3f4f6",
                  }}
                >
                  <span style={{
                    fontSize: "0.8rem",
                    color: "#374151",
                    fontFamily: "monospace",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {inviteLink(invite.token)}
                  </span>
                  <div style={{ display: "flex", gap: "0.5rem", flexShrink: 0 }}>
                    <button
                      onClick={() => copyLink(invite)}
                      style={{
                        padding: "0.35rem 0.7rem",
                        borderRadius: 6,
                        border: "1px solid #d1d5db",
                        background: "white",
                        fontSize: "0.78rem",
                        fontWeight: 600,
                        cursor: "pointer",
                        color: copiedId === invite.id ? "#16a34a" : "#374151",
                      }}
                    >
                      {copiedId === invite.id ? "복사됨!" : "링크 복사"}
                    </button>
                    <button
                      onClick={() => revokeInvite(invite.id)}
                      style={{
                        padding: "0.35rem 0.7rem",
                        borderRadius: 6,
                        border: "1px solid #fecaca",
                        background: "white",
                        color: "#dc2626",
                        fontSize: "0.78rem",
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      취소
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = { padding: "0.7rem 1rem", color: "#6b7280", fontWeight: 600, fontSize: "0.8rem" };
const tdStyle: React.CSSProperties = { padding: "0.7rem 1rem" };
