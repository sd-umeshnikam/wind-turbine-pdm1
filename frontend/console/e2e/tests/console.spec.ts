import { expect, test, type Page } from "@playwright/test";

// End-to-end walk through every page of the console against the live stack. Read-only:
// alert workflow mutations are covered by the API integration tests, which roll back.

const USER = process.env.E2E_USERNAME ?? "admin";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const SHOTS = "results/screens";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Fleet overview" })).toBeVisible();
}

/** No error state, no failed request to the API, no console error. */
function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`page: ${e.message}`));
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 500) problems.push(`api ${r.status()} ${r.url()}`);
  });
  return problems;
}

async function noErrorState(page: Page) {
  await expect(page.getByText("Could not load data")).toHaveCount(0);
  await expect(page.getByText("Service temporarily unavailable")).toHaveCount(0);
}

test.beforeAll(() => {
  if (!PASSWORD) throw new Error("Set E2E_PASSWORD (and E2E_USERNAME) to run the end-to-end suite");
});

test("rejects a wrong password", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Incorrect username or password");
});

test("fleet overview shows every turbine from the API", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  const fleet = await (
    await page.request.get("/api/fleet", {
      headers: { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem("wtpdm.token"))}` },
    })
  ).json();
  await expect(page.locator("table.heatmap tbody tr")).toHaveCount(fleet.turbines.length);
  await expect(page.getByText("Turbines reporting")).toBeVisible();
  await expect(page.getByText(`${fleet.kpis.reporting} / ${fleet.kpis.turbines}`)).toBeVisible();
  await expect(page.locator(".live-dot.live")).toBeVisible();
  await noErrorState(page);
  await page.screenshot({ path: `${SHOTS}/01-fleet.png`, fullPage: true });
  expect(problems).toEqual([]);
});

test("turbine page: components, trends, expected vs actual, sensors, twin, events", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.locator("table.heatmap tbody tr th a").first().click();
  await expect(page.getByRole("tab", { name: "Components" })).toBeVisible();
  await expect(page.locator("section.card table.data").first()).toBeVisible();
  await noErrorState(page);
  await page.screenshot({ path: `${SHOTS}/02-turbine-components.png`, fullPage: true });

  await page.getByRole("tab", { name: "Health trends" }).click();
  await expect(page.getByRole("img", { name: /Health of .* over time/ })).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/03-turbine-trends.png`, fullPage: true });

  await page.getByRole("tab", { name: "Expected vs actual" }).click();
  await expect(page.getByRole("img", { name: /Measured and expected/ })).toBeVisible();
  await expect(page.getByText(/regressor (ridge_poly2|lightgbm|mlp)/)).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/04-turbine-expected.png`, fullPage: true });

  await page.getByRole("tab", { name: "Sensor explorer" }).click();
  await expect(page.getByRole("img").first()).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/05-turbine-sensors.png`, fullPage: true });

  await page.getByRole("tab", { name: "Digital twin" }).click();
  await expect(page.getByRole("img", { name: "Nacelle components coloured by health" })).toBeVisible();
  await expect(page.getByText("Active power", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-turbine-twin.png`, fullPage: true });

  await page.getByRole("tab", { name: "Labelled events" }).click();
  await expect(page.getByText("replaying now")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/07-turbine-events.png`, fullPage: true });
  await noErrorState(page);
  expect(problems).toEqual([]);
});

test("alerts work queue and detail drawer", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.getByRole("link", { name: /Alerts/ }).click();
  await expect(page.getByRole("heading", { name: "Alerts" })).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();
  const rows = page.locator("table.data tbody tr");
  await expect(rows.first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/08-alerts.png`, fullPage: true });
  await rows.first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: "Activity" })).toBeVisible();
  await expect(drawer.getByText("Turbine", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/09-alert-drawer.png` });
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await noErrorState(page);
  expect(problems).toEqual([]);
});

test("models: registry, comparison, run detail and model card", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.getByRole("link", { name: "Models" }).click();
  await expect(page.getByText("champion").first()).toBeVisible();
  await expect(page.getByRole("img", { name: "Detector comparison on event metrics" })).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/10-models.png`, fullPage: true });
  await page.getByRole("tab", { name: "Normal-behaviour models" }).click();
  await expect(page.getByText(/Nrmse Lightgbm/i)).toBeVisible();
  await page.getByRole("tab", { name: "Model card" }).click();
  await expect(page.locator(".markdown h1, .markdown h2").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/11-model-card.png`, fullPage: true });
  await noErrorState(page);
  expect(problems).toEqual([]);
});

