export interface User {
  id: string;
  name: string;
  role: string;
  managerId?: string | null;
}
export interface Tab {
  label: string;
  href: string;
  active: boolean;
}
export interface Workspace {
  id: string;
  label: string;
  icon: string;
  href: string;
}
export interface ShellPage {
  module: string;
  label: string;
  title: string;
  subtitle: string;
  flow: string;
  tabs: Tab[];
  workspaces: Workspace[];
  user: User;
  companyName: string;
  logo: string;
  menuStyle: string;
  html: string;
  productionView?: import("./modules/production/ProductionPage").ProductionView;
  inventoryView?: "inventory" | "stock-moves";
  financeView?: import("./modules/finance/types").FinanceView;
  hrResource?: import("./modules/hr/config").Resource;
  hrReports?: boolean;
  tradeResource?: import("./modules/trade/types").Resource;
  tradeArea?: "sales" | "purchase";
  native?:
    | "production"
    | "inventory"
    | "finance"
    | "hr"
    | "hr-dashboard"
    | "trade"
    | "trade-dashboard"
    | "crm-dashboard"
    | "customers"
    | "vendors"
    | "products"
    | "leads"
    | "reminders";
}
export interface Bridge {
  request<T>(path: string, options?: RequestInit): Promise<T>;
  can(module: string, action?: string): boolean;
  navigate(href: string): void;
  toast(message: string): void;
  changePassword(): void;
  companyProfile(): void;
  logout(): void;
  cacheCustomers(items: Customer[]): void;
  cacheRecords(
    kind: import("./modules/MastersPage").MasterKind,
    items: import("./modules/MastersPage").MasterRecord[],
  ): void;
}
export interface Customer {
  id: number | string;
  code: string;
  name: string;
  contact: string;
  phone: string;
  email: string;
  category: string;
  paymentTerms: string;
  creditLimit: number;
  status: string;
  address: string;
  version: string;
  createdBy?: string | null;
}
export type CustomerValues = Pick<
  Customer,
  | "name"
  | "contact"
  | "phone"
  | "email"
  | "category"
  | "paymentTerms"
  | "creditLimit"
  | "status"
  | "address"
>;
export interface CustomerDetails {
  customer: Customer;
  orderTotal: number;
  orders: {
    id: string | number;
    orderNo: string;
    orderDate: string;
    total: number;
    status: string;
  }[];
}
export interface CustomerPage {
  items: Customer[];
  total: number;
  page: number;
  pageSize: number;
}
export interface ModernRuntime {
  dispose(): void;
  render(page: ShellPage, bridge: Bridge): void;
  openMaster(id?: string | number): void;
  saveMaster(): Promise<void>;
  openCustomer(): void;
  saveCustomer(): Promise<void>;
}
declare global {
  interface Window {
    ModernWorkspace?: ModernRuntime;
  }
}
