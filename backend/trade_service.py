"""Server-owned Sales and Purchasing commands; ledgers share the SQL transaction."""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
import secrets
import time
from flask import g
from sqlalchemy import select, update
from .app import (
    db,
    Document,
    app_document,
    audit,
    problem,
    utcnow,
    validate_numbers,
    validate_json,
)
from .permissions import COLLECTIONS, allowed, in_scope
from .erp import lock, next_number, sync_business, dec
from .validation import validate_business
from . import trade_store as store

MONEY = Decimal("0.01")
QTY = Decimal("0.0001")
PREFIXES = {
    "requests": "PR",
    "rfqs": "RFQ",
    "quotations": "VQ",
    "comparisons": "CMP",
    "orders": "PO",
    "receipts": "GRN",
    "invoices": "BILL",
    "payments": "PAY",
    "salesQuotations": "SQ",
    "salesOrders": "SO",
    "deliveries": "DO",
    "customerInvoices": "INV",
    "customerPayments": "REC",
}
CREATE_FIELDS = {
    "requests": {
        "date",
        "department",
        "requester",
        "requiredDate",
        "priority",
        "notes",
        "items",
        "attachmentPath",
        "attachment",
    },
    "rfqs": {"requestId", "parentVersion", "dueDate", "notes", "vendorIds"},
    "quotations": {
        "rfqId",
        "parentVersion",
        "vendorId",
        "quoteDate",
        "validUntil",
        "paymentTerms",
        "deliveryTime",
        "notes",
        "items",
        "attachmentPath",
        "attachment",
    },
    "orders": {
        "quotationId",
        "parentVersion",
        "vendorId",
        "poDate",
        "deliveryDate",
        "deliveryLocation",
        "paymentTerms",
        "deliveryTerms",
        "notes",
        "terms",
        "items",
        "attachmentPath",
        "attachment",
    },
    "receipts": {
        "poId",
        "parentVersion",
        "receivedDate",
        "receivedBy",
        "location",
        "notes",
        "items",
    },
    "invoices": {
        "poId",
        "parentVersion",
        "invoiceNo",
        "invoiceDate",
        "dueDate",
        "referenceNo",
        "notes",
        "items",
    },
    "payments": {
        "invoiceId",
        "parentVersion",
        "paymentDate",
        "amount",
        "method",
        "referenceNo",
        "notes",
    },
    "salesQuotations": {
        "leadId",
        "parentVersion",
        "customerId",
        "quotationDate",
        "validUntil",
        "paymentTerms",
        "deliveryTerms",
        "taxNote",
        "notes",
        "terms",
        "items",
    },
    "salesOrders": {"quotationId", "parentVersion", "orderDate", "notes"},
    "deliveries": {
        "orderId",
        "parentVersion",
        "deliveryDate",
        "deliveredBy",
        "location",
        "referenceNo",
        "notes",
        "items",
    },
    "customerInvoices": {
        "orderId",
        "parentVersion",
        "invoiceDate",
        "dueDate",
        "notes",
        "items",
    },
    "customerPayments": {
        "invoiceId",
        "parentVersion",
        "paymentDate",
        "amount",
        "method",
        "referenceNo",
        "notes",
    },
}
EDITABLE = {"requests", "salesQuotations", "orders", "quotations"}


class TradeCommand(db.Model):
    __tablename__ = "trade_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(40), nullable=False)
    identity = db.Column(db.String(64), nullable=False)


def permit(key, action="view", state=None):
    if key not in store.SPECS:
        problem("Unknown transaction register", 404)
    if not allowed(
        g.user, state or app_document().stored_data, COLLECTIONS[key], action
    ):
        problem("Permission required: " + COLLECTIONS[key] + "." + action, 403)


def text(data, key, default="", limit=1000, required=False):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value.strip()) > limit:
        problem("Invalid " + key)
    value = value.strip()
    if required and not value:
        problem(key + " is required")
    return value


def number(value, label="Amount", positive=False, quantum=MONEY):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or abs(value) > 1e12
    ):
        problem(label + " must be a finite number within the supported range")
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    if result < 0 or (positive and result <= 0):
        problem(label + " must be " + ("positive" if positive else "non-negative"))
    return result


def on_date(data, key, default=None, required=True):
    value = text(data, key, default or "", 40)
    if not value and not required:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        problem("Enter a valid " + key)
    if parsed.isoformat() != value:
        problem("Enter " + key + " as YYYY-MM-DD")
    return value


def today():
    from .erp import day

    return day()


def find(state, key, identity, scope=True):
    value = next((r for r in state.get(key, []) if str(r["id"]) == str(identity)), None)
    if value is None or (
        scope and key in COLLECTIONS and not in_scope(g.user, value, key, state)
    ):
        problem("Referenced " + key + " record not found", 404)
    return value


def parent(state, key, identity, data):
    value = find(state, key, identity)
    if not data.get("parentVersion"):
        problem("The source record version is required", 428)
    if data["parentVersion"] != store.version(value):
        problem("The source document changed. Select it again before saving.", 409)
    # Historical orphans survive migration for review; a new posting must never
    # inherit a missing party, product or workflow parent from such a record.
    for field, target in store.REFERENCES.get(key, {}).items():
        if value.get(field) not in (None, ""):
            find(state, target, value[field], scope=False)
    if key in store.SPECS and store.SPECS[key][3]:
        field = "customerId" if store.SPECS[key][3] == "customers" else "vendorId"
        find(state, store.SPECS[key][3], value.get(field), scope=False)
    if key in (
        "requests",
        "rfqs",
        "quotations",
        "orders",
        "salesQuotations",
        "salesOrders",
    ):
        source_lines = value.get("lineItems", value.get("items"))
        if not isinstance(source_lines, list) or not source_lines:
            problem("The source document has no valid economic lines")
        for line in source_lines:
            number(line.get("quantity"), "Source quantity", True, QTY)
            find(state, "products", line.get("productId"), scope=False)
    return value


