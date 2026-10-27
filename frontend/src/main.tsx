import { Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { flushSync } from "react-dom";
import { WorkspaceShell } from "./components/WorkspaceShell";
import {
  CustomersPage,
  type CustomerCommands,
} from "./modules/customers/CustomersPage";
import type { Bridge, ShellPage } from "./types";
import "./styles.css";
class ScreenBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Workspace render failed", error, info.componentStack);
  }
  render() {
    return this.state.failed ? (
      <div role="alert" className="modern-error">
        This screen could not load. Reload the page to try again.
      </div>
    ) : (
      this.props.children
    );
  }
}
let root: Root | undefined;
const commands: CustomerCommands = { open: () => {}, save: async () => {} };
window.ModernWorkspace = {
  dispose() {
    root?.unmount();
    root = undefined;
  },
  render(page: ShellPage, bridge: Bridge) {
    let container = document.getElementById("workspace-root");
    if (!container) {
      container = document.createElement("div");
      container.id = "workspace-root";
      document.body.appendChild(container);
    }
    if (!root) root = createRoot(container);
    // Only the compatibility boundary is synchronous: legacy renderers bind controls immediately.
    flushSync(() =>
      root!.render(
        <ScreenBoundary>
          <WorkspaceShell page={page} bridge={bridge}>
            {page.native === "customers" ? (
              <CustomersPage bridge={bridge} commands={commands} />
            ) : (
              <div
                className="legacy-screen"
                dangerouslySetInnerHTML={{ __html: page.html }}
              />
            )}
          </WorkspaceShell>
        </ScreenBoundary>,
      ),
    );
  },
  openCustomer: () => commands.open(),
  saveCustomer: () => commands.save(),
};
