import { api } from "./client";
import type { Membership, MyWorkspaces, User } from "./types";

export const authApi = {
  me: () => api<User>("/auth/me/", { skipUnauthorizedHandler: true }),
  login: (email: string, password: string) =>
    api<User>("/auth/login/", {
      method: "POST",
      body: { email, password },
      skipUnauthorizedHandler: true,
    }),
  logout: () => api<void>("/auth/logout/", { method: "POST" }),
};

export const workspaceApi = {
  mine: () => api<MyWorkspaces>("/workspaces/"),
  /** Tell the server which workspace this session used last (a redirect hint only). */
  remember: (workspaceId: string) =>
    api<Membership>("/workspaces/current/", { method: "PUT", body: { workspace_id: workspaceId } }),
  detail: (workspaceId: string) => api<Membership>(`/workspaces/${workspaceId}/`),
};
