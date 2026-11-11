"""ERP operations the assistant can hand to the normal workspace forms."""

from urllib.parse import urlencode

from flask import g

from .app import app_document
from .permissions import allowed

# Each entry uses the same module and action permissions as its destination.
# Only fixed workspace routes are returned to the browser or chosen by the model.
PROCESS_FORMS = (
    ("purchase-request", "Purchasing", "New purchase request", "requests", "requests", "create", "new"),
    ("rfq", "Purchasing", "Create RFQ from an approved purchase request", "rfqs", "rfqs", "create", "new"),
    ("rfq-register", "Purchasing", "Review RFQs or mark a draft RFQ as sent", "rfqs", "rfqs", "edit", ""),
    ("supplier-quote", "Purchasing", "Record supplier quotation", "quotations", "quotations", "create", "new"),
    ("compare-quotes", "Purchasing", "Compare or award supplier quotations", "comparison", "comparison", "view", ""),
    ("purchase-order", "Purchasing", "Create purchase order", "orders", "orders", "create", "new"),
    ("purchase-orders", "Purchasing", "Manage purchase orders and remaining quantities", "orders", "orders", "edit", ""),
    ("goods-receipt", "Purchasing", "Receive goods from a purchase order", "receipts", "receipts", "create", "new"),
    ("vendor-bill", "Accounting", "Create vendor bill", "invoices", "invoices", "create", "new"),
    ("supplier-payment", "Accounting", "Register supplier payment", "payments", "payments", "create", "new"),
    ("vendor", "Purchasing", "Add vendor", "vendors", "vendors", "create", "new"),
    ("customer", "Sales & CRM", "Add customer", "customers", "sales_customers", "create", "new"),
    ("lead", "Sales & CRM", "Add CRM lead", "leads", "leads", "create", "new"),
    ("reminder", "Sales & CRM", "Schedule CRM follow-up", "reminders", "reminders", "create", "new"),
    ("sales-quote", "Sales & CRM", "Create sales quotation", "sales-quotations", "sales_quotations", "create", "new"),
    ("sales-quotes", "Sales & CRM", "Send, accept or manage sales quotations", "sales-quotations", "sales_quotations", "edit", ""),
    ("sales-order", "Sales & CRM", "Create sales order", "sales-orders", "sales_orders", "create", "new"),
    ("sales-orders", "Sales & CRM", "Manage sales orders and reservations", "sales-orders", "sales_orders", "edit", ""),
    ("delivery", "Inventory", "Create delivery challan", "sales-deliveries", "sales_deliveries", "create", "new"),
    ("customer-invoice", "Accounting", "Create customer invoice", "sales-invoices", "sales_invoices", "create", "new"),
    ("customer-payment", "Accounting", "Register customer payment", "sales-payments", "sales_payments", "create", "new"),
    ("product", "Inventory", "Add product or service", "products", "products", "create", "new"),
    ("stock-adjustment", "Inventory", "Adjust stock", "inventory", "inventory", "approve", "adjust"),
    ("stock-scrap", "Inventory", "Record scrap", "inventory", "inventory", "approve", "scrap"),
    ("stock-return", "Inventory", "Return stock from an existing movement", "stock-moves", "inventory", "approve", ""),
    ("stock-transfer", "Inventory", "Transfer stock between warehouse locations", "warehouse", "inventory", "approve", "new"),
    ("warehouse", "Inventory", "Manage reservations and backorders", "warehouse", "inventory", "approve", ""),
    ("bom", "Manufacturing", "Create bill of materials", "boms", "manufacturing", "create", "new"),
    ("production-order", "Manufacturing", "Create manufacturing order", "production-orders", "manufacturing", "create", "new"),
    ("production", "Manufacturing", "Reserve, stage, start or complete production", "production-orders", "manufacturing", "approve", ""),
    ("expense", "Expenses", "Create expense claim", "expense-claims", "expenses", "create", "new"),
    ("expenses", "Expenses", "Submit or reimburse an expense claim", "expense-claims", "expenses", "edit", ""),
    ("journal", "Accounting", "Create journal entry", "journals", "accounting", "create", "new"),
    ("journal-register", "Accounting", "Review or post journal entries", "journals", "accounting", "approve", ""),
    ("account", "Accounting", "Add ledger account", "accounts", "accounting", "create", "new"),
    ("bank-statement", "Accounting", "Enter a bank statement line", "bank", "accounting", "create", "new"),
    ("bank-match", "Accounting", "Reconcile bank statement lines", "bank", "accounting", "approve", ""),
    ("match-items", "Accounting", "Match outstanding debit and credit items", "aged", "accounting", "approve", "new"),
    ("cash-transfer", "Accounting", "Transfer money between bank and cash accounts", "accounting", "accounting", "approve", "transfer"),
    ("credit-note", "Accounting", "Create customer credit note", "credits", "accounting", "create", "new"),
    ("vendor-credit", "Accounting", "Create vendor credit note", "credits", "accounting", "create", "vendor-credit"),
    ("employee", "HR & Payroll", "Add employee", "hr-employees", "hr_employees", "create", "new"),
    ("manpower", "HR & Payroll", "Create manpower request", "hr-manpower", "hr_manpower", "create", "new"),
    ("recruitment", "HR & Payroll", "Add recruitment candidate", "hr-recruitment", "hr_recruitment", "create", "new"),
    ("attendance", "HR & Payroll", "Record attendance", "hr-attendance", "hr_attendance", "create", "new"),
    ("leave", "HR & Payroll", "Create leave request", "hr-leave", "hr_leave", "create", "new"),
    ("payroll", "HR & Payroll", "Create payroll draft", "hr-payroll", "hr_payroll", "create", "new"),
    ("payroll-register", "HR & Payroll", "Manage payroll, approval and payment", "hr-payroll", "hr_payroll", "edit", ""),
    ("separation", "HR & Payroll", "Record employee separation", "hr-separation", "hr_separation", "create", "new"),
)


def available_processes():
    user = g.user
    state = app_document().stored_data
    results = [{
        "id": "review", "group": "Approvals",
        "label": "Review, approve or reject a pending ERP action",
    }]
    for identity, group, label, view, module, permission, launch in PROCESS_FORMS:
        if not allowed(user, state, module) or not allowed(user, state, module, permission):
            continue
        if identity in ("cash-transfer", "stock-transfer") and not allowed(
            user, state, module, "create"
        ):
            continue
        if identity in ("supplier-payment", "customer-payment") and not (
            allowed(user, state, module, "approve")
            and allowed(user, state, "accounting", "approve")
        ):
            continue
        params = {"view": view}
        if launch in ("new", "vendor-credit"):
            params["new"] = "1"
            if launch == "vendor-credit":
                params["kind"] = "vendor"
        elif launch:
            params["action"] = launch
        if identity in ("goods-receipt", "delivery"):
            params["module"] = "inventory"
        elif group == "Accounting":
            params["module"] = "accounting"
        results.append({
            "id": identity, "group": group, "label": label,
            "url": "/erp.html?" + urlencode(params),
        })
    return results