def add(state, key, values):
    identity = int(time.time() * 1000) * 1000 + secrets.randbelow(1000)
    while any(str(r["id"]) == str(identity) for r in state.get(key, [])):
        identity += 1
    record = {
        **values,
        "id": identity,
        "createdBy": g.user.id,
        "createdAt": utcnow(),
        "workflowVersion": 1,
    }
    field = store.SPECS[key][1]
    if field and not record.get(field):
        candidate = next_number(PREFIXES[key])
        while any(r.get(field) == candidate for r in state.get(key, [])):
            candidate = next_number(PREFIXES[key])
        record[field] = candidate
    state.setdefault(key, []).insert(0, record)
    return record


def quantities(items):
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= 200
        or any(not isinstance(i, dict) for i in items)
    ):
        problem("Add 1–200 valid line items")
    return items


def calculate_line(product, quantity, rate, discount=0, tax=0, description=""):
    q = number(quantity, "Quantity", True, QTY)
    r = number(rate, "Rate", False, QTY)
    d = number(discount, "Discount percent", False, QTY)
    t = number(tax, "Tax percent", False, QTY)
    if d > 100 or t > 100:
        problem("Tax and discount must be within 0–100%")
    base = (q * r).quantize(MONEY, rounding=ROUND_HALF_UP)
    reduction = (base * d / 100).quantize(MONEY, rounding=ROUND_HALF_UP)
    net = base - reduction
    vat = (net * t / 100).quantize(MONEY, rounding=ROUND_HALF_UP)
    if net + vat > Decimal("1000000000000"):
        problem("Line amount exceeds the supported PKR amount limit")
    return dict(
        productId=product["id"],
        productName=product.get("name", product.get("productName", "")),
        unit=product.get("unit", "Each"),
        description=description,
        quantity=float(q),
        rate=float(r),
        quotedRate=float(r),
        discountPercent=float(d),
        taxPercent=float(t),
        subtotal=float(net),
        discountAmount=float(reduction),
        taxAmount=float(vat),
        tax=float(vat),
        total=float(net + vat),
    )


def price_lines(state, items, source=None):
    result = []
    for index, item in enumerate(quantities(items)):
        if set(item) - {
            "productId",
            "quantity",
            "rate",
            "taxPercent",
            "discountPercent",
            "description",
            "lineIndex",
        }:
            problem("Unknown line item fields")
        product = find(state, "products", item.get("productId"))
        if source is not None:
            if index >= len(source) or str(product["id"]) != str(
                source[index].get("productId")
            ):
                problem("Quotation lines must match the RFQ order")
            quantity = source[index]["quantity"]
            if item.get("quantity", quantity) != quantity:
                problem("Vendor quotations must quote the RFQ quantity")
        else:
            quantity = item.get("quantity")
        result.append(
            calculate_line(
                product,
                quantity,
                item.get("rate", product.get("rate", 0)),
                item.get("discountPercent", 0),
                item.get("taxPercent", 0),
                text(item, "description", limit=2000),
            )
        )
    if source is not None and len(result) != len(source):
        problem("Quote every RFQ line")
    return result


def totals(items):
    result = {
        key: float(sum((Decimal(str(i.get(field, 0))) for i in items), Decimal(0)))
        for key, field in [
            ("subtotal", "subtotal"),
            ("taxAmount", "taxAmount"),
            ("total", "total"),
        ]
    }
    if result["total"] > 1e12:
        problem("Document total exceeds the supported PKR amount limit")
    return result


def attachment(data, module):
    identity = data.get("attachmentPath")
    if not identity:
        return {}
    from .app import Attachment
    from .scope import require_object

    value = db.session.get(Attachment, str(identity))
    if not value or value.module != module:
        problem("Attachment not found for this module", 404)
    require_object(value)
    return {"attachmentPath": value.id, "attachment": value.filename}


def received(state, order, index):
    return sum(
        (
            Decimal(
                str(
                    (
                        r.get("items", [])[index]
                        if index < len(r.get("items", []))
                        else {}
                    ).get("acceptedQty", 0)
                )
            )
            for r in state.get("receipts", [])
            if str(r.get("poId")) == str(order["id"])
        ),
        Decimal(0),
    )


def dispatched(state, order, index, reserved=False):
    product = str(order["items"][index].get("productId"))
    return sum(
        (
            Decimal(str(item.get("deliveredQty", 0)))
            for d in state.get("deliveries", [])
            if str(d.get("orderId")) == str(order["id"])
            and (
                d.get("status") != "Cancelled"
                if reserved
                else d.get("status") == "Delivered"
            )
            for item in d.get("items", [])
            if (
                item.get("lineIndex") == index
                if "lineIndex" in item
                else str(item.get("productId")) == product
            )
        ),
        Decimal(0),
    )


def billed_quantity(state, order, index, customer=False, exclude=None):
    key = "customerInvoices" if customer else "invoices"
    field = "orderId" if customer else "poId"
    result = Decimal(0)
    for bill in state.get(key, []):
        if (
            str(bill.get(field)) != str(order["id"])
            or str(bill["id"]) == str(exclude)
            or bill.get("status") in ("Exception", "Cancelled")
        ):
            continue
        for position, item in enumerate(bill.get("items", [])):
            if int(item.get("lineIndex", position)) == index:
                result += Decimal(str(item.get("quantity", 0)))
    return result


