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
      if (error instanceof ApiError && error.status === 401) {
        return { status: "anonymous", signedOut: false };
      }
      throw error;
    }
  }
  const mine = await workspaceApi.mine();
  return {
    status: "authenticated",
    user,
    memberships: mine.memberships,
    lastWorkspaceId: mine.current_workspace_id,
  };
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
    setUnauthorizedHandler(() => setState({ status: "anonymous", signedOut: false }));
    return () => {
      cancelled = true;
      setUnauthorizedHandler(null);
    };
  }, []);

  const rememberWorkspace = useCallback((workspaceId: string) => {
    setState((previous) =>
      previous.status === "authenticated" && previous.lastWorkspaceId !== workspaceId
        ? { ...previous, lastWorkspaceId: workspaceId }
        : previous,
    );
    // Best effort: this is only a hint for the next sign-in, so a failure
    // must not disturb the screen the user is looking at.
    workspaceApi.remember(workspaceId).catch(() => undefined);
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      state,
      reload,
      rememberWorkspace,
      // Errors from these actions propagate to the calling screen, which
      // shows them next to the control the user just used.
      login: async (email, password) => {
        const user = await authApi.login(email, password);
        setState(await loadSession(user));
      },
      logout: async () => {
        await authApi.logout();
        setState({ status: "anonymous", signedOut: true });
      },
    }),
    [state, reload, rememberWorkspace],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
