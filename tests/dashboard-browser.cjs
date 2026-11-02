const assert = require("node:assert/strict");
const path = require("node:path");
module.exports = async (page, base) => {
  for (const viewport of [
    { width: 1366, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    for (const [view, heading] of [
      ["crm-dashboard", "Revenue & Pipeline"],
      ["sales", "Sales Order Trend"],
      ["purchase-dashboard", "Purchase Order Trend"],
    ]) {
      await page.goto(base + "/erp.html?view=" + view);
      const dashboard = page.locator(".reference-dashboard");
      await dashboard.locator('[aria-busy="false"]').first().waitFor();
      await dashboard
        .getByRole("heading", { name: heading, exact: true })
        .waitFor();
      assert.equal(await dashboard.locator(".ref-kpi").count(), 4);
      assert.equal(await dashboard.getByRole("img").count(), 1);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth),
        viewport.width,
        view + ": viewport fit",
      );
      const clipped = await dashboard.evaluate(
        (el) =>
          Array.from(el.querySelectorAll(".ref-panel,.ref-kpi")).filter(
            (node) => {
              const r = node.getBoundingClientRect();
              return r.x < 0 || r.right > innerWidth + 1;
            },
          ).length,
      );
      assert.equal(clipped, 0, view + ": no clipped cards");
      const cols = await dashboard
        .locator(".ref-kpis")
        .evaluate(
          (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
        );
      assert.equal(
        cols,
        view === "crm-dashboard" || viewport.width === 390 ? 2 : 4,
        view + ": reference KPI grid",
      );
      if (view === "crm-dashboard") {
        const year = dashboard.getByLabel("Lead closing year");
        await year.selectOption(String(new Date().getFullYear() - 1));
        await dashboard.locator('[aria-busy="false"]').first().waitFor();
        await year.selectOption("");
        await dashboard.locator('[aria-busy="false"]').first().waitFor();
      }
      await page.screenshot({
        path: path.join(
          __dirname,
          "../test-results/reference-" + view + "-" + viewport.width + ".png",
        ),
        fullPage: true,
      });
      if (view === "sales") {
        const order = dashboard.locator(".ref-recent a").first();
        if (await order.count()) {
          const label = await order.locator("b").first().textContent();
          await order.click();
          await page
            .getByRole("textbox", { name: "Search sales orders", exact: true })
            .waitFor();
          assert.equal(
            await page
              .getByRole("textbox", {
                name: "Search sales orders",
                exact: true,
              })
              .inputValue(),
            label,
          );
        }
      }
    }
  }
  await require("./financial-permissions-browser.cjs")(page, base);
  await page.setViewportSize({ width: 1366, height: 900 });
  console.log(
    "Reference CRM/Sales/Purchase dashboards: desktop/mobile grids, charts, filters and navigation passed",
  );
};
