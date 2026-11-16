// Shapes returned by the backend. Keep in step with /api/schema/.

export interface User {
  id: string;
  email: string;
  full_name: string;
  phone: string;
}

export type Role = "owner" | "manager" | "attendant" | "affiliate";

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  status: "active" | "suspended" | "archived";
  currency: string;
}

export interface Membership {
  id: string;
  role: Role;
  status: "active" | "suspended" | "removed";
  workspace: Workspace;
  capabilities: string[];
}

export interface MyWorkspaces {
  current_workspace_id: string | null;
  memberships: Membership[];
}
