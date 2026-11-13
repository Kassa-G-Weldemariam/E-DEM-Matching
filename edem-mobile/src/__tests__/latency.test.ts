import { describe, expect, test } from "@jest/globals";

import { latencyText } from "../push/latency";

const SENT = "2026-11-20T10:00:00.000+00:00";
const after = (seconds: number) => Date.parse(SENT) + seconds * 1000;

describe("latencyText", () => {
  test("shows how long a notification took", () => {
    expect(latencyText({ sent_at: SENT }, after(1.5))).toBe(" (arrived 1.5 s after it was sent)");
  });

  test("rounds to one decimal place", () => {
    expect(latencyText({ sent_at: SENT }, after(2.04))).toBe(" (arrived 2.0 s after it was sent)");
  });

  test.each([undefined, null, "text", 42, {}, { sent_at: 42 }, { sent_at: "not a date" }])(
    "gives no text for %p",
    (data) => {
      expect(latencyText(data, after(1))).toBe("");
    },
  );

  test("a tiny negative difference counts as zero", () => {
    expect(latencyText({ sent_at: SENT }, after(-2))).toBe(" (arrived 0.0 s after it was sent)");
  });

  test("a large negative difference warns about the clocks", () => {
    expect(latencyText({ sent_at: SENT }, after(-30))).toContain("clock");
  });
});
