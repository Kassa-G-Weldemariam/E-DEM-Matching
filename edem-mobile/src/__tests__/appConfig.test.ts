import { afterEach, describe, expect, test } from "@jest/globals";
import type { ConfigContext, ExpoConfig } from "expo/config";

import buildConfig from "../../app.config";

const base = {
  name: "E-DEM Donor",
  slug: "edem-donor",
  scheme: "edem",
  android: { package: "com.edem.matching" },
  plugins: ["expo-router", "expo-notifications"],
};
const build = (): ExpoConfig => buildConfig({ config: base } as unknown as ConfigContext);

function setEnv(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}

const original = { APP_VARIANT: process.env.APP_VARIANT, GOOGLE_SERVICES_JSON: process.env.GOOGLE_SERVICES_JSON };

afterEach(() => {
  setEnv("APP_VARIANT", original.APP_VARIANT);
  setEnv("GOOGLE_SERVICES_JSON", original.GOOGLE_SERVICES_JSON);
});

function buildProperties(config: ExpoConfig): unknown[] {
  return ((config.plugins ?? []) as unknown[]).filter(
    (plugin) => Array.isArray(plugin) && plugin[0] === "expo-build-properties",
  );
}

function allowsCleartext(config: ExpoConfig): boolean {
  const [entry] = buildProperties(config) as [string, { android: { usesCleartextTraffic: boolean } }][];
  return entry[1].android.usesCleartextTraffic;
}

describe("app config", () => {
  const cases: [string | undefined, boolean][] = [
    [undefined, true],
    ["development", true],
    ["preview", false],
    ["production", false],
  ];
  test.each(cases)("plain http traffic for APP_VARIANT=%s is allowed: %s", (variant, expected) => {
    setEnv("APP_VARIANT", variant);
    expect(allowsCleartext(build())).toBe(expected);
  });

  test("the Firebase file defaults to the local one", () => {
    setEnv("GOOGLE_SERVICES_JSON", undefined);
    expect(build().android?.googleServicesFile).toBe("./google-services.json");
  });

  test("the Firebase file comes from the environment when it is set (EAS)", () => {
    setEnv("GOOGLE_SERVICES_JSON", "/tmp/eas/google-services.json");
    expect(build().android?.googleServicesFile).toBe("/tmp/eas/google-services.json");
  });

  test("the package name from app.json is kept", () => {
    expect(build().android?.package).toBe("com.edem.matching");
  });

  test("the existing plugins are kept and build properties are added exactly once", () => {
    const plugins = build().plugins as unknown[];
    expect(plugins).toContain("expo-router");
    expect(plugins).toContain("expo-notifications");
    expect(buildProperties(build())).toHaveLength(1);
  });
});
