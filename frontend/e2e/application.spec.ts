import { test, expect } from "@playwright/test";

const base = process.env.SECOND_BRAIN_E2E_URL;
test.skip(!base, "Start synthetic backend and supply SECOND_BRAIN_E2E_URL.");

test("desktop-shared UI loads, sends, switches and deletes conversations", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(base!);
  await expect(page.getByRole("button", { name: "Nueva conversación" })).toBeEnabled();
  await page.getByRole("textbox", { name: "Mensaje" }).fill("Hola desde una prueba sintética");
  await page.getByRole("button", { name: "Enviar", exact: true }).click();
  await expect(page.locator(".message.assistant")).toContainText("Respuesta local.");
  await page.getByRole("button", { name: "Nueva conversación" }).click();
  await expect(page.locator(".welcome")).toBeVisible();
  await page.getByRole("button", { name: "Hola desde una prueba sintética", exact: true }).click();
  await expect(page.locator(".message.assistant")).toContainText("Respuesta local.");
  page.on("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Borrar Hola desde una prueba sintética" }).click();
  await expect(page.locator(".welcome")).toBeVisible();
  await page.getByRole("button", { name: "Memoria" }).click();
  await expect(page.getByRole("heading", { name: "Tu memoria" })).toBeVisible();
  expect(errors).toEqual([]);
});
