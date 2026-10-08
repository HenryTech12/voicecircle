import { describe, expect, it } from "vitest";
import { duration, initials, toE164, OUTCOME } from "./format";

describe("format helpers", () => {
  it("builds E.164 numbers from local input", () => {
    expect(toE164("+234", "0803 123 4567")).toBe("+2348031234567");
    expect(toE164("+1", "(415) 555-0100")).toBe("+14155550100");
    expect(toE164("+234", "")).toBe("");
  });
  it("formats durations and initials", () => {
    expect(duration(75)).toBe("1 min 15 s");
    expect(duration(9)).toBe("9 s");
    expect(initials("Grandma Ada")).toBe("GA");
  });
  it("has wording for every outcome", () => {
    for (const k of ["hung_up_early", "verified", "refused", "hesitated", "complied"] as const) {
      expect(OUTCOME[k].sentence("Ada")).toContain("Ada");
    }
  });
});
