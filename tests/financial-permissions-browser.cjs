const assert = require("node:assert/strict");
module.exports = async (page, base) => {
  const me = await (
    await page.context().request.get(base + "/api/auth/me")
  ).json();
  const password = "Dashboard-permission-test-42";
  const created = await page
    .context()
    .request.post(base + "/api/administration/commands/create-user", {
      headers: { "X-CSRF-Token": me.csrfToken },
      data: {
        requestKey: "dashboard-restricted-user",
        name: "Restricted Dashboard User",
        email: "dashboard-restricted@example.test",
        password,
        role: "Salesperson",
        managerId: me.user.id,
        active: true,
      },
    });
  assert.equal(created.status(), 200, await created.text());
  const restricted = page.context();
  const adminCookies = await restricted.cookies();
  let screen;
  try {
    await restricted.clearCookies();
    const login = await restricted.request.post(base + "/api/auth/login", {
      data: { email: "dashboard-restricted@example.test", password },
    });
    assert.equal(login.status(), 200);
    const summary = await (
      await restricted.request.get(base + "/api/trade/summary/sales")
    ).json();
    assert.deepEqual(summary.balances, {});
    assert.ok(
      !summary.registers.some((r) =>
        ["customerInvoices", "customerPayments"].includes(r.key),
      ),
    );
    assert.equal(
      (
        await restricted.request.get(base + "/api/trade/customerInvoices")
      ).status(),
      403,
    );
    assert.equal(
      (
        await restricted.request.get(base + "/api/trade/customerPayments")
      ).status(),
      403,
    );
    screen = await restricted.newPage();
    for (const width of [1366, 390]) {
      await screen.setViewportSize({ width, height: 844 });
      await screen.goto(base + "/erp.html?view=sales");
      for (const label of ["Collected", "Receivables"]) {
        const card = screen.locator(".ref-kpi").filter({
          has: screen.locator(".ref-kpi-label", { hasText: label }),
        });
        await card.getByText("Unavailable", { exact: true }).waitFor();
        assert.ok(
          (await card.textContent()).includes(
            label === "Collected"
              ? "Requires payment access"
              : "Requires invoice access",
          ),
        );
        assert.ok(!(await card.textContent()).includes("Rs 0.00"));
      }
      await screen
        .getByText("You do not have access to this register.", { exact: true })
        .waitFor();
      assert.equal(
        await screen.evaluate(() => document.documentElement.scrollWidth),
        width,
      );
    }
    await screen.close();
    screen = undefined;
    await restricted.clearCookies();
    await restricted.addCookies(adminCookies);
    // Authorized zero is a real amount; a missing API field is not a zero.
    await page.route("**/api/trade/summary/sales", async (route) => {
      const response = await route.fetch(),
        data = await response.json();
      data.balances = { collected: 0, outstanding: 0 };
      await route.fulfill({ response, json: data });
    });
    await page.goto(base + "/erp.html?view=sales");
    for (const label of ["Collected", "Receivables"])
      await page
        .locator(".ref-kpi")
        .filter({ has: page.locator(".ref-kpi-label", { hasText: label }) })
        .getByText("Rs 0.00", { exact: true })
        .waitFor();
    await page.unroute("**/api/trade/summary/sales");
    await page.route("**/api/trade/summary/sales", async (route) => {
      const response = await route.fetch(),
        data = await response.json();
      data.balances = {};
      await route.fulfill({ response, json: data });
    });
    await page.reload();
    for (const label of ["Collected", "Receivables"])
      await page
        .locator(".ref-kpi")
        .filter({ has: page.locator(".ref-kpi-label", { hasText: label }) })
        .getByText("Unavailable", { exact: true })
        .waitFor();
    console.log(
      "Financial permissions: restricted API/UI, authorized zero and missing data passed",
    );
  } finally {
    await page.unroute("**/api/trade/summary/sales");
    await screen?.close();
    await restricted.clearCookies();
    await restricted.addCookies(adminCookies);
  }
};