def invoice_lines(state, order, items, customer=False, exclude=None):
    output = []
    used = set()
    for item in quantities(items):
        if set(item) - {"lineIndex", "quantity"}:
            problem("Invoice lines accept lineIndex and quantity only")
        index = item.get("lineIndex")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(order["items"])
            or index in used
        ):
            problem("Invalid or repeated order line")
        used.add(index)
        src = order["items"][index]
        quantity = number(item.get("quantity"), "Invoice quantity", True, QTY)
        remaining = Decimal(str(src["quantity"])) - billed_quantity(
            state, order, index, customer, exclude
        )
        if quantity > remaining:
            problem("Invoice quantity exceeds the remaining uninvoiced order quantity")
        product = find(state, "products", src["productId"])
        line = calculate_line(
            product,
            float(quantity),
            src.get("rate", src.get("quotedRate", 0)),
            src.get("discountPercent", 0),
            src.get("taxPercent", 0),
            str(src.get("description", "")),
        )
        # Allocate original line cents cumulatively. Re-rounding every partial
        # invoice independently can overcharge tax (or leave the last bill stuck).
        prior_quantity = billed_quantity(state, order, index, customer, exclude)
        prior_net, prior_tax = Decimal(0), Decimal(0)
        for bill in state.get("customerInvoices" if customer else "invoices", []):
            if (
                str(bill.get("orderId" if customer else "poId")) != str(order["id"])
                or str(bill["id"]) == str(exclude)
                or bill.get("status") in ("Exception", "Cancelled")
            ):
                continue
            for position, previous_line in enumerate(bill.get("items", [])):
                if int(previous_line.get("lineIndex", position)) != index:
                    continue
                tax = Decimal(
                    str(previous_line.get("taxAmount", previous_line.get("tax", 0)))
                )
                prior_tax += tax
                prior_net += Decimal(str(previous_line.get("total", 0))) - tax
        original = calculate_line(
            product,
            src["quantity"],
            src.get("rate", src.get("quotedRate", 0)),
            src.get("discountPercent", 0),
            src.get("taxPercent", 0),
        )
        ratio = (prior_quantity + quantity) / Decimal(str(src["quantity"]))
        net = (Decimal(str(original["subtotal"])) * ratio).quantize(
            MONEY, rounding=ROUND_HALF_UP
        ) - prior_net
        tax = (Decimal(str(original["taxAmount"])) * ratio).quantize(
            MONEY, rounding=ROUND_HALF_UP
        ) - prior_tax
        if net < 0 or tax < 0:
            problem(
                "Previous invoice allocations require review before further billing"
            )
        line.update(
            subtotal=float(net),
            taxAmount=float(tax),
            tax=float(tax),
            total=float(net + tax),
        )
        line["lineIndex"] = index
        output.append(line)
    return output


def match_bill(state, bill):
    order = find(state, "orders", bill.get("poId"))
    allocated = sum(
        (
            Decimal(str(b.get("amount", 0)))
            for b in state.get("invoices", [])
            if str(b.get("poId")) == str(order["id"])
            and str(b["id"]) != str(bill["id"])
            and b.get("status") in ("Matched", "Approved", "Partially Paid", "Paid")
        ),
        Decimal(0),
    )
    accepted_value = Decimal(0)
    for index, line in enumerate(order.get("items", [])):
        calc = (
            calculate_line(
                {
                    "id": line.get("productId"),
                    "productName": line.get("productName"),
                    "unit": line.get("unit"),
                },
                float(received(state, order, index)),
                line.get("rate", line.get("quotedRate", 0)),
                line.get("discountPercent", 0),
                line.get("taxPercent", 0),
            )
            if received(state, order, index) > 0
            else {"total": 0}
        )
        accepted_value += Decimal(str(calc["total"]))
    available = max(
        Decimal(0), min(accepted_value, Decimal(str(order.get("total", 0)))) - allocated
    )
    matched = Decimal(str(bill["amount"])) <= available + MONEY
    for position, line in enumerate(bill.get("items", [])):
        index = int(line.get("lineIndex", position))
        if index >= len(order.get("items", [])):
            matched = False
            continue
        if Decimal(str(line.get("quantity", 0))) > received(
            state, order, index
        ) - billed_quantity(state, order, index, False, bill["id"]):
            matched = False
    bill["matchStatus"] = "Matched" if matched else "Exception"
    bill["matchReason"] = (
        "Within accepted, ordered and unbilled quantities/value"
        if matched
        else "Bill exceeds accepted, ordered or unbilled quantities/value"
    )
    return matched


