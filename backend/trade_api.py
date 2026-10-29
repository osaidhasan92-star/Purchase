"""Bounded native transaction resources and explicit workflow commands."""

from copy import deepcopy
from flask import Blueprint, g, jsonify, request, render_template_string, make_response
from sqlalchemy import select, or_, and_, func
from .app import db, User, app_document, problem
from .permissions import allowed, COLLECTIONS
from . import trade_store as store
from .trade_service import (
    permit,
    execute,
    available_actions,
    received,
    dispatched,
    billed_quantity,
    totals,
    calculate_line,
)
from .crm_api import visible_leads
from .master_store import Lead

bp = Blueprint("trade", __name__, url_prefix="/api/trade")


def visibility(key):
    """Translate the existing department/team/parent policy into SQL before paging."""
    from .scope import finance_access

    state = app_document().stored_data
    if g.user.role == "Admin":
        return True
    if key == "requests" and (
        allowed(g.user, state, "rfqs") or finance_access(g.user, state)
    ):
        return True
    if key not in (
        "requests",
        "salesQuotations",
        "salesOrders",
        "deliveries",
        "customerInvoices",
        "customerPayments",
    ):
        return True
    if key != "requests" and finance_access(g.user, state):
        return True
    team_conditions = [User.id == g.user.id, User.manager_id == g.user.id]
    if g.user.manager_id:
        team_conditions.extend(
            [User.id == g.user.manager_id, User.manager_id == g.user.manager_id]
        )
    actors = select(User.id).where(or_(*team_conditions))
    model = store.MODELS[key]
    own = or_(model.created_by.in_(actors), model.owner_id.in_(actors))
    if key == "requests":
        return own
    if key == "salesQuotations":
        return or_(own, model.lead_id.in_(select(Lead.id).where(visible_leads())))
    if key == "salesOrders":
        parent = store.MODELS["salesQuotations"]
        return or_(
            own,
            model.quotation_id.in_(
                select(parent.id).where(visibility("salesQuotations"))
            ),
        )
    parent = store.MODELS["salesOrders"]
    return or_(
        own, model.order_id.in_(select(parent.id).where(visibility("salesOrders")))
    )


def require_migrated():
    if not app_document().stored_data.get(store.MARKER):
        problem(
            "Run flask --app backend.app migrate-storage before opening transactions",
            503,
        )


def scoped(key, identity):
    permit(key)
    require_migrated()
    row = db.session.scalar(
        select(store.MODELS[key]).where(
            store.MODELS[key].id == str(identity), visibility(key)
        )
    )
    if row is None:
        problem("Document not found", 404)
    return row


def output(key, row, detail=False):
    state = app_document().stored_data
    result = (
        store.record(key, row)
        if detail
        else {"id": row.original_id, "status": row.status}
    )
    field = store.SPECS[key][1]
    if field:
        result[field] = row.number
    if not detail:
        for f, c in store.FIELDS[key].items():
            if f in ("createdBy", "ownerId", "managerId", "notes"):
                continue
            value = getattr(row, c)
            if value is not None:
                result[f] = float(value) if f in store.NUMBERS else value
    result.update(
        version=row.record_version, actions=available_actions(key, result, state)
    )
    return result


