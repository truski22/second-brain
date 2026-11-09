// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import * as client from "../api/client";
import { dateGroup, Integrations, Tasks } from "./Panels";

describe("calendar grouping", () => {
  it("uses backend date, including month rollover", () => {
    expect(dateGroup("2026-10-01", "2026-09-30")).toBe("Mañana");
    expect(dateGroup("2026-09-28", "2026-09-29")).toBe("Atrasadas");
    expect(dateGroup(null, "2026-09-29")).toBe("Sin fecha");
  });
  it("offers explicit completion with task identity", () => {
    render(<Tasks tasks={[{ id: "1", task: "Comprar pan", due_date: "2026-09-30" }]}
      today="2026-09-29" refresh={async () => {}} report={() => {}} />);
    expect(screen.getByRole("button", { name: "Completar: Comprar pan" })).toBeDefined();
    expect(screen.getByText("Mañana")).toBeDefined();
  });
});

describe("integrations", () => {
  it("renders the connection form declared by the backend", async () => {
    vi.spyOn(client, "api").mockResolvedValue([{ id: "gitlab", name: "GitLab", connected: false, url: "",
      account: "", access: "read", fields: [
        { name: "url", label: "URL de GitLab", secret: false, placeholder: "https://gitlab.com" },
        { name: "token", label: "Token personal", secret: true, placeholder: "" }] }]);
    render(<Integrations report={() => {}} />);
    expect(await screen.findByRole("button", { name: "Conectar GitLab" })).toBeDefined();
    expect((screen.getByLabelText("Token personal") as HTMLInputElement).type).toBe("password");
  });
});