def recompute(state, key, row):
    if key not in (
        "orders",
        "receipts",
        "invoices",
        "payments",
        "salesOrders",
        "deliveries",
        "customerInvoices",
        "customerPayments",
    ):
        return
    affected_customer = key in (
        "salesOrders",
        "deliveries",
        "customerInvoices",
        "customerPayments",
    )
    order_id = (
        row["id"]
        if key in ("orders", "salesOrders")
        else row.get("orderId" if affected_customer else "poId")
    )
    for customer in (False, True):
        if customer != affected_customer:
            continue
        bills = state.get("customerInvoices" if customer else "invoices", [])
        payments = state.get("customerPayments" if customer else "payments", [])
        for bill in bills:
            if str(bill.get("orderId" if customer else "poId")) != str(order_id):
                continue
            if bill.get("status") not in (
                ("Posted", "Partially Paid", "Paid")
                if customer
                else ("Approved", "Partially Paid", "Paid")
            ):
                continue
            paid = sum(
                (
                    Decimal(str(p.get("amount", 0)))
                    for p in payments
                    if str(p.get("invoiceId")) == str(bill["id"])
                    and p.get("status") == ("Received" if customer else "Processed")
                ),
                Decimal(0),
            )
            balance = Decimal(str(bill["amount"])) - paid
            if balance < 0:
                problem("Payments exceed the invoice balance")
            bill.update(
                paidAmount=float(paid),
                balance=float(balance),
                status=(
                    "Paid"
                    if balance == 0
                    else (
                        "Partially Paid"
                        if paid
                        else "Posted" if customer else "Approved"
                    )
                ),
            )
        orders = state.get("salesOrders" if customer else "orders", [])
        for order in orders:
            if str(order["id"]) != str(order_id):
                continue
            if order.get("status") == "Cancelled":
                continue
            linked = [
                b
                for b in bills
                if str(b.get("orderId" if customer else "poId")) == str(order["id"])
                and b.get("status") not in ("Cancelled", "Exception")
            ]
            billed = sum((Decimal(str(b.get("amount", 0))) for b in linked), Decimal(0))
            paid = sum(
                (Decimal(str(b.get("paidAmount", 0))) for b in linked), Decimal(0)
            )
            total = Decimal(str(order.get("total", 0)))
            quantities_done = [
                (
                    dispatched(state, order, index)
                    if customer
                    else received(state, order, index)
                )
                for index in range(len(order.get("items", [])))
            ]
            complete = bool(quantities_done) and all(
                q >= Decimal(str(line["quantity"]))
                for q, line in zip(quantities_done, order["items"])
            )
            any_done = any(q > 0 for q in quantities_done)
            order["invoiceStatus"] = (
                "Invoiced"
                if billed >= total and billed
                else "Partially Invoiced" if billed else "Not Invoiced"
            )
            order["paymentStatus"] = (
                "Paid"
                if billed and paid >= billed
                else "Partially Paid" if paid else "Unpaid"
            )
            if customer:
                order["deliveryStatus"] = (
                    "Delivered"
                    if complete
                    else "Partially Delivered" if any_done else "Pending Delivery"
                )
                order["status"] = (
                    "Completed"
                    if complete and total > 0 and billed >= total and paid >= total
                    else (
                        "Delivered"
                        if complete
                        else (
                            "Partially Delivered"
                            if any_done
                            else order.get("status", "Confirmed")
                        )
                    )
                )
            elif complete or any_done:
                order["status"] = (
                    "Completed"
                    if complete and total > 0 and billed >= total and paid >= total
                    else "Received" if complete else "Partially Received"
                )


