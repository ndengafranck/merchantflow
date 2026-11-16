import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, errorMessage, setUnauthorizedHandler } from "../api/client";
import { authApi, workspaceApi } from "../api/endpoints";
import type { User } from "../api/types";
import { SessionContext, type SessionContextValue, type SessionState } from "./SessionContext";

/** Loads who the user is and which workspaces they can enter. */
async function loadSession(knownUser?: User): Promise<SessionState> {
  let user = knownUser;
  if (!user) {
    try {
      user = await authApi.me();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return { status: "anonymous" };
      throw error;
    }
  }
  const mine = await workspaceApi.mine();
  let currentWorkspaceId = mine.current_workspace_id;
  // Someone with a single workspace has nothing to choose.
  const only = mine.memberships.length === 1 ? mine.memberships[0] : undefined;
  if (!currentWorkspaceId && only) {
    await workspaceApi.select(only.workspace.id);
    currentWorkspaceId = only.workspace.id;
  }
  return { status: "authenticated", user, memberships: mine.memberships, currentWorkspaceId };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  const reload = useCallback(async () => {
    setState({ status: "loading" });
    try {
      setState(await loadSession());
    } catch (error) {
      setState({ status: "error", message: errorMessage(error) });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadSession()
      .then((next) => !cancelled && setState(next))
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(error) });
      });
    // If the server ends the session, every screen falls back to the login page.
    setUnauthorizedHandler(() => setState({ status: "anonymous" }));
    return () => {
      cancelled = true;
      setUnauthorizedHandler(null);
    };
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      state,
      reload,
      // Errors from these actions propagate to the calling screen, which
      // shows them next to the control the user just used.
      login: async (email, password) => {
        const user = await authApi.login(email, password);
        setState(await loadSession(user));
      },
      logout: async () => {
        await authApi.logout();
        setState({ status: "anonymous" });
      },
      selectWorkspace: async (workspaceId) => {
        await workspaceApi.select(workspaceId);
        setState((previous) =>
          previous.status === "authenticated"
            ? { ...previous, currentWorkspaceId: workspaceId }
            : previous,
        );
      },
    }),
    [state, reload],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
