import { describe, expect, test } from "@jest/globals";

import { checkApiUrl } from "../config";

describe("checkApiUrl", () => {
  test("an empty address is a problem", () => {
    expect(checkApiUrl("", true)).toContain("not set");
  });

  test("an address without http or https is a problem", () => {
    expect(checkApiUrl("192.168.1.20:8000/v1", true)).toContain("must start with");
  });

  test("an address with a space is a problem", () => {
    expect(checkApiUrl("http://192.168.1.20:8000 /v1", true)).toContain("must start with");
  });

  test("plain http is fine while developing", () => {
    expect(checkApiUrl("http://192.168.1.20:8000/v1", true)).toBeNull();
  });

  test("plain http is refused in a release build", () => {
    expect(checkApiUrl("http://192.168.1.20:8000/v1", false)).toContain("https");
  });

  test.each([true, false])("https is always fine (development: %s)", (isDevelopment) => {
    expect(checkApiUrl("https://api.example.org/v1", isDevelopment)).toBeNull();
  });
});
