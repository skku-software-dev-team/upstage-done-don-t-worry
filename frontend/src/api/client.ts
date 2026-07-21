import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

export const TOKEN_STORAGE_KEY = "auth_token";

client.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // Only force a redirect when a session that WAS logged in just expired —
    // not when e.g. the login form itself gets a 401 for bad credentials,
    // which the caller needs to catch and show inline.
    if (error.response?.status === 401 && localStorage.getItem(TOKEN_STORAGE_KEY)) {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export default client;
