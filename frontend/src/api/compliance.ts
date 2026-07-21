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

export interface Category {
  id: string;
  name: string;
}

export interface ChecklistDocRef {
  document_id: string;
  doc_type: string;
  document_name: string;
}

export interface ChecklistItemDetail {
  id: string;
  merged_title: string;
  category_id: string | null;
  category_name: string | null;
  documents: ChecklistDocRef[];
}

export interface OrgStatus {
  id: string;
  canonical_id: string;
  period_id: string;
  status: string;
  jira_key: string | null;
  updated_at: string;
}

export interface ChecklistPeriod {
  id: string;
  label: string;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  jira_base_url: string | null;
  jira_email: string | null;
  jira_project_key: string | null;
  jira_connected: boolean;
  updated_at: string;
}

export interface JiraConnectInput {
  jira_base_url: string;
  jira_email: string;
  jira_api_token: string;
  jira_project_key: string;
}

export interface ChatSource {
  id: string;
  source_type: "clause" | "law_article";
  clause_no: string | null;
  title: string | null;
  document_name: string | null;
  doc_type: string | null;
}

export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
}

export interface UploadResult {
  message: string;
  clauses: number;
  checklist_items: number;
  linked_laws?: number;
}

export interface Law {
  id: string;
  name: string;
  version: string;
  enacted_date: string | null;
}

export interface LawArticle {
  id: string;
  law_id: string;
  article_no: string | null;
  article_text: string | null;
}

export interface LawUploadResult {
  message: string;
  articles: number;
  linked_clauses: number;
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
  list: (params?: { categoryId?: string; documentId?: string }) =>
    client
      .get<ChecklistItemDetail[]>("/checklist", {
        params: {
          category_id: params?.categoryId,
          document_id: params?.documentId,
        },
      })
      .then((r) => r.data),
  categories: () => client.get<Category[]>("/checklist/categories").then((r) => r.data),
  orgStatus: (periodId?: string) =>
    client
      .get<OrgStatus[]>("/checklist/status", { params: { period_id: periodId } })
      .then((r) => r.data),
  updateStatus: (canonicalId: string, status: string, jiraKey?: string, periodId?: string) =>
    client
      .put<OrgStatus>(`/checklist/item/${canonicalId}`, {
        status,
        jira_key: jiraKey,
        period_id: periodId,
      })
      .then((r) => r.data),
  syncJira: () =>
    client
      .post<{ synced: number; updated: number }>("/checklist/jira/sync")
      .then((r) => r.data),
  periods: () => client.get<ChecklistPeriod[]>("/checklist/periods").then((r) => r.data),
  savePeriod: (label: string, startDate?: string, endDate?: string) =>
    client
      .post<ChecklistPeriod>("/checklist/periods", {
        label,
        start_date: startDate,
        end_date: endDate,
      })
      .then((r) => r.data),
};

export const orgApi = {
  get: () => client.get<Organization>("/org").then((r) => r.data),
  connectJira: (data: JiraConnectInput) =>
    client.put<Organization>("/org/jira", data).then((r) => r.data),
};

export const lawsApi = {
  list: () => client.get<Law[]>("/laws").then((r) => r.data),
  create: (data: Pick<Law, "name" | "version" | "enacted_date">) =>
    client.post<Law>("/laws", data).then((r) => r.data),
  delete: (lawId: string) => client.delete(`/laws/${lawId}`),
  articles: (lawId: string) =>
    client.get<LawArticle[]>(`/laws/${lawId}/articles`).then((r) => r.data),
  upload: (lawId: string, formData: FormData) =>
    client
      .post<LawUploadResult>(`/laws/${lawId}/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data),
};

export const chatApi = {
  send: (message: string) =>
    client.post<ChatResponse>("/chat", { message }).then((r) => r.data),
};