def context(key, row):
    """Return this document's operational quantities, never an entire register."""
    result = {}
    if key in ("orders", "salesOrders"):
        # Only this workflow graph is needed for parent form quantities.
        model = store.MODELS
        state = {}
        for related, field in (
            [("deliveries", "order_id"), ("customerInvoices", "order_id")]
            if key == "salesOrders"
            else [("receipts", "po_id"), ("invoices", "po_id")]
        ):
            state[related] = [
                store.record(related, r)
                for r in db.session.scalars(
                    select(model[related]).where(
                        getattr(model[related], field) == row.id
                    )
                )
            ]
        value = store.record(key, row)
        lines = []
        from decimal import Decimal

        for index, item in enumerate(value.get("items", [])):
            received_qty = (
                dispatched(state, value, index)
                if key == "salesOrders"
                else received(state, value, index)
            )
            reserved = (
                dispatched(state, value, index, True)
                if key == "salesOrders"
                else received_qty
            )
            billed = billed_quantity(state, value, index, key == "salesOrders")
            quantity = Decimal(str(item.get("quantity", 0)))
            lines.append(
                dict(
                    lineIndex=index,
                    productId=item.get("productId"),
                    productName=item.get("productName", ""),
                    unit=item.get("unit", "Each"),
                    ordered=float(quantity),
                    received=float(received_qty),
                    remaining=float(max(Decimal(0), quantity - reserved)),
                    invoiceRemaining=float(max(Decimal(0), quantity - billed)),
                    acceptedUnbilled=float(max(Decimal(0), received_qty - billed)),
                    rate=item.get("rate", item.get("quotedRate", 0)),
                    taxPercent=item.get("taxPercent", 0),
                    discountPercent=item.get("discountPercent", 0),
                )
            )
        result["lines"] = lines
        result["legacyInvoiceCount"] = sum(
            1
            for bill in state.get(
                "customerInvoices" if key == "salesOrders" else "invoices", []
            )
            if not bill.get("items")
            and bill.get("status") not in ("Cancelled", "Exception")
        )
    if key in ("invoices", "customerInvoices"):
        payment_key = "customerPayments" if key == "customerInvoices" else "payments"
        payment_model = store.MODELS[payment_key]
        paid = db.session.scalar(
            select(func.coalesce(func.sum(payment_model.amount), 0)).where(
                payment_model.invoice_id == row.id,
                payment_model.status
                == ("Received" if key == "customerInvoices" else "Processed"),
            )
        )
        result["balance"] = float(max(0, (row.amount or 0) - paid))
    if key == "deliveries":
        if allowed(g.user, app_document().stored_data, "sales_invoices") and allowed(
            g.user, app_document().stored_data, "sales_invoices", "export"
        ):
            model = store.MODELS["customerInvoices"]
            result["invoices"] = [
                dict(invoiceNo=r.number, amount=float(r.amount or 0), status=r.status)
                for r in db.session.scalars(
                    select(model)
                    .where(
                        model.order_id == row.order_id, visibility("customerInvoices")
                    )
                    .order_by(model.document_date, model.id)
                    .limit(25)
                )
            ]
        # A delivery challan includes its complete source quotation/order, subject to this document's scope.
        order = (
            db.session.get(store.MODELS["salesOrders"], str(row.order_id))
            if row.order_id
            else None
        )
        if order:
            result["sourceLines"] = deepcopy(
                store.record("salesOrders", order).get("items", [])
            )
            result["sourceNumber"] = order.number
    return result


@bp.get("/reference/leads/<identity>")
def lead_reference(identity):
    permit("salesQuotations", "create")
    require_migrated()
    from .master_store import record as master_record
    from .master_api import version

    lead = db.session.scalar(select(Lead).where(Lead.id == identity, visible_leads()))
    if lead is None:
        problem("Lead not found", 404)
    value = master_record("leads", lead)
    return jsonify(
        record={
            **{
                k: value.get(k)
                for k in (
                    "id",
                    "customerId",
                    "customerName",
                    "ownerId",
                    "managerId",
                    "stage",
                    "currency",
                )
            },
            "version": version(value),
        }
    )


