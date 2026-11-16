import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { Membership, User } from "../api/types";
import { useSession, workspacePath } from "../session/SessionContext";

const ROLE_LABELS: Record<Membership["role"], string> = {
  owner: "Owner",
  manager: "Manager",
  attendant: "Attendant",
  affiliate: "Affiliate",
};

interface Props {
  user: User;
  membership: Membership;
  canSwitchWorkspace: boolean;
}

export function AppShell({ user, membership, canSwitchWorkspace }: Props) {
  const { logout } = useSession();
  const [navOpen, setNavOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);

  async function handleLogout() {
    setSigningOut(true);
    setSignOutError(null);
    try {
      await logout();
    } catch (error) {
      setSignOutError(errorMessage(error));
      setSigningOut(false);
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <button
          type="button"
          className="nav-toggle"
          aria-label="Toggle navigation"
          aria-expanded={navOpen}
          aria-controls="primary-nav"
          onClick={() => setNavOpen((open) => !open)}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <div className="topbar-context">
          <span className="brand">MerchantFlow</span>
          <span className="workspace-name">{membership.workspace.name}</span>
        </div>
        <div className="topbar-user">
          <span className="user-name">
            {user.full_name}
            <span className="badge">{ROLE_LABELS[membership.role]}</span>
          </span>
          <button
            type="button"
            className="button button-secondary"
            onClick={handleLogout}
            disabled={signingOut}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </header>

      <nav id="primary-nav" className={navOpen ? "sidebar sidebar-open" : "sidebar"}>
        <NavLink
          to={workspacePath(membership.workspace.id)}
          end
          className="nav-link"
          onClick={() => setNavOpen(false)}
        >
          Dashboard
        </NavLink>
        {canSwitchWorkspace && (
          <Link to="/workspaces" className="nav-link nav-link-quiet">
            Switch workspace
          </Link>
        )}
      </nav>

      <main className="content">
        {signOutError && (
          <p className="alert" role="alert">
            Could not sign out: {signOutError}
          </p>
        )}
        <Outlet context={membership} />
      </main>
    </div>
  );
}
