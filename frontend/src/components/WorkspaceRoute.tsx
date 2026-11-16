import { useEffect } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";
import type { Membership, User } from "../api/types";
import { findMembership, useSession } from "../session/SessionContext";
import { AppShell } from "./AppShell";
import { EmptyState, FullPage } from "./States";

interface Props {
  user: User;
  memberships: Membership[];
  lastWorkspaceId: string | null;
}

/**
 * Everything under /w/:workspaceId. The URL is the single source of truth for
 * which workspace a tab shows, so tabs cannot affect each other, links can be
 * shared and the back button works across a workspace switch.
 */
export function WorkspaceRoute({ user, memberships, lastWorkspaceId }: Props) {
  const { workspaceId } = useParams();
  const { rememberWorkspace, reload } = useSession();
  const membership = findMembership(memberships, workspaceId);
  const enteredId = membership?.workspace.id;

  useEffect(() => {
    if (enteredId && enteredId !== lastWorkspaceId) rememberWorkspace(enteredId);
  }, [enteredId, lastWorkspaceId, rememberWorkspace]);

  if (!membership) {
    return (
      <FullPage>
        <section className="card auth-card">
          <EmptyState title="Workspace not available">
            <p>This workspace does not exist, or your account is not a member of it.</p>
          </EmptyState>
          <Link className="button button-primary button-link" to="/workspaces">
            Choose a workspace
          </Link>
          <button type="button" className="button button-secondary" onClick={() => void reload()}>
            Check again
          </button>
        </section>
      </FullPage>
    );
  }

  // Keyed by workspace: moving to another workspace discards every piece of
  // state that was loaded for the previous one.
  return (
    <AppShell
      key={membership.workspace.id}
      user={user}
      membership={membership}
      canSwitchWorkspace={memberships.length > 1}
    />
  );
}

/** The membership for the workspace in the URL, for screens inside the shell. */
export function useWorkspaceMembership(): Membership {
  return useOutletContext<Membership>();
}