def create(state, key, data):
    if key not in CREATE_FIELDS:
        problem("Create a comparison by awarding a vendor quotation")
    if set(data) - CREATE_FIELDS[key] - {"requestKey"}:
        problem("Unknown " + key + " fields")
    permit(key, "create", state)
    if key == "requests":
        items = price_lines(state, data.get("items"))
        return add(
            state,
            key,
            dict(
                requester=text(data, "requester", g.user.name, 160, True),
                department=text(data, "department", limit=160, required=True),
                date=on_date(data, "date", today()),
                requiredDate=on_date(data, "requiredDate", required=False),
                priority=text(data, "priority", "Normal", 40),
                notes=text(data, "notes", limit=10000),
                lineItems=items,
                items=len(items),
                total=totals(items)["total"],
                status=(
                    "Draft"
                    if allowed(g.user, state, "requests", "edit")
                    else "Pending Approval"
                ),
                **attachment(data, "requests")
            ),
        )
    if key == "rfqs":
        source = parent(state, "requests", data.get("requestId"), data)
        if source.get("status") != "Approved":
            problem("RFQs require an approved purchase request")
        if any(
            str(r.get("requestId")) == str(source["id"]) for r in state.get("rfqs", [])
        ):
            problem("An RFQ already exists for this request", 409)
        ids = data.get("vendorIds")
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 100
            or len(set(map(str, ids))) != len(ids)
        ):
            problem("Select 1–100 distinct vendors")
        vendors = [find(state, "vendors", identity) for identity in ids]
        if any(v.get("status") == "Inactive" for v in vendors):
            problem("Select active vendors")
        return add(
            state,
            key,
            dict(
                requestId=source["id"],
                requestNo=source["requestNo"],
                department=source.get("department", ""),
                issueDate=today(),
                dueDate=on_date(data, "dueDate"),
                vendors=[
                    {k: v.get(k, "") for k in ("id", "name", "email", "contact", "trn")}
                    for v in vendors
                ],
                items=deepcopy(source.get("lineItems", [])),
                estimatedTotal=source.get("total", 0),
                notes=text(data, "notes", limit=10000),
                status="Draft",
            ),
        )
    if key == "quotations":
        source = parent(state, "rfqs", data.get("rfqId"), data)
        vendor = find(state, "vendors", data.get("vendorId"))
        if source.get("status") not in ("Sent", "Response Received"):
            problem("Send the RFQ before recording vendor quotations")
        if not any(
            str(v["id"]) == str(vendor["id"]) for v in source.get("vendors", [])
        ):
            problem("Vendor was not invited to this RFQ")
        if any(
            str(q.get("rfqId")) == str(source["id"])
            and str(q.get("vendorId")) == str(vendor["id"])
            for q in state.get(key, [])
        ):
            problem("This vendor already quoted this RFQ", 409)
        items = price_lines(state, data.get("items"), source.get("items", []))
        if any(i["rate"] <= 0 for i in items):
            problem("Enter a positive vendor rate for each line")
        result = add(
            state,
            key,
            dict(
                rfqId=source["id"],
                rfqNo=source["rfqNo"],
                requestNo=source.get("requestNo", ""),
                vendorId=vendor["id"],
                vendorName=vendor["name"],
                vendorEmail=vendor.get("email", ""),
                vendorTRN=vendor.get("trn", ""),
                quoteDate=on_date(data, "quoteDate", today()),
                validUntil=on_date(data, "validUntil"),
                paymentTerms=text(data, "paymentTerms", "Cash", 160),
                deliveryTime=text(data, "deliveryTime", limit=160),
                notes=text(data, "notes", limit=10000),
                items=items,
                **totals(items),
                status="Received",
                **attachment(data, "quotations")
            ),
        )
        source["status"] = "Response Received"
        return result
    if key == "salesQuotations":
        customer = find(state, "customers", data.get("customerId"))
        if customer.get("status") == "Inactive":
            problem("Select an active customer")
        lead = (
            parent(state, "leads", data["leadId"], data) if data.get("leadId") else None
        )
        if lead and str(lead.get("customerId")) != str(customer["id"]):
            problem("The lead belongs to another customer")
        if lead and lead.get("currency", "PKR") != "PKR":
            problem("Use a PKR opportunity; currency conversion is not configured")
        items = price_lines(state, data.get("items"))
        return add(
            state,
            key,
            dict(
                leadId=lead["id"] if lead else None,
                customerId=customer["id"],
                customerName=customer["name"],
                customerAddress=customer.get("address", ""),
                ownerId=lead.get("ownerId") if lead else g.user.id,
                managerId=lead.get("managerId") if lead else g.user.manager_id,
                quotationDate=on_date(data, "quotationDate", today()),
                validUntil=on_date(data, "validUntil", required=False),
                paymentTerms=text(data, "paymentTerms", "Cash", 160),
                deliveryTerms=text(data, "deliveryTerms", limit=1000),
                taxNote=text(data, "taxNote", limit=1000),
                terms=text(data, "terms", limit=10000),
                notes=text(data, "notes", limit=10000),
                items=items,
                **totals(items),
                status="Draft"
            ),
        )
    if key in ("orders", "salesOrders"):
        customer = key == "salesOrders"
        source_key = "salesQuotations" if customer else "quotations"
        source = (
            parent(state, source_key, data["quotationId"], data)
            if data.get("quotationId")
            else None
        )
        if customer and not source:
            problem("Select a customer-accepted quotation")
        if source:
            if source.get("status") != ("Accepted" if customer else "Selected"):
                problem(
                    "Select an "
                    + ("accepted" if customer else "awarded")
                    + " quotation"
                )
            if any(
                str(o.get("quotationId")) == str(source["id"])
                for o in state.get(key, [])
            ):
                problem("An order already exists for this quotation", 409)
            partner = find(
                state,
                "customers" if customer else "vendors",
                source["customerId" if customer else "vendorId"],
            )
            items = deepcopy(source["items"])
        else:
            partner = find(state, "vendors", data.get("vendorId"))
            items = price_lines(state, data.get("items"))
        values = dict(
            quotationId=source["id"] if source else None,
            quotationNo=source.get("quotationNo", "") if source else "",
            items=items,
            **totals(items),
            notes=text(data, "notes", limit=10000),
            paymentTerms=text(
                data,
                "paymentTerms",
                str((source or {}).get("paymentTerms", "Cash")),
                160,
            ),
            invoiceStatus="Not Invoiced",
            paymentStatus="Unpaid"
        )
        if customer:
            values.update(
                customerId=partner["id"],
                customerName=partner["name"],
                leadId=source.get("leadId"),
                orderDate=on_date(data, "orderDate", today()),
                status="Confirmed",
                deliveryStatus="Pending Delivery",
                deliveryTerms=source.get("deliveryTerms", ""),
                ownerId=source.get("ownerId"),
                managerId=source.get("managerId"),
            )
        else:
            values.update(
                vendorId=partner["id"],
                vendorName=partner["name"],
                vendorTRN=partner.get("trn", ""),
                rfqId=(source or {}).get("rfqId"),
                rfqNo=(source or {}).get("rfqNo", ""),
                requestNo=(source or {}).get("requestNo", ""),
                poDate=on_date(data, "poDate", today()),
                deliveryDate=on_date(data, "deliveryDate"),
                deliveryLocation=text(data, "deliveryLocation", "WH / Stock", 160),
                deliveryTerms=text(data, "deliveryTerms", limit=1000),
                terms=text(data, "terms", limit=10000),
                status="Draft",
                source="Quotation" if source else "Direct PO",
                **attachment(data, "orders")
            )
        result = add(state, key, values)
        if source and customer:
            source.update(
                status="Converted", orderId=result["id"], orderNo=result["orderNo"]
            )
        if source and not customer:
            find(state, "rfqs", source["rfqId"])["status"] = "PO Created"
        return result
    if key in ("receipts", "deliveries"):
        customer = key == "deliveries"
        source_key = "salesOrders" if customer else "orders"
        link = "orderId" if customer else "poId"
        source = parent(state, source_key, data.get(link), data)
        if source.get("status") not in (
            ("Confirmed", "Partially Delivered", "Delivered")
            if customer
            else ("Approved", "Sent to Vendor", "Partially Received")
        ):
            problem(
                "This order is not open for "
                + ("delivery" if customer else "receiving")
            )
        entered = quantities(data.get("items"))
        seen = set()
        items = []
        for value in entered:
            allowed_fields = (
                {"lineIndex", "deliveredQty"}
                if customer
                else {
                    "lineIndex",
                    "receivedQty",
                    "acceptedQty",
                    "rejectedQty",
                    "inspection",
                    "remark",
                }
            )
            if set(value) - allowed_fields:
                problem("Unknown fulfilment line fields")
            index = value.get("lineIndex")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= len(source["items"])
                or index in seen
            ):
                problem("Select each order line once")
            seen.add(index)
            src = source["items"][index]
            remain = Decimal(str(src["quantity"])) - (
                dispatched(state, source, index, True)
                if customer
                else received(state, source, index)
            )
            if customer:
                qty = number(
                    value.get("deliveredQty", 0), "Delivery quantity", False, QTY
                )
                if qty > remain:
                    problem("Delivery exceeds remaining unreserved order quantity")
                items.append(
                    dict(
                        lineIndex=index,
                        productId=src["productId"],
                        productName=src.get("productName", ""),
                        unit=src.get("unit", "Each"),
                        deliveredQty=float(qty),
                    )
                )
            else:
                qty = number(
                    value.get("receivedQty", 0), "Received quantity", False, QTY
                )
                accepted = number(
                    value.get("acceptedQty", 0), "Accepted quantity", False, QTY
                )
                rejected = number(
                    value.get("rejectedQty", 0), "Rejected quantity", False, QTY
                )
                if qty > remain or accepted + rejected != qty:
                    problem(
                        "Received must equal accepted plus rejected and remain within the PO quantity"
                    )
                items.append(
                    dict(
                        lineIndex=index,
                        productId=src["productId"],
                        productName=src.get("productName", ""),
                        unit=src.get("unit", "Each"),
                        orderedQty=src["quantity"],
                        receivedQty=float(qty),
                        acceptedQty=float(accepted),
                        rejectedQty=float(rejected),
                        inspection=text(value, "inspection", "Accepted", 80),
                        remark=text(value, "remark", limit=1000),
                    )
                )
        if not any(i.get("deliveredQty", i.get("receivedQty", 0)) > 0 for i in items):
            problem("Enter at least one positive fulfilment quantity")
        if not customer:
            # Legacy ledger uses receipt line ordinal to pick PO cost: fill omitted lines with zero.
            by_index = {i["lineIndex"]: i for i in items}
            items = [
                by_index.get(
                    i,
                    dict(
                        lineIndex=i,
                        productId=line["productId"],
                        productName=line.get("productName", ""),
                        unit=line.get("unit", "Each"),
                        orderedQty=line["quantity"],
                        receivedQty=0,
                        acceptedQty=0,
                        rejectedQty=0,
                    ),
                )
                for i, line in enumerate(source["items"])
            ]
        values = dict(
            items=items,
            notes=text(data, "notes", limit=10000),
            location=text(data, "location", "WH / Stock", 160),
            quotationId=source.get("quotationId"),
            quotationNo=source.get("quotationNo", ""),
        )
        if customer:
            values.update(
                orderId=source["id"],
                orderNo=source["orderNo"],
                customerId=source["customerId"],
                customerName=source["customerName"],
                deliveryDate=on_date(data, "deliveryDate", today()),
                deliveredBy=text(data, "deliveredBy", g.user.name, 160),
                referenceNo=text(data, "referenceNo", limit=160),
                status="Pending",
            )
        else:
            values.update(
                poId=source["id"],
                poNo=source["poNo"],
                vendorId=source["vendorId"],
                vendorName=source["vendorName"],
                receivedDate=on_date(data, "receivedDate", today()),
                receivedBy=text(data, "receivedBy", g.user.name, 160),
                status=(
                    "Accepted"
                    if all(i.get("rejectedQty", 0) == 0 for i in items)
                    else (
                        "Partially Accepted"
                        if any(i.get("acceptedQty", 0) > 0 for i in items)
                        else "Rejected"
                    )
                ),
            )
        return add(state, key, values)
    if key in ("invoices", "customerInvoices"):
        customer = key == "customerInvoices"
        link = "orderId" if customer else "poId"
        source = parent(
            state, "salesOrders" if customer else "orders", data.get(link), data
        )
        if source.get("status") in ("Draft", "Pending Approval", "Cancelled"):
            problem("Invoice an approved/confirmed order")
        items = invoice_lines(state, source, data.get("items"), customer)
        total = totals(items)
        if total["total"] <= 0:
            problem("Invoice total must be positive")
        values = dict(
            items=items,
            subtotal=total["subtotal"],
            taxAmount=total["taxAmount"],
            amount=total["total"],
            paidAmount=0,
            balance=total["total"],
            invoiceDate=on_date(data, "invoiceDate", today()),
            dueDate=on_date(data, "dueDate"),
            quotationId=source.get("quotationId"),
            quotationNo=source.get("quotationNo", ""),
            paymentTerms=source.get("paymentTerms", "Cash"),
            notes=text(data, "notes", limit=10000),
        )
        if customer:
            permit(key, "approve", state)
            values.update(
                orderId=source["id"],
                orderNo=source["orderNo"],
                customerId=source["customerId"],
                customerName=source["customerName"],
                status="Posted",
            )
        else:
            values.update(
                poId=source["id"],
                poNo=source["poNo"],
                vendorId=source["vendorId"],
                vendorName=source["vendorName"],
                invoiceNo=text(data, "invoiceNo", limit=160, required=True),
                referenceNo=text(data, "referenceNo", limit=160),
                status="Exception",
            )
        result = add(state, key, values)
        if not customer:
            result["status"] = "Matched" if match_bill(state, result) else "Exception"
        return result
    if key in ("payments", "customerPayments"):
        permit(key, "approve", state)
        customer = key == "customerPayments"
        source = parent(
            state,
            "customerInvoices" if customer else "invoices",
            data.get("invoiceId"),
            data,
        )
        if source.get("status") not in (
            ("Posted", "Partially Paid") if customer else ("Approved", "Partially Paid")
        ):
            problem("Select an open posted/approved invoice")
        amount = number(data.get("amount"), "Payment amount", True)
        balance = Decimal(str(source.get("amount", 0))) - sum(
            (
                Decimal(str(p.get("amount", 0)))
                for p in state.get(key, [])
                if str(p.get("invoiceId")) == str(source["id"])
                and p.get("status") == ("Received" if customer else "Processed")
            ),
            Decimal(0),
        )
        if amount > balance:
            problem("Payment exceeds the outstanding balance")
        method = text(data, "method", "Bank Transfer", 40)
        if method not in ("Cash", "Bank Transfer", "Cheque", "Card", "Online"):
            problem("Select a valid payment method")
        reference = text(data, "referenceNo", limit=160)
        if reference and any(
            str(p.get("referenceNo", "")).casefold() == reference.casefold()
            for p in state.get(key, [])
        ):
            problem("Payment reference already exists", 409)
        values = dict(
            invoiceId=source["id"],
            invoiceNo=source["invoiceNo"],
            paymentDate=on_date(data, "paymentDate", today()),
            amount=float(amount),
            method=method,
            referenceNo=reference,
            notes=text(data, "notes", limit=10000),
            status="Received" if customer else "Processed",
        )
        values.update(
            {
                field: source.get(field)
                for field in (
                    ("customerId", "customerName", "orderId", "orderNo")
                    if customer
                    else ("vendorId", "vendorName", "poId", "poNo")
                )
            }
        )
        return add(state, key, values)
    problem("Unsupported creation command")


