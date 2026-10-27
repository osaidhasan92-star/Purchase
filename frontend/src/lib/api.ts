import type {
  Bridge,
  Customer,
  CustomerPage,
  CustomerValues,
  CustomerDetails,
} from "../types";
export function customerApi(bridge: Bridge) {
  return {
    details: (id: string | number) =>
      bridge.request<CustomerDetails>(
        "/customers/" + encodeURIComponent(String(id)),
      ),
    list: (page: number, search: string) =>
      bridge.request<CustomerPage>(
        "/customers?" +
          new URLSearchParams({ page: String(page), pageSize: "25", search }),
      ),
    create: (values: CustomerValues, requestKey: string) =>
      bridge.request<{ customer: Customer }>("/customers", {
        method: "POST",
        body: JSON.stringify({ ...values, requestKey }),
      }),
    update: (customer: Customer, values: CustomerValues) =>
      bridge.request<{ customer: Customer }>(
        "/customers/" + encodeURIComponent(String(customer.id)),
        {
          method: "PATCH",
          body: JSON.stringify({ ...values, version: customer.version }),
        },
      ),
  };
}
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Unable to complete the request.";
