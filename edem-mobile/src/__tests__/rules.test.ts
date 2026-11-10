import { describe, expect, test } from "@jest/globals";

import { ensureDonor, NotADonorError } from "../auth/rules";

describe("ensureDonor", () => {
  test("a donor is accepted", () => {
    expect(() => ensureDonor({ role: "donor" })).not.toThrow();
  });

  test.each(["hospital", "blood_bank", "admin"])("a %s is refused", (role) => {
    expect(() => ensureDonor({ role })).toThrow(NotADonorError);
  });

  test("an unknown role is refused", () => {
    expect(() => ensureDonor({ role: "superuser" })).toThrow(NotADonorError);
  });

  test("the message says where non-donors should go", () => {
    expect(() => ensureDonor({ role: "hospital" })).toThrow("website");
  });
});
