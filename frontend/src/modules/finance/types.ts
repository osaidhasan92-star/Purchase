export type FinanceView =
  "accounting" | "accounts" | "journals" | "reports" | "aged" | "bank";
export interface Row {
  id: number | string;
  version?: string;
  [key: string]: unknown;
}
export interface Journal extends Row {
  id: number;
  number: string;
  memo: string;
  date: string;
  source: string;
  status: string;
  version: string;
  actions: string[];
  lines: Line[];
  sourceLink?: { href: string; label: string } | null;
}
export interface Line {
  id?: number;
  account: string;
  debit: string;
  credit: string;
  partner: string;
  dueDate?: string | null;
  openAmount?: string;
  version?: string;
}
export interface PageData {
  items: Row[];
  total: number;
  page: number;
  pageSize: number;
}
export interface Summary {
  [key: string]: string | unknown;
  periodLock: { date: string | null; version: string };
}
export const titles: Record<FinanceView, string> = {
  accounting: "Accounting & Finance",
  accounts: "Chart of Accounts",
  journals: "Journal Entries",
  reports: "Financial Reports",
  aged: "Receivables & Payables",
  bank: "Bank Reconciliation",
};
export const money = (v: unknown) =>
  Number(v || 0).toLocaleString("en-PK", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
export const str = (v: unknown) =>
  v === null || v === undefined ? "—" : String(v);
export const today = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Karachi" });
export const requestKey = () =>
  "finance-" + Date.now() + "-" + Math.random().toString(36).slice(2);