TRANSITIONS = {
    "requests": {
        "submit": ({"Draft"}, "Pending Approval", "edit"),
        "approve": ({"Pending Approval"}, "Approved", "approve"),
        "reject": ({"Pending Approval"}, "Rejected", "approve"),
    },
    "rfqs": {"send": ({"Draft"}, "Sent", "edit")},
    "salesQuotations": {
        "submit": ({"Draft"}, "Pending Approval", "edit"),
        "approve": ({"Pending Approval"}, "Approved", "approve"),
        "reject": ({"Draft", "Pending Approval", "Sent"}, "Rejected", "edit"),
        "send": ({"Approved"}, "Sent", "edit"),
        "accept": ({"Sent"}, "Accepted", "edit"),
        "expire": ({"Sent"}, "Expired", "edit"),
    },
    "orders": {
        "submit": ({"Draft"}, "Pending Approval", "edit"),
        "approve": ({"Pending Approval"}, "Approved", "approve"),
        "send": ({"Approved"}, "Sent to Vendor", "edit"),
        "cancel": ({"Draft", "Pending Approval", "Approved"}, "Cancelled", "edit"),
    },
    "deliveries": {
        "deliver": ({"Pending"}, "Delivered", "edit"),
        "cancel": ({"Pending"}, "Cancelled", "edit"),
    },
    "invoices": {
        "match": ({"Exception", "Matched"}, "Matched", "edit"),
        "approve": ({"Matched"}, "Approved", "approve"),
    },
}


