const assert = require("node:assert/strict");
const path = require("node:path");
module.exports = async (page, base) => {
  const goto = async () => {
    await page.goto(base + "/erp.html?view=accounting");
    await page
      .getByRole("heading", { name: "Financial Overview", exact: true })
      .waitFor();
  };
  const menu = async (label) => {
    await page.getByRole("button", { name: label, exact: true }).click();
    return page.getByRole("menu", { name: label, exact: true });
  };
  await goto();
  for (const width of [1366, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForFunction(
      () =>
        innerWidth > 900 ||
        document.querySelector(".sidebar").getBoundingClientRect().right <= 1,
    );
    const frame = page.locator('[data-dashboard="accounting"]');
    assert.equal(await frame.locator(".ref-kpi").count(), 4);
    assert.equal(await frame.locator(".ref-main-grid > .ref-panel").count(), 2);
    assert.equal(
      await frame.locator(".ref-three-grid > .ref-panel").count(),
      3,
    );
    assert.equal(await frame.getByRole("img").count(), 1);
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth),
      width,
    );
    await page.screenshot({
      path: path.join(
        __dirname,
        "../test-results/accounting-approved-" + width + ".png",
      ),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1366, height: 900 });
  for (const [label, view] of [
    ["Customers", "sales-invoices"],
    ["Vendors", "invoices"],
  ]) {
    const m = await menu(label);
    await m
      .getByRole("menuitem", {
        name: label === "Customers" ? "Customer Invoices" : "Vendor Bills",
        exact: true,
      })
      .click();
    await page.waitForURL("**/erp.html?view=" + view + "&module=accounting");
    await page.locator('[data-screen^="trade-"]').waitFor();
    assert.equal(
      await page.locator('[data-frontend="react"]').getAttribute("data-module"),
      "accounting",
    );
    assert.equal(await page.locator(".module-tab.active").textContent(), label);
    await goto();
  }
  for (const [label, view] of [
    ["New Invoice", "sales-invoices"],
    ["New Bill", "invoices"],
  ]) {
    await page.getByRole("link", { name: label, exact: true }).click();
    await page.getByRole("dialog").waitFor();
    assert.equal(new URL(page.url()).searchParams.get("view"), view);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await goto();
  }
  await page.getByRole("link", { name: "Profit & Loss", exact: true }).click();
  await page.getByRole("combobox", { name: "Report", exact: true }).waitFor();
  assert.equal(
    await page
      .getByRole("combobox", { name: "Report", exact: true })
      .inputValue(),
    "pnl",
  );
  await goto();
  await page
    .getByRole("link", { name: "Aged Receivables", exact: true })
    .click();
  await page.getByLabel("Aging account", { exact: true }).waitFor();
  assert.equal(
    await page.getByLabel("Aging account", { exact: true }).inputValue(),
    "1100",
  );
  await goto();
  await page
    .getByRole("link", { name: "Reconcile Transactions", exact: true })
    .click();
  await page
    .locator('[data-native-finance="bank"][aria-busy="false"]')
    .waitFor();
  assert.equal(new URL(page.url()).searchParams.get("status"), "Unmatched");
  await goto();
  const m = await menu("Bank & Cash");
  await m
    .getByRole("menuitem", { name: "Bank / Cash Transfer", exact: true })
    .click();
  await page.getByRole("dialog").waitFor();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await goto();
  const draft = page.locator(".acct-invoice-counts a").first();
  const target = new URL(await draft.getAttribute("href"), base);
  await draft.click();
  await page.getByLabel("From date", { exact: true }).waitFor();
  assert.equal(
    await page.getByLabel("From date", { exact: true }).inputValue(),
    target.searchParams.get("from"),
  );
  assert.equal(
    await page.getByLabel("To date", { exact: true }).inputValue(),
    target.searchParams.get("to"),
  );
  await goto();
  await page
    .getByLabel("Accounting period", { exact: true })
    .selectOption("all");
  await page
    .locator('[data-native-finance="accounting"][aria-busy="false"]')
    .waitFor();
  assert.equal(
    await page.getByLabel("Accounting period", { exact: true }).inputValue(),
    "all",
  );
  const headings = await page
    .locator(".acct-transactions th")
    .allTextContents();
  assert.deepEqual(headings, [
    "Date",
    "Document",
    "Partner",
    "Amount",
    "Document Status",
    "Payment Status",
  ]);
  await menu("Configuration");
  await page.keyboard.press("Escape");
  await page.getByRole("menu").waitFor({ state: "hidden" });
  assert.equal(
    await page
      .getByRole("button", { name: "Configuration", exact: true })
      .evaluate((el) => el === document.activeElement),
    true,
  );
  console.log(
    "Accounting design: layout, menus, invoice/bill create forms, report/aging shortcuts, reconciliation, transfers and period filter passed",
  );
};
