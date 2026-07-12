import client from "./client";

export interface Document {
  id: string;
  name: string;
  doc_type: string;
  version: string;
  created_at: string;
}

export interface Clause {
  id: string;
  document_id: string;
  clause_no: string | null;
  title: string | null;
  requirement: string | null;
  related_laws: string | null;
  page: number | null;
  created_at: string;
}

export interface CanonicalItem {
  id: string;
  category_id: string | null;
  merged_title: string;
}

export interface OrgStatus {
  id: string;
  org_id: string;
  canonical_id: string;
  status: string;
  jira_key: string | null;
  updated_at: string;
}

export interface ChatResponse {
  answer: string;
  sources: Clause[];
}

export interface UploadResult {
  message: string;
  clauses: number;
  checklist_items: number;
}

export const documentsApi = {
  list: () => client.get<Document[]>("/documents").then((r) => r.data),
  create: (data: Pick<Document, "name" | "doc_type">) =>
    client.post<Document>("/documents", data).then((r) => r.data),
  delete: (docId: string) => client.delete(`/documents/${docId}`),
  clauses: (docId: string) =>
    client.get<Clause[]>(`/documents/${docId}/clauses`).then((r) => r.data),
  upload: (docId: string, formData: FormData) =>
    client
      .post<UploadResult>(`/documents/${docId}/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data),
};

export const checklistApi = {
  list: () => client.get<CanonicalItem[]>("/checklist").then((r) => r.data),
  orgStatus: (orgId: string) =>
    client.get<OrgStatus[]>(`/checklist/org/${orgId}`).then((r) => r.data),
  updateStatus: (orgId: string, canonicalId: string, status: string, jiraKey?: string) =>
    client
      .put<OrgStatus>(`/checklist/org/${orgId}/item/${canonicalId}`, {
        status,
        jira_key: jiraKey,
      })
      .then((r) => r.data),
};

export const chatApi = {
  send: (message: string, orgId?: string) =>
    client
      .post<ChatResponse>("/chat", { message, org_id: orgId })
      .then((r) => r.data),
};
