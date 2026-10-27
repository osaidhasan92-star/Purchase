import { Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { flushSync } from "react-dom";
import { TradePage, TradeDashboard } from "./modules/trade/TradePage";
import { CrmDashboard } from "./modules/CrmDashboard";
import { WorkspaceShell } from "./components/WorkspaceShell";
import {
  CustomersPage,
  type CustomerCommands,
} from "./modules/customers/CustomersPage";
import { MastersPage, type MasterCommands } from "./modules/MastersPage";
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
const masterCommands: MasterCommands = { open: () => {}, save: async () => {} };
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
            {page.native === "trade" && page.tradeResource ? (
              <TradePage
                key={page.tradeResource}
                resource={page.tradeResource}
                bridge={bridge}
                user={page.user}
              />
            ) : page.native === "trade-dashboard" && page.tradeArea ? (
              <TradeDashboard bridge={bridge} area={page.tradeArea} />
            ) : page.native === "crm-dashboard" ? (
              <CrmDashboard bridge={bridge} />
            ) : page.native === "customers" ? (
              <CustomersPage bridge={bridge} commands={commands} />
            ) : page.native === "vendors" ||
              page.native === "products" ||
              page.native === "leads" ||
              page.native === "reminders" ? (
              <MastersPage
                key={page.native}
                kind={page.native}
                bridge={bridge}
                commands={masterCommands}
              />
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
  openMaster: (id) => masterCommands.open(id),
  saveMaster: () => masterCommands.save(),
  openCustomer: () => commands.open(),
  saveCustomer: () => commands.save(),
};
