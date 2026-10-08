import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, tokenStore } from "./api";

afterEach(() => { vi.restoreAllMocks(); tokenStore.clear(); });

describe("api client", () => {
  it("sends the bearer token and parses JSON", async () => {
    tokenStore.set("abc");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));
    await expect(api.circles()).resolves.toEqual([]);
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/v1\/circles$/);
    expect((init!.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });
  it("maps the error envelope to ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "not_found", message: "Circle not found" } }), { status: 404 }),
    );
    const err = await api.circle("x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("Circle not found");
  });
  it("reports network failures clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fail"));
    const err = await api.health().catch((e) => e);
    expect(err.code).toBe("network");
  });
});