def action_permission(key, action, row):
    if key == "quotations" and action == "award":
        return "approve"
    if key == "comparisons" and action == "clear":
        return "approve"
    if (
        key == "salesQuotations"
        and action == "reject"
        and row.get("status") == "Pending Approval"
    ):
        return "approve"
    return TRANSITIONS.get(key, {}).get(action, (None, None, None))[2]


def act(state, key, row, action, data):
    permission = action_permission(key, action, row)
    if not permission:
        problem("Unknown document action")
    permit(key, permission, state)
    if set(data) - {"requestKey", "version"}:
        problem("Unknown action fields")
    if key == "quotations" and action == "award":
        permit("comparisons", "approve", state)
        if row.get("status") != "Received":
            problem("Award a received vendor quotation")
        if row.get("validUntil") and str(row["validUntil"]) < today():
            problem("This vendor quotation has expired")
        if any(
            str(o.get("rfqId")) == str(row.get("rfqId"))
            and o.get("status") != "Cancelled"
            for o in state.get("orders", [])
        ):
            problem("This RFQ already has a purchase order")
        rfq = find(state, "rfqs", row["rfqId"])
        if rfq.get("status") not in ("Sent", "Response Received"):
            problem("This RFQ is closed; clear its previous award first")
        for q in state.get("quotations", []):
            if str(q.get("rfqId")) == str(row["rfqId"]):
                q["status"] = "Selected" if q["id"] == row["id"] else "Rejected"
        rfq.update(status="Closed", completedAt=utcnow())
        values = dict(
            rfqId=rfq["id"],
            rfqNo=rfq["rfqNo"],
            requestNo=rfq.get("requestNo", ""),
            selectedQuotationId=row["id"],
            selectedQuotationNo=row["quotationNo"],
            vendorId=row["vendorId"],
            vendorName=row["vendorName"],
            total=row["total"],
            status="Completed",
            comparedAt=utcnow(),
        )
        old = next(
            (
                c
                for c in state.get("comparisons", [])
                if str(c.get("rfqId")) == str(rfq["id"])
            ),
            None,
        )
        if old:
            old.update(values)
        else:
            add(state, "comparisons", values)
        return
    if key == "comparisons" and action == "clear":
        if row.get("status") != "Completed":
            problem("This award is already clear")
        if any(
            str(o.get("rfqId")) == str(row["rfqId"]) for o in state.get("orders", [])
        ):
            problem("An award used by a purchase order cannot be cleared")
        for q in state.get("quotations", []):
            if str(q.get("rfqId")) == str(row["rfqId"]):
                q["status"] = "Received"
        find(state, "rfqs", row["rfqId"])["status"] = "Response Received"
        row["status"] = "Cleared"
        return
    origins, target, _ = TRANSITIONS[key][action]
    if row.get("status") not in origins:
        problem("Action is not available in the current document status", 409)
    if key == "invoices" and not match_bill(state, row):
        problem(row["matchReason"])
    if (
        key == "orders"
        and action == "cancel"
        and any(str(r.get("poId")) == str(row["id"]) for r in state.get("receipts", []))
    ):
        problem("An order with receipts cannot be cancelled")
    if (
        key == "salesQuotations"
        and action in ("send", "accept")
        and row.get("validUntil")
        and str(row["validUntil"]) < today()
    ):
        problem("This sales quotation has expired")
    row["status"] = target
    row[action + "At"] = utcnow()
    if action == "approve":
        row.update(approvedBy=g.user.id, approvedByName=g.user.name)


