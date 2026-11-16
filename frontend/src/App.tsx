import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ErrorState, FullPage, LoadingState } from "./components/States";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { WorkspaceSelectPage } from "./pages/WorkspaceSelectPage";
import { currentMembership, useSession } from "./session/SessionContext";

export function App() {
  const { state, reload } = useSession();

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
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  const membership = currentMembership(state);
  const selector = (
    <WorkspaceSelectPage
      user={state.user}
      memberships={state.memberships}
      currentWorkspaceId={state.currentWorkspaceId}
    />
  );

  return (
    <Routes>
      <Route path="/workspaces" element={selector} />
      {membership ? (
        <Route
          element={
            <AppShell
              user={state.user}
              membership={membership}
              canSwitchWorkspace={state.memberships.length > 1}
            />
          }
        >
          {/* Keyed so switching workspace discards the previous workspace's data. */}
          <Route
            index
            element={
              <DashboardPage key={membership.workspace.id} workspaceId={membership.workspace.id} />
            }
          />
        </Route>
      ) : (
        <Route index element={<Navigate to="/workspaces" replace />} />
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
