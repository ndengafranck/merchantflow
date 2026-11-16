import { createContext, useContext } from "react";
import type { Membership, User } from "../api/types";

export type SessionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "anonymous" }
  | {
      status: "authenticated";
      user: User;
      memberships: Membership[];
      currentWorkspaceId: string | null;
    };

export interface SessionActions {
  /** Re-read the session from the server (used by "Try again"). */
  reload: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  selectWorkspace: (workspaceId: string) => Promise<void>;
}

export interface SessionContextValue extends SessionActions {
  state: SessionState;
}

export const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>.");
  return value;
}

/** The membership for the selected workspace, if the user is in one. */
export function currentMembership(state: SessionState): Membership | null {
  if (state.status !== "authenticated" || !state.currentWorkspaceId) return null;
  return state.memberships.find((m) => m.workspace.id === state.currentWorkspaceId) ?? null;
}
