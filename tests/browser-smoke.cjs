const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");
(async () => {
  const { chromium } = require("playwright");
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "modern-browser-")),
    port = 21000 + Math.floor(Math.random() * 2000),
    base = "http://127.0.0.1:" + port;
  const python = process.env.PYTHON || "python",
    cwd = path.resolve(__dirname, ".."),
    password = "Browser-demo-test-only-42";
  const env = {
    ...process.env,
    DATABASE_URL: "sqlite:///" + path.join(temp, "test.sqlite"),
    COOKIE_SECURE: "false",
  };
  let server, browser;
  try {
    const setup = spawnSync(
      python,
      [
        "-c",
        `from backend.app import app,db,User\nfrom werkzeug.security import generate_password_hash\nwith app.app_context():\n result=app.test_cli_runner().invoke(args=['init-db'])\n assert result.exit_code==0,result.output\n db.session.add(User(id='browser-admin',name='Demo Administrator',email='browser@example.test',role='Admin',active=True,password_hash=generate_password_hash('${password}')))\n db.session.commit()`,
      ],
      { env, cwd, encoding: "utf8" },
    );
    assert.equal(setup.status, 0, setup.stderr);
    server = spawn(
      python,
      ["-m", "flask", "--app", "backend.app", "run", "--port", String(port)],
      { env, cwd, stdio: "ignore" },
    );
    for (let i = 0; i < 100; i++) {
      try {
        if ((await fetch(base + "/api/health")).ok) break;
      } catch {}
      await new Promise((r) => setTimeout(r, 40));
    }
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CHROMIUM_EXECUTABLE_PATH
        ? {
            executablePath: process.env.CHROMIUM_EXECUTABLE_PATH,
            args: JSON.parse(process.env.CHROMIUM_ARGS || "[]"),
          }
        : {}),
    });
    const context = await browser.newContext({
      viewport: { width: 1366, height: 900 },
    });
    await context.route("**/*", (route) =>
      route.request().url().startsWith(base) ? route.continue() : route.abort(),
    );
    const page = await context.newPage(),
      errors = [],
      requests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) =>
      requests.push(new URL(request.url()).pathname),
    );
    await page.goto(base + "/index.html");
    await page.locator("#email").fill("browser@example.test");
    await page.locator("#password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForSelector('[data-frontend="react"]');
    requests.length = 0;
    await page.goto(base + "/erp.html?view=customers&module=crm");
    await page.waitForSelector('[data-screen="customers-react"]');
    await page.getByText("No customers found", { exact: true }).waitFor();
    assert.ok(
      !requests.includes("/api/state") && !requests.includes("/api/hr/state"),
    );
    await page
      .getByRole("button", { name: "Add Customer", exact: true })
      .click();
    await page.locator("#cname").fill("Browser customer");
    await page.locator("#cemail").fill("client@example.test");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page
      .getByRole("cell", { name: "Browser customer", exact: true })
      .waitFor();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.locator("#cphone").fill("+92 300 1234567");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page
      .getByRole("cell", { name: "+92 300 1234567", exact: true })
      .waitFor();
    await page.getByRole("button", { name: "Details", exact: true }).click();
    await page.getByRole("heading", { name: "Customer Details" }).waitFor();
    assert.equal(await page.locator("#cname").isDisabled(), true);
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page.locator("#cust-search").fill("missing customer");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.getByText("No customers found", { exact: true }).waitFor();
    await page.locator("#cust-search").fill("Browser");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page
      .getByRole("cell", { name: "Browser customer", exact: true })
      .waitFor();
    fs.mkdirSync(path.join(cwd, "test-results"), { recursive: true });
    await page.screenshot({
      path: path.join(cwd, "test-results/customers-desktop.png"),
      fullPage: true,
    });
    await page.locator(".user-menu-trigger").click();
    await page
      .getByRole("button", { name: "Company profile", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Company profile", exact: true })
      .waitFor();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    // Additional native resources use the same compact bootstrap and real forms.
    requests.length=0;
    await page.goto(base+'/erp.html?view=vendors');
    await page.getByText('No vendors found',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Add Vendor',exact:true}).click();
    await page.locator('#vname').fill('Browser supplier');
    await page.locator('#vtrn').fill('NTN-1234567');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'Browser supplier',exact:true}).waitFor();
    await page.getByRole('button',{name:'Edit',exact:true}).click();
    await page.locator('#vphone').fill('+92 300 7654321');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'+92 300 7654321',exact:true}).waitFor();
    await page.goto(base+'/erp.html?view=products');
    await page.getByText('No products found',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Add Product',exact:true}).click();
    await page.locator('#pname').fill('Browser stock item');
    await page.locator('#psku').fill('BR-STOCK-1');
    await page.locator('#prate').fill('125.50');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'Browser stock item',exact:true}).waitFor();
    await page.goto(base+'/erp.html?view=leads');
    await page.getByText('No leads found',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Add Lead',exact:true}).click();
    await page.locator('#crm-lead-customer option').filter({hasText:'Browser customer'}).waitFor({state:'attached'});
    await page.locator('#crm-lead-customer').selectOption({label:'Browser customer'});
    assert.equal(await page.locator('#crm-lead-email').inputValue(),'client@example.test');
    await page.locator('#crm-lead-stage-input').selectOption('Quotation Required');
    await page.locator('#crm-lead-value').fill('1000');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'Quotation Required',exact:true}).waitFor();
    await page.getByRole('button',{name:'Edit',exact:true}).click();
    await page.locator('#crm-lead-source').fill('Website');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'Website',exact:true}).waitFor();
    await page.screenshot({path:path.join(cwd,'test-results/leads-desktop.png'),fullPage:true});
    await page.goto(base+'/erp.html?view=reminders');
    await page.getByText('No reminders found',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Add Reminder',exact:true}).click();
    await page.locator('#crm-reminder-lead option').filter({hasText:'Browser customer'}).waitFor({state:'attached'});
    await page.locator('#crm-reminder-lead').selectOption({label:'Browser customer'});
    await page.locator('#crm-reminder-date').fill('2020-01-01');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'Open',exact:true}).waitFor();
    await page.getByRole('button',{name:'Edit',exact:true}).click();
    await page.locator('#crm-reminder-done').selectOption('Done');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('cell',{name:'Done',exact:true}).waitFor();
    await page.goto(base+'/erp.html?view=crm-dashboard');
    await page.getByText('No follow-ups due',{exact:true}).waitFor();
    assert.ok(!requests.includes('/api/state')&&!requests.includes('/api/hr/state'));
    await require('./trade-browser.cjs')(page,base,requests);
    for (const view of [
      "sales",
      "purchase-dashboard",
      "hr-dashboard",
      "accounting",
      "manufacturing",
    ]) {
      await page.goto(base + "/erp.html?view=" + view);
      await page.waitForSelector('[data-frontend="react"]');
      assert.equal(await page.locator(".sidebar .nav-item.active").count(), 1);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + "/erp.html?view=customers");
    await page.waitForSelector('[data-screen="customers-react"]');
    await page
      .getByRole("cell", { name: "Browser customer", exact: true })
      .waitFor();
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth),
      390,
    );
    await page.screenshot({
      path: path.join(cwd, "test-results/customers-mobile.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Open modules" }).click();
    await page.locator(".sidebar.open").waitFor();
    await page.locator('[data-workspace="hr"]').click();
    await page.waitForURL("**/erp.html?view=hr-dashboard");
    await page
      .getByRole("heading", { name: "HR Dashboard", exact: true })
      .waitFor();
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify({
        browser: browser.version(),
        checks:
          "Native masters/CRM plus full native Sales/Purchasing partial fulfilment, billing, payments and print checks; compact bootstrap; Admin profile; five legacy modules in React shell; mobile navigation and width",
        pageErrors: errors,
      }),
    );
  } finally {
    await browser?.close();
    if (server?.pid && server.exitCode === null) {
      const exited = new Promise((resolve) => server.once("exit", resolve));
      server.kill();
      await exited;
    }
    fs.rmSync(temp, {
      recursive: true,
      force: true,
      maxRetries: 10,
      retryDelay: 100,
    });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