def edit(state, key, row, data):
    if key not in EDITABLE or row.get("status") not in (
        ("Received",) if key == "quotations" else ("Draft",)
    ):
        problem("Only editable draft/received documents can change")
    permit(key, "edit", state)
    # Parent/partner identity is immutable after creation; recreate the draft to change its source.
    editable = {
        "requests": {
            "notes",
            "items",
            "department",
            "requester",
            "requiredDate",
            "priority",
        },
        "salesQuotations": {
            "notes",
            "items",
            "terms",
            "paymentTerms",
            "deliveryTerms",
            "validUntil",
            "taxNote",
        },
        "orders": {
            "notes",
            "items",
            "terms",
            "paymentTerms",
            "deliveryTerms",
            "deliveryDate",
            "deliveryLocation",
        },
        "quotations": {"notes", "items", "paymentTerms", "deliveryTime", "validUntil"},
    }[key]
    if set(data) - editable - {"requestKey", "version"}:
        problem("Unknown or immutable edit fields")
    for field in editable - {"items"}:
        if field in data:
            row[field] = (
                on_date(data, field, required=field == "deliveryDate")
                if field in ("validUntil", "deliveryDate", "requiredDate")
                else text(
                    data, field, limit=10000 if field in ("notes", "terms") else 1000
                )
            )
    if "items" in data:
        if key == "orders" and any(
            str(v.get("poId")) == str(row["id"])
            for k in ("receipts", "invoices")
            for v in state.get(k, [])
        ):
            problem("An order with receipts or bills cannot change its economic lines")
        if key == "quotations" and any(
            str(o.get("quotationId")) == str(row["id"]) for o in state.get("orders", [])
        ):
            problem("An ordered quotation cannot change")
        if key == "orders" and row.get("quotationId"):
            problem(
                "Quoted PO lines are fixed; use direct PO lines or create a new quotation"
            )
        source = (
            find(state, "rfqs", row["rfqId"]).get("items", [])
            if key == "quotations"
            else None
        )
        items = price_lines(state, data["items"], source)
        if key == "requests":
            row.update(lineItems=items, items=len(items), total=totals(items)["total"])
        else:
            row.update(items=items, **totals(items))


def available_actions(key, row, state):
    output = []
    for action, (origins, _, _) in TRANSITIONS.get(key, {}).items():
        if row.get("status") in origins and allowed(
            g.user, state, COLLECTIONS[key], action_permission(key, action, row)
        ):
            output.append(action)
    if (
        key == "quotations"
        and row.get("status") == "Received"
        and allowed(g.user, state, "quotations", "approve")
        and allowed(g.user, state, "comparison", "approve")
    ):
        output.append("award")
    if (
        key == "comparisons"
        and row.get("status") == "Completed"
        and allowed(g.user, state, "comparison", "approve")
    ):
        output.append("clear")
    if (
        key in EDITABLE
        and row.get("status") in (("Received",) if key == "quotations" else ("Draft",))
        and allowed(g.user, state, COLLECTIONS[key], "edit")
    ):
        output.append("edit")
    return output


def execute(key, identity=None, action=None):
    """Versioned/idempotent commands are serialized with stock and accounting writes."""
    from .app import body, sync_crm_from_sales, validate_scope_references

    data = body()
    validate_json(data)
    permit(key, "view")
    if identity is None:
        permit(key, "create")
    request_key = data.get("requestKey", "")
    if not isinstance(request_key, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{8,100}", request_key
    ):
        problem("A unique requestKey of 8–100 letters/numbers is required")
    fingerprint = store.version(
        {
            "key": key,
            "identity": str(identity) if identity is not None else None,
            "action": action,
            "data": {
                k: v
                for k, v in data.items()
                if k not in ("version", "parentVersion", "requestKey")
            },
        }
    )
    lock()
    doc = app_document()
    db.session.refresh(doc)
    if not doc.stored_data.get(store.MARKER):
        problem("Run flask --app backend.app migrate-storage", 503)
    original = deepcopy(doc.data)
    state = deepcopy(original)
    row = find(state, key, identity) if identity is not None else None
    if row:
        permission = action_permission(key, action, row) if action else "edit"
        if permission:
            permit(key, permission, state)
    receipt = db.session.get(TradeCommand, (g.user.id, request_key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("This request key was already used for another command", 409)
        value = find(state, receipt.resource, receipt.identity)
        return value, doc.revision
    if row:
        if not data.get("version"):
            problem("Document version is required", 428)
        if data["version"] != store.version(row):
            problem(
                "This document changed. Reload its details before trying again.", 409
            )
        if action:
            act(state, key, row, action, data)
        else:
            edit(state, key, row, data)
    else:
        row = create(state, key, data)
    recompute(state, key, row)
    sync_crm_from_sales(state, original)
    validate_scope_references(state, original)
    validate_business(state)
    for resource in store.SPECS:
        for value in state.get(resource, []):
            validate_numbers(value)
    # Existing immutable stock/accounting services participate in this same transaction.
    from .storage import persist

    stored = persist(state)
    result = db.session.execute(
        update(Document)
        .where(Document.name == "app", Document.revision == doc.revision)
        .values(stored_data=stored, revision=doc.revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        problem("Another user saved newer records. Reload.", 409)
    sync_business(original, state, "app")
    db.session.add(
        TradeCommand(
            actor_id=g.user.id,
            request_key=request_key,
            fingerprint=fingerprint,
            resource=key,
            identity=str(row["id"]),
        )
    )
    audit(
        "Trade " + (action or "edit" if identity is not None else "create"),
        {"resource": key, "recordId": row["id"]},
    )
    revision = doc.revision + 1
    db.session.commit()
    return row, revision
