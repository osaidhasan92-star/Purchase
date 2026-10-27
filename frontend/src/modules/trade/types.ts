export type Resource =
  | "requests"
  | "rfqs"
  | "quotations"
  | "comparisons"
  | "orders"
  | "receipts"
  | "invoices"
  | "payments"
  | "salesQuotations"
  | "salesOrders"
  | "deliveries"
  | "customerInvoices"
  | "customerPayments";
export interface TradeLine {
  productId?: string | number;
  productName?: string;
  description?: string;
  unit?: string;
  quantity?: number;
  rate?: number;
  quotedRate?: number;
  taxPercent?: number;
  discountPercent?: number;
  subtotal?: number;
  taxAmount?: number;
  total?: number;
  lineIndex?: number;
  receivedQty?: number;
  acceptedQty?: number;
  rejectedQty?: number;
  deliveredQty?: number;
  inspection?: string;
  remark?: string;
  [key: string]: unknown;
}
export interface TradeRecord {
  id: string | number;
  version: string;
  status: string;
  actions?: string[];
  items?: TradeLine[];
  lineItems?: TradeLine[];
  vendors?: { id: string | number; name: string }[];
  [key: string]: unknown;
}
export interface OrderLineContext {
  lineIndex: number;
  productId: string | number;
  productName: string;
  unit: string;
  ordered: number;
  received: number;
  remaining: number;
  invoiceRemaining: number;
  acceptedUnbilled: number;
  rate: number;
  taxPercent: number;
  discountPercent: number;
}
export interface TradeContext {
  balance?: number;
  lines?: OrderLineContext[];
  sourceLines?: TradeLine[];
  sourceNumber?: string;
  legacyInvoiceCount?: number;
  unbilledValue?: number;
}
export interface Detail {
  record: TradeRecord;
  context: TradeContext;
}
export interface TradePageData {
  items: TradeRecord[];
  total: number;
  page: number;
  pageSize: number;
}
export interface ResourceConfig {
  label: string;
  singular: string;
  view: string;
  module: string;
  number: string;
  date: string;
  area: "sales" | "purchase";
  source?: { resource: Resource; field: string; label: string; status: string };
}
export const configs: Record<Resource, ResourceConfig> = {
  requests: {
    label: "Purchase Requests",
    singular: "Purchase Request",
    view: "requests",
    module: "requests",
    number: "requestNo",
    date: "date",
    area: "purchase",
  },
  rfqs: {
    label: "Requests for Quotation",
    singular: "RFQ",
    view: "rfqs",
    module: "rfqs",
    number: "rfqNo",
    date: "issueDate",
    area: "purchase",
    source: {
      resource: "requests",
      field: "requestId",
      label: "Approved Purchase Request",
      status: "Approved",
    },
  },
  quotations: {
    label: "Vendor Quotations",
    singular: "Vendor Quotation",
    view: "quotations",
    module: "quotations",
    number: "quotationNo",
    date: "quoteDate",
    area: "purchase",
    source: {
      resource: "rfqs",
      field: "rfqId",
      label: "RFQ",
      status: "Sent|Response Received",
    },
  },
  comparisons: {
    label: "Quotation Comparison",
    singular: "Award",
    view: "comparison",
    module: "comparison",
    number: "selectedQuotationNo",
    date: "comparedAt",
    area: "purchase",
  },
  orders: {
    label: "Purchase Orders",
    singular: "Purchase Order",
    view: "orders",
    module: "orders",
    number: "poNo",
    date: "poDate",
    area: "purchase",
    source: {
      resource: "quotations",
      field: "quotationId",
      label: "Awarded Vendor Quotation (optional for direct PO)",
      status: "Selected",
    },
  },
  receipts: {
    label: "Goods Receipts",
    singular: "Goods Receipt",
    view: "receipts",
    module: "receipts",
    number: "grnNo",
    date: "receivedDate",
    area: "purchase",
    source: {
      resource: "orders",
      field: "poId",
      label: "Purchase Order",
      status: "Approved|Sent to Vendor|Partially Received",
    },
  },
  invoices: {
    label: "Vendor Bills",
    singular: "Vendor Bill",
    view: "invoices",
    module: "invoices",
    number: "invoiceNo",
    date: "invoiceDate",
    area: "purchase",
    source: {
      resource: "orders",
      field: "poId",
      label: "Purchase Order",
      status: "Approved|Sent to Vendor|Partially Received|Received",
    },
  },
  payments: {
    label: "Supplier Payments",
    singular: "Supplier Payment",
    view: "payments",
    module: "payments",
    number: "paymentNo",
    date: "paymentDate",
    area: "purchase",
    source: {
      resource: "invoices",
      field: "invoiceId",
      label: "Approved Vendor Bill",
      status: "Approved|Partially Paid",
    },
  },
  salesQuotations: {
    label: "Sales Quotations",
    singular: "Sales Quotation",
    view: "sales-quotations",
    module: "sales_quotations",
    number: "quotationNo",
    date: "quotationDate",
    area: "sales",
  },
  salesOrders: {
    label: "Sales Orders",
    singular: "Sales Order",
    view: "sales-orders",
    module: "sales_orders",
    number: "orderNo",
    date: "orderDate",
    area: "sales",
    source: {
      resource: "salesQuotations",
      field: "quotationId",
      label: "Accepted Sales Quotation",
      status: "Accepted",
    },
  },
  deliveries: {
    label: "Delivery Challans",
    singular: "Delivery",
    view: "sales-deliveries",
    module: "sales_deliveries",
    number: "deliveryNo",
    date: "deliveryDate",
    area: "sales",
    source: {
      resource: "salesOrders",
      field: "orderId",
      label: "Sales Order",
      status: "Confirmed|Partially Delivered|Delivered",
    },
  },
  customerInvoices: {
    label: "Customer Invoices",
    singular: "Customer Invoice",
    view: "sales-invoices",
    module: "sales_invoices",
    number: "invoiceNo",
    date: "invoiceDate",
    area: "sales",
    source: {
      resource: "salesOrders",
      field: "orderId",
      label: "Sales Order",
      status: "Confirmed|Partially Delivered|Delivered",
    },
  },
  customerPayments: {
    label: "Customer Payments",
    singular: "Customer Payment",
    view: "sales-payments",
    module: "sales_payments",
    number: "paymentNo",
    date: "paymentDate",
    area: "sales",
    source: {
      resource: "customerInvoices",
      field: "invoiceId",
      label: "Posted Customer Invoice",
      status: "Posted|Partially Paid",
    },
  },
};
export const actionLabels: Record<string, string> = {
  submit: "Submit for Approval",
  approve: "Approve",
  reject: "Reject",
  send: "Mark Sent",
  accept: "Record Acceptance",
  expire: "Mark Expired",
  deliver: "Validate Delivery",
  cancel: "Cancel Document",
  match: "Check Match",
  award: "Award Quotation",
  clear: "Clear Award",
};
export const str = (value: unknown) =>
  value === null || value === undefined ? "" : String(value);
export const money = (value: unknown) =>
  "Rs " +
  Number(value || 0).toLocaleString("en-PK", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
export const keyFor = (prefix: string) =>
  prefix + "-" + Date.now() + "-" + Math.random().toString(36).slice(2);
export const route = (resource: Resource, sourceId?: string | number) =>
  "erp.html?" +
  new URLSearchParams({
    view: configs[resource].view,
    module: configs[resource].area === "purchase" ? "purchase" : "sales",
    ...(sourceId ? { sourceId: String(sourceId) } : {}),
  });

export const economicLines = (record: TradeRecord): TradeLine[] =>
  Array.isArray(record.lineItems)
    ? record.lineItems
    : Array.isArray(record.items)
      ? record.items
      : [];
