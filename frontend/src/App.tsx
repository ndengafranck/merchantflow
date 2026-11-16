import { Navigate, Route, Routes, useLocation, useParams, type Location } from "react-router-dom";
import { ErrorState, FullPage, LoadingState } from "./components/States";
import { WorkspaceRoute } from "./components/WorkspaceRoute";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { WorkspaceSelectPage } from "./pages/WorkspaceSelectPage";
import { findMembership, useSession, workspacePath } from "./session/SessionContext";
import type { Membership } from "./api/types";

interface LoginRedirectState {
  from?: Pick<Location, "pathname" | "search">;
}

/** Where "/" leads: back to the last workspace, the only one, or the chooser. */
function landingPath(memberships: Membership[], lastWorkspaceId: string | null): string {
  const last = findMembership(memberships, lastWorkspaceId);
  if (last) return workspacePath(last.workspace.id);
  const only = memberships.length === 1 ? memberships[0] : undefined;
  return only ? workspacePath(only.workspace.id) : "/workspaces";
}

/** An unknown page inside a workspace falls back to that workspace's dashboard. */
function WorkspaceHomeRedirect() {
  const { workspaceId = "" } = useParams();
  return <Navigate to={workspacePath(workspaceId)} replace />;
}

export function App() {
  const { state, reload } = useSession();
  const location = useLocation();

  if (state.status === "loading") {
    return (
      <FullPage>
        <LoadingState label="Starting MerchantFlow…" />
      </FullPage>
    );
  }
  if (state.status === "error") {
    return (
      <FullPage>
        <ErrorState message={state.message} onRetry={() => void reload()} />
      </FullPage>
    );
  }
  if (state.status === "anonymous") {
    // Remember the page that was asked for, so signing in returns to it.
    const redirectState: LoginRedirectState = state.signedOut
      ? {}
      : { from: { pathname: location.pathname, search: location.search } };
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace state={redirectState} />} />
      </Routes>
    );
  }

  const { user, memberships, lastWorkspaceId } = state;
  const from = (location.state as LoginRedirectState | null)?.from;
  const afterLogin = from ? `${from.pathname}${from.search}` : "/";
  const landing = landingPath(memberships, lastWorkspaceId);
  const workspaceProps = { user, memberships, lastWorkspaceId };

  return (
    <Routes>
      <Route path="/login" element={<Navigate to={afterLogin} replace />} />
      <Route path="/" element={<Navigate to={landing} replace />} />
      <Route path="/workspaces" element={<WorkspaceSelectPage {...workspaceProps} />} />
      <Route path="/w/:workspaceId" element={<WorkspaceRoute {...workspaceProps} />}>
        <Route index element={<DashboardPage />} />
        <Route path="*" element={<WorkspaceHomeRedirect />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
