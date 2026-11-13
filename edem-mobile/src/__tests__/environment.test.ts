import { describe, expect, test } from "@jest/globals";
import { ExecutionEnvironment } from "expo-constants";

import { isExpoGoEnvironment } from "../push/environment";

describe("isExpoGoEnvironment", () => {
  test("Expo Go is recognised", () => {
    expect(isExpoGoEnvironment(ExecutionEnvironment.StoreClient)).toBe(true);
  });

  test.each([ExecutionEnvironment.Standalone, ExecutionEnvironment.Bare])("%s is not Expo Go", (environment) => {
    expect(isExpoGoEnvironment(environment)).toBe(false);
  });

  test.each([undefined, null])("%p is not Expo Go", (environment) => {
    expect(isExpoGoEnvironment(environment)).toBe(false);
  });
});
