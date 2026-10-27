import { useEffect, useRef, useState, type FormEvent } from "react";
import { flushSync } from "react-dom";
import type {
  Bridge,
  Customer,
  CustomerPage,
  CustomerValues,
  CustomerDetails,
} from "../../types";
import { customerApi, errorMessage } from "../../lib/api";
export interface CustomerCommands {
  open: () => void;
  save: () => Promise<void>;
}
export function CustomersPage({
  bridge,
  commands,
}: {
  bridge: Bridge;
  commands: CustomerCommands;
}) {
  const [data, setData] = useState<CustomerPage>({
    items: [],
    total: 0,
    page: 1,
    pageSize: 25,
  });
  const [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [editing, setEditing] = useState<Customer | null | undefined>(
      undefined,
    ),
    [saving, setSaving] = useState(false),
    [formError, setFormError] = useState("");
  const [readonly, setReadonly] = useState(false),
    [details, setDetails] = useState<CustomerDetails | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const form = useRef<HTMLFormElement>(null),
    busy = useRef(false),
    key = useRef("");
  const api = customerApi(bridge);
  useEffect(() => {
    if (editing === undefined || !dialog.current) return;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusable = () =>
      Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
        ) || [],
      );
    focusable()[0]?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy.current) {
        event.preventDefault();
        setEditing(undefined);
      }
      if (event.key === "Tab") {
        const items = focusable(),
          first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    const current = dialog.current;
    current.addEventListener("keydown", keyboard);
    return () => {
      current.removeEventListener("keydown", keyboard);
      if (previous?.isConnected) previous.focus();
    };
  }, [editing === undefined]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api
      .list(page, search)
      .then((result) => {
        if (active) {
          setData(result);
          bridge.cacheCustomers(result.items);
        }
      })
      .catch((failure) => {
        if (active) setError(errorMessage(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, search, reload, bridge]);
  useEffect(() => {
    if (!readonly || !editing) return;
    let active = true;
    api
      .details(editing.id)
      .then((result) => {
        if (active) {
          setDetails(result);
          setEditing(result.customer);
        }
      })
      .catch((failure) => {
        if (active) setFormError(errorMessage(failure));
      });
    return () => {
      active = false;
    };
  }, [readonly, editing?.id]);
  const open = (customer: Customer | null, viewOnly = false) => {
    setReadonly(viewOnly);
    setDetails(null);
    setFormError("");
    key.current =
      "customer-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    setEditing(customer);
  };
  const save = async () => {
    if (readonly || busy.current || !form.current) return;
    if (!form.current.reportValidity()) return;
    const values = Object.fromEntries(new FormData(form.current).entries());
    const normalized: CustomerValues = {
      name: String(values.name || ""),
      contact: String(values.contact || ""),
      phone: String(values.phone || ""),
      email: String(values.email || ""),
      category: String(values.category || ""),
      paymentTerms: String(values.paymentTerms || "Cash"),
      status: String(values.status || "Active"),
      address: String(values.address || ""),
      creditLimit: Number(values.creditLimit || 0),
    };
    busy.current = true;
    setSaving(true);
    setFormError("");
    try {
      const result = editing
        ? await api.update(editing, normalized)
        : await api.create(normalized, key.current);
      // Keep only this record/page in the compatibility cache; no aggregate save occurs.
      bridge.cacheCustomers([
        result.customer,
        ...data.items.filter(
          (item) => String(item.id) !== String(result.customer.id),
        ),
      ]);
      setData((previous) => ({
        ...previous,
        items: [
          result.customer,
          ...previous.items.filter(
            (item) => String(item.id) !== String(result.customer.id),
          ),
        ],
      }));
      setEditing(undefined);
      setPage(1);
      setReload((value) => value + 1);
      bridge.toast(editing ? "Customer updated" : "Customer added");
    } catch (failure) {
      setFormError(errorMessage(failure));
      if (
        typeof failure === "object" &&
        failure !== null &&
        "status" in failure &&
        failure.status === 409
      )
        setReload((value) => value + 1);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };
  commands.open = () => flushSync(() => open(null));
  commands.save = save;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void save();
  };
  const format = (amount: number) =>
    "Rs " +
    Number(amount || 0).toLocaleString("en-PK", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  return (
    <>
      <div className="section-card" data-screen="customers-react">
        <div className="section-head">
          <div>
            <div className="section-title">Customer List</div>
            <div className="hint">
              Shared customer master for authorized CRM, Sales and Finance users
            </div>
          </div>
          {bridge.can("sales_customers", "create") && (
            <button
              className="btn-primary"
              type="button"
              onClick={() => open(null)}
            >
              Add Customer
            </button>
          )}
        </div>
        <form
          className="filters"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch(
              String(
                new FormData(event.currentTarget).get("search") || "",
              ).trim(),
            );
            setPage(1);
            setReload((value) => value + 1);
          }}
        >
          <input
            id="cust-search"
            name="search"
            maxLength={160}
            placeholder="Search name, code, phone or email"
            aria-label="Search customers"
          />
          <button className="btn-secondary" type="submit">
            Search
          </button>
        </form>
        {error && (
          <p role="alert" className="modern-error">
            {error}{" "}
            <button
              type="button"
              onClick={() => setReload((value) => value + 1)}
            >
              Try again
            </button>
          </p>
        )}
        <div className="table-wrap" aria-busy={loading}>
          <table>
            <thead>
              <tr>
                {[
                  "Code",
                  "Customer",
                  "Contact",
                  "Phone",
                  "Email",
                  "Payment Terms",
                  "Credit Limit",
                  "Status",
                  "Actions",
                ].map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="empty">
                    Loading customers…
                  </td>
                </tr>
              ) : data.items.length ? (
                data.items.map((customer) => (
                  <tr key={customer.id}>
                    <td>{customer.code}</td>
                    <td>
                      <b>{customer.name}</b>
                    </td>
                    <td>{customer.contact}</td>
                    <td>{customer.phone}</td>
                    <td>{customer.email}</td>
                    <td>{customer.paymentTerms}</td>
                    <td>{format(customer.creditLimit)}</td>
                    <td>{customer.status}</td>
                    <td>
                      <button
                        type="button"
                        className="btn-sm"
                        onClick={() => open(customer, true)}
                      >
                        Details
                      </button>{" "}
                      {bridge.can("sales_customers", "edit") && (
                        <button
                          type="button"
                          className="btn-sm"
                          onClick={() => open(customer)}
                        >
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="empty">
                    No customers found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="modern-pagination">
          <span>
            {data.total} customers · Page {page} of{" "}
            {Math.max(1, Math.ceil(data.total / data.pageSize))}
          </span>
          <div>
            <button
              className="btn-secondary"
              type="button"
              disabled={loading || page <= 1}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous
            </button>
            <button
              className="btn-secondary"
              type="button"
              disabled={loading || page * data.pageSize >= data.total}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>
      {editing !== undefined && (
        <div className="modal" id="modal">
          <div
            className="modal-box request-modal"
            ref={dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="customer-dialog-title"
          >
            <div className="modal-head">
              <h3 id="customer-dialog-title">
                {readonly
                  ? "Customer Details"
                  : editing
                    ? "Edit Customer"
                    : "Add Customer"}
              </h3>
              <button
                type="button"
                disabled={saving}
                aria-label="Close customer form"
                onClick={() => setEditing(undefined)}
              >
                ×
              </button>
            </div>
            <form ref={form} onSubmit={submit} key={editing?.version || "new"}>
              <div className="modal-body">
                <fieldset
                  className="modern-fieldset"
                  disabled={readonly || saving}
                >
                  <div className="grid2">
                    {[
                      ["name", "Customer Name", "cname"],
                      ["contact", "Contact Person", "ccontact"],
                      ["phone", "Phone", "cphone"],
                      ["email", "Email", "cemail"],
                      ["category", "Category", "ccat"],
                    ].map(([name, label, id]) => (
                      <label key={name}>
                        {label}
                        <input
                          id={id}
                          name={name}
                          type={name === "email" ? "email" : "text"}
                          required={name === "name"}
                          maxLength={
                            name === "email"
                              ? 254
                              : name === "phone"
                                ? 80
                                : name === "category"
                                  ? 100
                                  : 160
                          }
                          defaultValue={String(
                            editing?.[name as keyof Customer] || "",
                          )}
                        />
                      </label>
                    ))}
                    <label>
                      Payment Terms
                      <select
                        id="cterms"
                        name="paymentTerms"
                        defaultValue={editing?.paymentTerms || "Cash"}
                      >
                        {["Cash", "15 Days", "30 Days", "45 Days"].map(
                          (term) => (
                            <option key={term}>{term}</option>
                          ),
                        )}
                      </select>
                    </label>
                    <label>
                      Credit Limit
                      <input
                        id="climit"
                        name="creditLimit"
                        type="number"
                        min="0"
                        max="1000000000000"
                        step="0.01"
                        defaultValue={editing?.creditLimit || 0}
                      />
                    </label>
                    <label>
                      Status
                      <select
                        id="cstatus"
                        name="status"
                        defaultValue={editing?.status || "Active"}
                      >
                        <option>Active</option>
                        <option>Inactive</option>
                      </select>
                    </label>
                  </div>
                  <label>
                    Address
                    <textarea
                      id="caddress"
                      name="address"
                      rows={2}
                      maxLength={1000}
                      defaultValue={editing?.address || ""}
                    />
                  </label>
                </fieldset>
                {readonly && bridge.can("sales_orders") && (
                  <section>
                    <h4>Sales orders</h4>
                    <p>
                      {details
                        ? details.orderTotal +
                          " authorized orders (latest 25 shown)"
                        : "Loading orders…"}
                    </p>
                    {details && (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Order</th>
                              <th>Date</th>
                              <th>Status</th>
                              <th>Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {details.orders.map((order) => (
                              <tr key={order.id}>
                                <td>{order.orderNo}</td>
                                <td>{order.orderDate}</td>
                                <td>{order.status}</td>
                                <td>{format(order.total)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                )}
                {formError && (
                  <p role="alert" className="modern-error">
                    {formError} Close and reopen the record if it changed.
                  </p>
                )}
              </div>
              <div className="modal-foot">
                <button
                  className="btn-secondary"
                  type="button"
                  disabled={saving}
                  onClick={() => setEditing(undefined)}
                >
                  {readonly ? "Close" : "Cancel"}
                </button>
                {!readonly && (
                  <button
                    className="btn-primary"
                    type="submit"
                    disabled={saving}
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
