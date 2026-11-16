import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { Membership, User } from "../api/types";
import { EmptyState, FullPage } from "../components/States";
import { useSession } from "../session/SessionContext";

interface Props {
  user: User;
  memberships: Membership[];
  currentWorkspaceId: string | null;
}

export function WorkspaceSelectPage({ user, memberships, currentWorkspaceId }: Props) {
  const { selectWorkspace, logout } = useSession();
  const navigate = useNavigate();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function choose(workspaceId: string) {
    setPendingId(workspaceId);
    setError(null);
    try {
      await selectWorkspace(workspaceId);
      navigate("/", { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
      setPendingId(null);
    }
  }

  return (
    <FullPage>
      <section className="card auth-card">
        <h1>Choose a workspace</h1>
        <p className="muted">Signed in as {user.email}</p>

        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}

        {memberships.length === 0 ? (
          <EmptyState title="No workspaces yet">
            <p>
              Your account is not a member of any workspace. Ask the shop owner to add you, then
              sign in again.
            </p>
          </EmptyState>
        ) : (
          <ul className="workspace-list">
            {memberships.map((membership) => (
              <li key={membership.id}>
                <button
                  type="button"
                  className="workspace-option"
                  onClick={() => choose(membership.workspace.id)}
                  disabled={pendingId !== null}
                  aria-current={membership.workspace.id === currentWorkspaceId || undefined}
                >
                  <span className="workspace-option-name">{membership.workspace.name}</span>
                  <span className="badge">
                    {pendingId === membership.workspace.id ? "Opening…" : membership.role}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <button type="button" className="button button-secondary" onClick={() => void logout()}>
          Sign out
        </button>
      </section>
    </FullPage>
  );
}
