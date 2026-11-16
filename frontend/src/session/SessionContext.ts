import { createContext, useContext } from "react";
import type { Membership, User } from "../api/types";

export type SessionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  // signedOut is true only after the user chose to sign out, so the next
  // person to sign in on this browser is not sent to the previous person's page.
  | { status: "anonymous"; signedOut: boolean }
  | {
      status: "authenticated";
      user: User;
      memberships: Membership[];
      /** Where this session last worked. Used only to pick a landing page. */
      lastWorkspaceId: string | null;
    };

export interface SessionActions {
  /** Re-read the session from the server (used by "Try again"). */
  reload: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Record the workspace being viewed. Never changes what any tab shows. */
  rememberWorkspace: (workspaceId: string) => void;
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

export function findMembership(
  memberships: Membership[],
  workspaceId: string | null | undefined,
): Membership | null {
  if (!workspaceId) return null;
  return memberships.find((m) => m.workspace.id === workspaceId) ?? null;
}

/** Path of a screen inside a workspace. The workspace always comes from the URL. */
export function workspacePath(workspaceId: string, rest = ""): string {
  return `/w/${workspaceId}${rest}`;
}