test("drift and retraining", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.getByRole("link", { name: /Drift/ }).click();
  await expect(page.getByRole("heading", { name: "Farm A", exact: true })).toBeVisible();
  await expect(page.getByText("Scheduled retrain", { exact: true })).toBeVisible();
  await expect(page.getByText("Retrain jobs", { exact: true })).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/12-drift.png`, fullPage: true });
  await noErrorState(page);
  expect(problems).toEqual([]);
});

test("data coverage, quality, events and replay", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.getByRole("link", { name: /Data/ }).click();
  await expect(page.getByText("Planetary bearings")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/13-data-coverage.png`, fullPage: true });
  await page.getByRole("tab", { name: "Data quality" }).click();
  await expect(page.getByText("Ambient temperature").first()).toBeVisible();
  await page.getByRole("tab", { name: "Labelled events" }).click();
  await expect(page.getByText("Anomaly").first()).toBeVisible();
  await page.getByRole("tab", { name: "Replay status" }).click();
  await expect(page.getByText("replay of recorded SCADA history", { exact: true })).toBeVisible();
  await noErrorState(page);
  expect(problems).toEqual([]);
});

test("admin: users and audit log", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.getByRole("link", { name: /Users & audit/ }).click();
  await expect(page.getByRole("cell", { name: new RegExp(USER) }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByText("auth.login").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/14-audit.png`, fullPage: true });
  await noErrorState(page);
  expect(problems).toEqual([]);
});

test("dark mode renders the fleet", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await login(page);
  await expect(page.locator("table.heatmap")).toBeVisible();
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe("rgb(13, 13, 13)");
  await page.screenshot({ path: `${SHOTS}/15-fleet-dark.png`, fullPage: true });
});

test("assistant answers from live data with sources and follow-ups", async ({ page }) => {
  test.setTimeout(150_000);
  const problems = watch(page);
  await login(page);
  await expect(page.getByText("What's new")).toBeVisible();
  await page.getByRole("button", { name: "Assistant" }).click();
  const panel = page.getByRole("complementary", { name: "Maintenance assistant" });
  await expect(panel.locator(".suggestion").first()).toBeVisible();
  await panel.getByLabel("Question").fill("Which turbines need attention first?");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByLabel("Sources")).toBeVisible({ timeout: 120_000 });
  await expect(panel.locator(".markdown").first()).not.toBeEmpty();
  await expect(panel.locator(".suggestion").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/16-assistant.png` });
  expect(problems).toEqual([]);
});

test("assistant keeps the conversation when closed and starts a clean new one", async ({ page }) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  await login(page);
  await page.getByRole("button", { name: "Assistant" }).click();
  const panel = page.getByRole("complementary", { name: "Maintenance assistant" });
  const asked = panel.locator(".bubble-user");

  // Closed while answering: the question and its answer are there on reopening.
  await panel.getByLabel("Question").fill("How many open alerts are there?");
  await panel.getByLabel("Question").press("Enter");
  await expect(panel.locator(".turbine-loader")).toBeVisible();
  await panel.getByRole("button", { name: "Close assistant" }).click();
  await page.getByRole("button", { name: "Assistant" }).click();
  await expect(asked).toHaveText(["How many open alerts are there?"]);
  await expect(panel.locator(".markdown").first()).toBeVisible({ timeout: 90_000 });

  // New conversation while answering: the next question is sent, the old answer is dropped.
  await panel.getByLabel("Question").fill("What is the health of turbine A-0?");
  await panel.getByLabel("Question").press("Enter");
  await panel.getByRole("button", { name: "New conversation" }).click();
  await panel.getByLabel("Question").fill("Is there any drift?");
  await panel.getByLabel("Question").press("Enter");
  await expect(asked).toHaveText(["Is there any drift?"]);
  await expect(panel.locator(".markdown").first()).toBeVisible({ timeout: 90_000 });
  await page.waitForTimeout(15_000);
  await expect(asked).toHaveText(["Is there any drift?"]);
  expect(problems).toEqual([]);
});

test("alert drawer and turbine page show maintenance recommendations", async ({ page }) => {
  const problems = watch(page);
  await login(page);
  await page.getByRole("link", { name: /Alerts/ }).click();
  await page.locator("table.data tbody tr").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: "Recommended maintenance" })).toBeVisible();
  await expect(drawer.getByText(/Respond (within|next)/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/17-recommendation.png` });
  await page.keyboard.press("Escape");
  await page.goto("/turbines");
  await page.locator("table.data tbody tr td a").first().click();
  await expect(page.getByRole("heading", { name: "Maintenance outlook" })).toBeVisible();
  await noErrorState(page);
  expect(problems).toEqual([]);
});
