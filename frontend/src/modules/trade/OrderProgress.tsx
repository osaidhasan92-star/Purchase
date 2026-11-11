import type { Bridge } from "../../types";
import { configs, route, type Resource, type TradeContext } from "./types";
export function OrderProgress({
  context,
  bridge,
  customer,
}: {
  context: TradeContext;
  bridge: Bridge;
  customer: boolean;
}) {
  return (
    <section aria-label="Fulfillment and returns">
      <h4>Fulfillment, returns and credits</h4>
      <div className="finance-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {[
                "Product",
                "Ordered",
                ...(!customer ? ["Received", "Rejected"] : []),
                customer ? "Delivered" : "Accepted",
                "Returned",
                "Net fulfilled",
                "Invoiced / billed",
                "Credited",
                "Remaining",
                "Closed remainder",
              ].map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {context.lines?.map((line) => (
              <tr key={line.lineIndex}>
                <td>{line.productName}</td>
                <td>{line.ordered}</td>
                {!customer && (
                  <>
                    <td>{line.receivedForInspection}</td>
                    <td>{line.rejected}</td>
                  </>
                )}
                <td>{line.fulfilled}</td>
                <td>{line.returned}</td>
                <td>{line.netFulfilled}</td>
                <td>
                  {context.financialQuantitiesAvailable
                    ? line.invoiced
                    : "Unavailable"}
                </td>
                <td>
                  {context.creditQuantitiesAvailable
                    ? line.credited
                    : "Unavailable"}
                </td>
                <td>{line.remaining}</td>
                <td>{line.closedRemaining}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        Invoice quantities include active drafts. Credited quantities count
        posted credit notes; refunds and applications are recorded separately in
        credit details.
      </p>
      {!context.financialQuantitiesAvailable && (
        <p className="hint">
          Invoice and credit quantities require access to the related financial
          register.
        </p>
      )}
      <p className="hint">
        Stock returns and financial credits are separate. Customer returns
        remain in Returns until inspected and approved for transfer to Stock.
        Keep the remainder open for replacement, or close it after resolving
        excess invoices. Credits can be applied or refunded in Accounting.
      </p>
      {customer && bridge.can("inventory") && (
        <p>
          <a
            className="btn-secondary"
            href="erp.html?view=warehouse&area=locations"
          >
            Inspect returned goods
          </a>
        </p>
      )}
      {!customer && (
        <p className="hint">
          Quantities rejected during receipt inspection never enter stock.
          Return previously accepted goods through their original receipt; then
          create a vendor credit from the linked bill.
        </p>
      )}
      <h4>Related fulfillment and financial documents</h4>
      <p className="hint">
        Up to 25 documents per register. Each link follows your existing
        permissions.
      </p>
      <ul>
        {context.relatedDocuments?.map((doc) => {
          if (doc.resource === "credits")
            return (
              <li key={"credit-" + doc.id}>
                <a
                  href={
                    "erp.html?view=credits&module=accounting&kind=" +
                    doc.kind +
                    "&creditId=" +
                    doc.id
                  }
                >
                  {doc.number}
                </a>{" "}
                · {doc.status} · Apply / refund in credit details
              </li>
            );
          const resource = doc.resource as Resource;
          return (
            <li key={doc.resource + "-" + doc.id}>
              <a
                href={
                  route(resource) +
                  "&documentId=" +
                  encodeURIComponent(String(doc.id))
                }
              >
                {doc.number}
              </a>{" "}
              · {doc.status}
              {["receipts", "deliveries"].includes(resource) &&
                bridge.can("inventory") && (
                  <>
                    {" "}
                    ·{" "}
                    <a
                      href={
                        "erp.html?view=stock-moves&search=" +
                        encodeURIComponent(resource + ":" + doc.id + ":")
                      }
                    >
                      Return goods / stock history
                    </a>
                  </>
                )}
              {["invoices", "customerInvoices"].includes(resource) &&
                bridge.can("accounting", "create") &&
                ["Posted", "Approved", "Partially Paid", "Paid"].includes(
                  doc.status,
                ) && (
                  <>
                    {" "}
                    ·{" "}
                    <a
                      href={
                        "erp.html?view=credits&module=accounting&kind=" +
                        (customer ? "customer" : "vendor") +
                        "&invoiceId=" +
                        encodeURIComponent(String(doc.id))
                      }
                    >
                      Create credit note
                    </a>
                  </>
                )}
              <span className="sr-only">{configs[resource].singular}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