@bp.get("/<key>")
def listing(key):
    permit(key)
    require_migrated()
    try:
        page, size = int(request.args.get("page", "1")), int(
            request.args.get("pageSize", "25")
        )
    except ValueError:
        problem("Pagination must use integers")
    if page < 1 or not 1 <= size <= 100:
        problem("Page must be positive; pageSize must be 1–100")
    search = request.args.get("search", "").strip().casefold()
    if len(search) > 160:
        problem("Search is too long")
    model = store.MODELS[key]
    query = select(model).where(visibility(key))
    if search:
        term = (
            "%"
            + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        query = query.where(model.search_text.like(term, escape="\\"))
    status = request.args.get("status", "")
    if status:
        statuses = status.split("|")
        if len(statuses) > 12 or any(len(s) > 80 for s in statuses):
            problem("Invalid status filter")
        query = query.where(model.status.in_(statuses))
    for field in ("rfqId", "poId", "orderId", "invoiceId", "quotationId", "requestId"):
        if request.args.get(field):
            column = store.FIELDS[key].get(field)
            if not column:
                problem("Unsupported reference filter")
            query = query.where(getattr(model, column) == request.args[field])
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.session.scalars(
        query.order_by(model.position, model.id).offset((page - 1) * size).limit(size)
    )
    return jsonify(
        items=[output(key, r) for r in rows], total=total, page=page, pageSize=size
    )


@bp.get("/<key>/<identity>")
def details(key, identity):
    row = scoped(key, identity)
    return jsonify(record=output(key, row, True), context=context(key, row))


@bp.post("/<key>")
@bp.patch("/<key>/<identity>")
@bp.post("/<key>/<identity>/actions/<action>")
def command(key, identity=None, action=None):
    value, revision = execute(key, identity, action)
    row = scoped(key, value["id"])
    return jsonify(
        record=output(key, row, True), context=context(key, row), revision=revision
    )


@bp.get("/summary/<area>")
def summary(area):
    if area not in ("sales", "purchase"):
        problem("Unknown dashboard", 404)
    keys = (
        (
            "salesQuotations",
            "salesOrders",
            "deliveries",
            "customerInvoices",
            "customerPayments",
        )
        if area == "sales"
        else (
            "requests",
            "rfqs",
            "quotations",
            "orders",
            "receipts",
            "invoices",
            "payments",
        )
    )
    require_migrated()
    state = app_document().stored_data
    registers = []
    for key in keys:
        if not allowed(g.user, state, COLLECTIONS[key]):
            continue
        model = store.MODELS[key]
        count = db.session.scalar(
            select(func.count()).select_from(model).where(visibility(key))
        )
        value_column = (
            model.amount
            if key in ("customerInvoices", "customerPayments", "invoices", "payments")
            else model.estimated_total if key == "rfqs" else model.total
        )
        value = db.session.scalar(
            select(func.coalesce(func.sum(value_column), 0)).where(visibility(key))
        )
        registers.append(dict(key=key, count=count, total=float(value or 0)))
    if not registers:
        problem("No transaction dashboard permissions", 403)
    return jsonify(registers=registers, currency="PKR")


PRINT_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} — {{number}}</title><style>body{font:14px Arial,sans-serif;color:#172338;margin:32px}header{border-bottom:2px solid #253374;margin-bottom:20px;display:flex;justify-content:space-between;gap:24px}h1{font-size:24px}h2{font-size:18px}table{border-collapse:collapse;width:100%;margin:20px 0}th,td{border:1px solid #d7dde8;text-align:left;padding:9px}th{background:#f2f5fa}.fields{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.total{text-align:right;font-size:18px}.notes{white-space:pre-wrap}.print{padding:10px 16px}@media print{.print{display:none}body{margin:12mm}tr{break-inside:avoid}}</style></head><body><header><div><h2>{{company.get('name','Company')}}</h2><p>{{company.get('address','')}}</p><p>{{company.get('email','')}} {{company.get('phone','')}}</p><p>NTN / Tax number: {{company.get('taxNumber','')}}</p></div><div><h1>{{title}}</h1><p>{{number}}</p><p>{{record.get('status','')}}</p></div></header><div class="fields">{% for label,value in fields %}<div><b>{{label}}</b><br>{{value if value is not none else ''}}</div>{% endfor %}</div>{% if lines %}<table><thead><tr><th>Item</th><th>Description</th><th>Qty</th><th>Unit</th><th>Rate</th><th>Tax %</th><th>Discount %</th><th>Total (PKR)</th></tr></thead><tbody>{% for item in lines %}<tr><td>{{item.get('productName','')}}</td><td>{{item.get('description','')}}</td><td>{{item.get('quantity',item.get('deliveredQty',item.get('acceptedQty','')))}}</td><td>{{item.get('unit','')}}</td><td>{{item.get('rate',item.get('quotedRate',''))}}</td><td>{{item.get('taxPercent','')}}</td><td>{{item.get('discountPercent','')}}</td><td>{{item.get('total','')}}</td></tr>{% endfor %}</tbody></table>{% endif %}{% if receipt %}<h2>Inspection / Receipt</h2><table><thead><tr><th>Item</th><th>Ordered</th><th>Received</th><th>Accepted</th><th>Rejected</th><th>Inspection / Remark</th></tr></thead><tbody>{% for item in receipt %}<tr><td>{{item.get('productName','')}}</td><td>{{item.get('orderedQty','')}}</td><td>{{item.get('receivedQty','')}}</td><td>{{item.get('acceptedQty','')}}</td><td>{{item.get('rejectedQty','')}}</td><td>{{item.get('inspection','')}} {{item.get('remark','')}}</td></tr>{% endfor %}</tbody></table>{% endif %}{% if source_lines %}<h2>Complete source quotation / order — {{source_number}}</h2><table><thead><tr><th>Item</th><th>Ordered Qty</th><th>Rate</th><th>Total (PKR)</th></tr></thead><tbody>{% for item in source_lines %}<tr><td>{{item.get('productName','')}}</td><td>{{item.get('quantity','')}}</td><td>{{item.get('rate',item.get('quotedRate',''))}}</td><td>{{item.get('total','')}}</td></tr>{% endfor %}</tbody></table>{% endif %}{% if invoices %}<h2>Related Customer Invoices (up to 25)</h2><table><thead><tr><th>Invoice</th><th>Amount (PKR)</th><th>Status</th></tr></thead><tbody>{% for invoice in invoices %}<tr><td>{{invoice.invoiceNo}}</td><td>{{invoice.amount}}</td><td>{{invoice.status}}</td></tr>{% endfor %}</tbody></table>{% endif %}{% if record.get('vendors') %}<h2>Invited Vendors</h2><table><thead><tr><th>Supplier</th><th>Email</th><th>Contact</th></tr></thead><tbody>{% for vendor in record.vendors %}<tr><td>{{vendor.get('name','')}}</td><td>{{vendor.get('email','')}}</td><td>{{vendor.get('contact','')}}</td></tr>{% endfor %}</tbody></table>{% endif %}{% if 'subtotal' in record %}<p class="total">Subtotal: PKR {{record.subtotal}}</p>{% endif %}{% if 'taxAmount' in record %}<p class="total">Tax: PKR {{record.taxAmount}}</p>{% endif %}<p class="total">Total: PKR {{record.get('amount',record.get('total',record.get('estimatedTotal','—')))}}</p>{% if 'balance' in record %}<p class="total">Paid: PKR {{record.get('paidAmount',0)}} · Balance: PKR {{record.get('balance',0)}}</p>{% endif %}<p class="notes">{{record.get('terms','')}}</p><p class="notes">{{record.get('notes','')}}</p><p>Pakistan · PKR · WH / Stock</p><button type="button" class="print" onclick="window.print()">Print / Save as PDF</button></body></html>"""
TITLES = {
    "requests": "Purchase Request",
    "rfqs": "Request for Quotation",
    "quotations": "Vendor Quotation",
    "comparisons": "Quotation Award",
    "orders": "Purchase Order",
    "receipts": "Goods Receipt Note",
    "invoices": "Vendor Bill",
    "payments": "Supplier Payment",
    "salesQuotations": "Sales Quotation",
    "salesOrders": "Sales Order",
    "deliveries": "Delivery Challan",
    "customerInvoices": "Customer Invoice",
    "customerPayments": "Customer Payment Receipt",
}


@bp.get("/<key>/<identity>/print")
def document_print(key, identity):
    row = scoped(key, identity)
    permit(key, "export")
    value = store.record(key, row)
    ctx = context(key, row)
    fields = [
        (label, value.get(field))
        for field, label in [
            ("customerName", "Customer"),
            ("vendorName", "Vendor"),
            (store.SPECS[key][2], "Date"),
            ("dueDate", "Due date"),
            ("quotationNo", "Quotation"),
            ("orderNo", "Sales Order"),
            ("poNo", "Purchase Order"),
            ("invoiceNo", "Invoice"),
            ("referenceNo", "Reference"),
            ("paymentTerms", "Payment Terms"),
            ("deliveryTerms", "Delivery Terms"),
            ("method", "Payment Method"),
            ("department", "Department"),
            ("requester", "Requester"),
            ("requiredDate", "Required Date"),
            ("priority", "Priority"),
            ("validUntil", "Valid Until"),
            ("vendorTRN", "Vendor NTN / Tax Number"),
            ("deliveryTime", "Delivery Time"),
        ]
        if value.get(field) is not None
    ]
    economic_lines = value.get("lineItems", value.get("items", []))
    if not isinstance(economic_lines, list):
        economic_lines = []
    response = make_response(
        render_template_string(
            PRINT_TEMPLATE,
            title=TITLES[key],
            number=row.number or str(row.original_id),
            company=app_document().stored_data.get("company", {}),
            record=value,
            fields=fields,
            lines=economic_lines if key != "receipts" else [],
            receipt=economic_lines if key == "receipts" else [],
            source_lines=ctx.get("sourceLines", []),
            source_number=ctx.get("sourceNumber", ""),
            invoices=ctx.get("invoices", []),
        )
    )
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response
