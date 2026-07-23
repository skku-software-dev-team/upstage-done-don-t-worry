import client from "./client";

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  department_id: string | null;
  role: "admin" | "member";
}

export interface AuthOrganization {
  id: string;
  name: string;
  jira_base_url: string | null;
  jira_email: string | null;
  jira_project_key: string | null;
  jira_connected: boolean;
  updated_at: string;
}

export interface AuthMeResponse {
  user: AuthUser;
  organization: AuthOrganization;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface AuthDepartment {
  id: string;
  name: string;
}

export const authApi = {
  signup: (orgName: string, email: string, password: string, name: string, departmentId?: string) =>
    client
      .post<TokenResponse>("/auth/signup", {
        org_name: orgName,
        email,
        password,
        name,
        department_id: departmentId || null,
      })
      .then((r) => r.data),
  login: (email: string, password: string) =>
    client.post<TokenResponse>("/auth/login", { email, password }).then((r) => r.data),
  acceptInvite: (token: string, email: string, password: string, name: string, departmentId?: string) =>
    client
      .post<TokenResponse>("/auth/accept-invite", {
        token,
        email,
        password,
        name,
        department_id: departmentId || null,
      })
      .then((r) => r.data),
  me: () => client.get<AuthMeResponse>("/auth/me").then((r) => r.data),
  departments: () => client.get<AuthDepartment[]>("/auth/departments").then((r) => r.data),
};
