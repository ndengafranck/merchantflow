import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import { workspaceApi } from "../api/endpoints";
import type { Membership } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

type Load =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; membership: Membership };

/**
 * Placeholder dashboard. It makes one real workspace-scoped request so the
 * whole path (session cookie, membership check, tenant scoping) is exercised;
 * business figures arrive with the catalogue and order milestones.
 */
export function DashboardPage({ workspaceId }: { workspaceId: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  const fetchWorkspace = useCallback(
    (isCurrent: () => boolean = () => true) => {
      workspaceApi
        .detail(workspaceId)
        .then((membership) => isCurrent() && setLoad({ status: "ready", membership }))
        .catch(
          (error: unknown) =>
            isCurrent() && setLoad({ status: "error", message: errorMessage(error) }),
        );
    },
    [workspaceId],
  );

  useEffect(() => {
    let current = true;
    fetchWorkspace(() => current);
    return () => {
      current = false;
    };
  }, [fetchWorkspace]);

  if (load.status === "loading") return <LoadingState label="Loading workspace…" />;
  if (load.status === "error") {
    return (
      <ErrorState
        message={load.message}
        onRetry={() => {
          setLoad({ status: "loading" });
          fetchWorkspace();
        }}
      />
    );
  }

  const { membership } = load;
  return (
    <>
      <h1>Dashboard</h1>
      <dl className="stat-grid">
        <div className="card stat">
          <dt>Workspace</dt>
          <dd>{membership.workspace.name}</dd>
        </div>
        <div className="card stat">
          <dt>Your role</dt>
          <dd className="capitalize">{membership.role}</dd>
        </div>
        <div className="card stat">
          <dt>Currency</dt>
          <dd>{membership.workspace.currency}</dd>
        </div>
      </dl>
      <div className="card">
        <EmptyState title="No activity yet">
          <p>Products, orders and commissions will appear here once those features are released.</p>
        </EmptyState>
      </div>
    </>
  );
}
