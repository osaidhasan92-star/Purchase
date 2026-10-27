import { useEffect, useState, type ReactNode, type MouseEvent } from "react";
import type { Bridge, ShellPage } from "../types";
export function WorkspaceShell({
  page,
  bridge,
  children,
}: {
  page: ShellPage;
  bridge: Bridge;
  children: ReactNode;
}) {
  const [menu, setMenu] = useState(false),
    [mobile, setMobile] = useState(false),
    [logoFailed, setLogoFailed] = useState(false);
  useEffect(() => {
    const close = () => setMenu(false);
    document.addEventListener("click", close);
    window.addEventListener("workspace:close-menu", close);
    return () => {
      document.removeEventListener("click", close);
      window.removeEventListener("workspace:close-menu", close);
    };
  }, []);
  const navigate = (event: MouseEvent<HTMLAnchorElement>, href: string) => {
    if (
      event.defaultPrevented ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
      event.button !== 0
    )
      return;
    event.preventDefault();
    bridge.navigate(href);
  };
  const action = (run: () => void) => {
    setMenu(false);
    run();
  };
  return (
    <>
      <div
        className="app module-app"
        data-module={page.module}
        data-frontend="react"
      >
        <aside className={"sidebar" + (mobile ? " open" : "")} id="side">
          <div className="side-brand">
            <>
              {logoFailed ? (
                <span className="modern-brand-fallback">
                  {page.companyName}
                </span>
              ) : (
                <img
                  src={page.logo}
                  alt={page.companyName}
                  onError={() => setLogoFailed(true)}
                />
              )}
            </>
          </div>
          <div className="sidebar-scroll">
            <div className="nav-title">MODULES</div>
            {page.workspaces.map((workspace) => (
              <a
                key={workspace.id}
                className={
                  "nav-item" + (workspace.id === page.module ? " active" : "")
                }
                aria-current={workspace.id === page.module ? "page" : undefined}
                href={workspace.href}
                data-workspace={workspace.id}
                onClick={(event) => navigate(event, workspace.href)}
              >
                <i className={"ti " + workspace.icon} />
                <span>{workspace.label}</span>
              </a>
            ))}
          </div>
          <div className="module-sidebar-foot">Pakistan · PKR · WH / Stock</div>
        </aside>
        <main className="main">
          <header className="top module-header">
            <button
              className="mobile-menu"
              type="button"
              aria-label="Open modules"
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div className="module-page-heading">
              <span className="module-eyebrow">{page.label}</span>
              <h1>{page.title}</h1>
              <p>{page.subtitle}</p>
            </div>
            <div
              className="user user-menu-wrap"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                className="user-menu-trigger"
                type="button"
                aria-expanded={menu}
                onClick={() => setMenu(!menu)}
              >
                <span>{page.user.name}</span>
                <b>
                  {page.user.name
                    .split(" ")
                    .map((part) => part[0])
                    .join("")
                    .slice(0, 2)
                    .toUpperCase()}
                </b>
                <i className="ti ti-chevron-down user-menu-arrow" />
              </button>
              <div
                className={"user-dropdown" + (menu ? " show" : "")}
                id="user-dropdown"
              >
                <div className="user-dropdown-head">
                  <b>{page.user.name}</b>
                  <span>{page.user.role}</span>
                </div>
                <div className="user-dropdown-divider" />
                {page.user.role === "Admin" && (
                  <button
                    type="button"
                    data-action="company-profile"
                    onClick={() => action(bridge.companyProfile)}
                  >
                    <i className="ti ti-building" />
                    <span>Company profile</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => action(bridge.changePassword)}
                >
                  <i className="ti ti-key" />
                  <span>Change Password</span>
                </button>
                <button type="button" onClick={() => action(bridge.logout)}>
                  <i className="ti ti-logout" />
                  <span>Sign out</span>
                </button>
              </div>
            </div>
          </header>
          <section className="content module-content">
            {page.module !== "overview" && (
              <div className="module-navigation">
                <nav
                  className="module-tabs"
                  aria-label={page.label + " submenu"}
                >
                  {page.tabs.map((tab) => (
                    <a
                      key={tab.href}
                      href={tab.href}
                      className={"module-tab" + (tab.active ? " active" : "")}
                      aria-current={tab.active ? "page" : undefined}
                      onClick={(event) => navigate(event, tab.href)}
                    >
                      {tab.label}
                    </a>
                  ))}
                </nav>
                {page.flow && <div className="module-flow">{page.flow}</div>}
              </div>
            )}
            <div className="module-body">{children}</div>
          </section>
        </main>
      </div>
      <div id="toast" />
      <div dangerouslySetInnerHTML={{ __html: page.menuStyle }} />
    </>
  );
}
