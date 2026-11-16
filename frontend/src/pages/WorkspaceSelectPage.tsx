import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { Membership, User } from "../api/types";
import { EmptyState, FullPage } from "../components/States";
import { useSession, workspacePath } from "../session/SessionContext";

interface Props {
  user: User;
  memberships: Membership[];
  lastWorkspaceId: string | null;
}

export function WorkspaceSelectPage({ user, memberships, lastWorkspaceId }: Props) {
  const { logout } = useSession();
  const [error, setError] = useState<string | null>(null);

  async function handleLogout() {
    setError(null);
    try {
      await logout();
    } catch (caught) {
      setError(`Could not sign out: ${errorMessage(caught)}`);
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
                {/* A real link: it can be opened in a new tab and lands in history. */}
                <Link
                  className="workspace-option"
                  to={workspacePath(membership.workspace.id)}
                  aria-current={membership.workspace.id === lastWorkspaceId || undefined}
                >
                  <span className="workspace-option-name">{membership.workspace.name}</span>
                  <span className="badge">{membership.role}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        <button type="button" className="button button-secondary" onClick={handleLogout}>
          Sign out
        </button>
      </section>
    </FullPage>
  );
}
