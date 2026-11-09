// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

afterEach(cleanup);

describe("composer", () => {
  it("submits non-empty text once and clears input", async () => {
    const send = vi.fn(async () => {});
    render(<Composer busy={false} voiceReady={false} send={send} stop={() => {}} report={() => {}} />);
    const field = screen.getByRole("textbox", { name: "Mensaje" });
    fireEvent.change(field, { target: { value: "  Comprar pan  " } });
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() => expect(send).toHaveBeenCalledWith("Comprar pan", false));
    expect((field as HTMLTextAreaElement).value).toBe("");
  });
  it("stops instead of resubmitting while busy", () => {
    const send = vi.fn(async () => {}), stop = vi.fn();
    render(<Composer busy voiceReady={false} send={send} stop={stop} report={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Detener" }));
    expect(stop).toHaveBeenCalledOnce();
    expect(send).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Micrófono" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
