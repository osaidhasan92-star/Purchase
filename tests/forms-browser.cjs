const assert = require("node:assert/strict");
const path = require("node:path");

module.exports = async (page, base) => {
  const forms = [
    ["customers", "Add Customer"],
    ["vendors", "Add Vendor"],
    ["products", "Add Product"],
    ["leads", "Add Lead"],
    ["reminders", "Add Reminder"],
    ["companies", "Add Company"],
    ["crm-quotes", "New Tracking Quote"],
    ["requests", "New Purchase Request"],
    ["rfqs", "New RFQ"],
    ["quotations", "New Vendor Quotation"],
    ["orders", "New Purchase Order"],
    ["receipts", "New Goods Receipt"],
    ["invoices", "New Vendor Bill"],
    ["payments", "New Supplier Payment"],
    ["sales-quotations", "New Sales Quotation"],
    ["sales-orders", "New Sales Order"],
    ["sales-deliveries", "New Delivery"],
    ["sales-invoices", "New Customer Invoice"],
    ["sales-payments", "New Customer Payment"],
    ["hr-employees", "Add Employee"],
    ["hr-manpower", "Add Manpower Request"],
    ["hr-recruitment", "Add Candidate"],
    ["hr-attendance", "Add Attendance"],
    ["hr-leave", "Add Leave Request"],
    ["hr-payroll", "Add Payroll"],
    ["accounts", "New Account"],
    ["journals", "New Journal Entry"],
    ["inventory", "Stock Adjustment"],
    ["boms", "New BoM"],
    ["production-orders", "New Manufacturing Order"],
    ["expense-claims", "New Expense"],
    ["users", "Add User"],
  ];
  const writes = [];
  const record = (request) => {
    if (
      new URL(request.url()).pathname.startsWith("/api/") &&
      ["POST", "PUT", "PATCH", "DELETE"].includes(request.method())
    )
      writes.push(request.method() + " " + new URL(request.url()).pathname);
  };
  page.on("request", record);
  try {
    for (const viewport of [
      { width: 1366, height: 900 },
      { width: 390, height: 600 },
    ]) {
      await page.setViewportSize(viewport);
      for (const [view, label] of forms) {
        await page.goto(base + "/erp.html?view=" + view);
        const pagination = page.locator(".modern-pagination button").first();
        if (await pagination.count()) {
          assert.ok(
            (await pagination.evaluate(
              (el) => el.getBoundingClientRect().height,
            )) >= 40,
            view + ": pagination uses shared buttons",
          );
        }
        const opener = page.getByRole("button", { name: label, exact: true });
        await opener.click();
        const dialog = page.getByRole("dialog");
        await dialog.waitFor();
        const cancel = dialog.getByRole("button", {
          name: "Cancel",
          exact: true,
        });
        const geometry = await dialog.evaluate((el) => {
          const rect = (e) => {
            const r = e.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
          };
          return {
            dialog: rect(el),
            overlay: rect(el.parentElement),
            pageWidth: document.documentElement.scrollWidth,
            locked: getComputedStyle(document.body).overflow,
          };
        });
        assert.equal(
          geometry.overlay.height,
          viewport.height,
          view + ": backdrop covers viewport",
        );
        assert.equal(
          geometry.overlay.width,
          viewport.width,
          view + ": backdrop width",
        );
        assert.ok(
          geometry.dialog.x >= 0 && geometry.dialog.y >= 0,
          view + ": dialog position",
        );
        assert.ok(
          geometry.dialog.x + geometry.dialog.width <= viewport.width + 1,
          view + ": dialog width",
        );
        assert.ok(
          geometry.dialog.y + geometry.dialog.height <= viewport.height + 1,
          view + ": dialog height",
        );
        assert.equal(
          geometry.pageWidth,
          viewport.width,
          view + ": no page horizontal overflow",
        );
        assert.equal(
          geometry.locked,
          "hidden",
          view + ": background scroll locked",
        );
        const clipped = await dialog.evaluate((el) => {
          const box = el.getBoundingClientRect();
          return Array.from(
            el.querySelectorAll("input:not([type=hidden]), select, textarea"),
          )
            .filter((field) => field.getClientRects().length)
            .filter((field) => {
              const r = field.getBoundingClientRect();
              return r.x < box.x - 1 || r.right > box.right + 1;
            })
            .map((field) => field.name || field.id);
        });
        assert.deepEqual(clipped, [], view + ": fields fit dialog width");
        const misaligned = await dialog.evaluate((el) =>
          Array.from(
            el.querySelectorAll(
              "input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea",
            ),
          )
            .filter((field) => field.getClientRects().length)
            .filter(
              (field) =>
                field.getBoundingClientRect().height < 40 ||
                getComputedStyle(field).fontWeight !== "400",
            )
            .map((field) => field.name || field.id),
        );
        assert.deepEqual(
          misaligned,
          [],
          view + ": consistent control height and text weight",
        );
        await cancel.scrollIntoViewIfNeeded();
        const footerGap = await cancel.evaluate((el) => {
          const footer = el.closest(".modal-foot"),
            form = footer?.parentElement;
          if (
            !form?.matches(".trade-form") ||
            getComputedStyle(footer).position !== "sticky"
          )
            return 0;
          return (
            form.getBoundingClientRect().bottom -
            footer.getBoundingClientRect().bottom
          );
        });
        assert.ok(
          Math.abs(footerGap) <= 1,
          view + ": no fields show below sticky footer",
        );
        const style = await cancel.evaluate((el) => ({
          height: el.getBoundingClientRect().height,
          padding: parseFloat(getComputedStyle(el).paddingInlineStart),
          background: getComputedStyle(el).backgroundColor,
          type: el.type,
        }));
        assert.ok(
          style.height >= 40 && style.padding >= 12,
          view + ": styled Cancel hit area",
        );
        assert.equal(
          style.background,
          "rgb(255, 255, 255)",
          view + ": shared secondary button",
        );
        assert.equal(style.type, "button", view + ": Cancel does not submit");
        const bounds = await cancel.boundingBox();
        assert.ok(
          bounds.y >= 0 && bounds.y + bounds.height <= viewport.height + 1,
          view + ": footer reachable",
        );
        // Unsaved form contents must not be persisted by dismissal.
        const input = dialog
          .locator(
            "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not(:disabled)",
          )
          .first();
        if (
          (await input.count()) &&
          ["text", "email"].includes(
            (await input.getAttribute("type")) || "text",
          )
        )
          await input.fill("Cancelled demo input");
        writes.length = 0;
        await cancel.click();
        await dialog.waitFor({ state: "hidden" });
        assert.deepEqual(writes, [], view + ": Cancel sends no writes");
        assert.equal(
          await opener.evaluate((el) => document.activeElement === el),
          true,
          view + ": focus restored",
        );
        assert.notEqual(
          await page.evaluate(() => document.body.style.overflow),
          "hidden",
          view + ": scroll restored",
        );
        await opener.click();
        await dialog.waitFor();
        await page.keyboard.press("Escape");
        await dialog.waitFor({ state: "hidden" });
      }
      await page.goto(base + "/erp.html?view=hr-employees");
      await page
        .getByRole("button", { name: "Add Employee", exact: true })
        .click();
      await page.screenshot({
        path: path.join(
          __dirname,
          "../test-results/forms-hr-" + viewport.width + ".png",
        ),
      });
      await page.keyboard.press("Escape");
      await page.locator(".user-menu-trigger").click();
      await page
        .getByRole("button", { name: "Company profile", exact: true })
        .click();
      const profile = page.getByRole("dialog", {
        name: "Company profile",
        exact: true,
      });
      const cancel = profile.getByRole("button", {
        name: "Cancel",
        exact: true,
      });
      await cancel.scrollIntoViewIfNeeded();
      assert.ok(
        (await cancel.evaluate((el) => el.getBoundingClientRect().height)) >=
          40,
        "Company profile: shared button outside module-app",
      );
      writes.length = 0;
      await cancel.click();
      await profile.waitFor({ state: "hidden" });
      assert.deepEqual(writes, [], "Company profile: Cancel sends no writes");
    }
    // Closing one of two dialogs must keep the underlying page locked.
    await page
      .getByRole("button", { name: "Add Employee", exact: true })
      .click();
    await page.evaluate(() =>
      window.dispatchEvent(new Event("workspace:company-profile")),
    );
    await page
      .getByRole("dialog", { name: "Company profile", exact: true })
      .waitFor();
    assert.equal(await page.getByRole("dialog").count(), 2);
    const profile = page.getByRole("dialog", {
      name: "Company profile",
      exact: true,
    });
    await profile.getByRole("button", { name: "Cancel", exact: true }).click();
    await profile.waitFor({ state: "hidden" });
    assert.equal(
      await page.evaluate(() => getComputedStyle(document.body).overflow),
      "hidden",
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    assert.notEqual(
      await page.evaluate(() => document.body.style.overflow),
      "hidden",
    );
    await page.setViewportSize({ width: 1366, height: 900 });
    console.log(
      "Form layout and Cancel: " +
        (forms.length + 1) +
        " forms at desktop and mobile sizes; nested-dialog scroll lock",
    );
  } finally {
    page.off("request", record);
  }
};
