import { describe, expect, test } from "@jest/globals";
import { readFileSync } from "node:fs";
import { join } from "node:path";

type Profile = {
  environment?: string;
  developmentClient?: boolean;
  distribution?: string;
  android?: { buildType?: string };
  env?: Record<string, string>;
};
type EasConfig = { cli?: { appVersionSource?: string }; build: Record<string, Profile> };

const eas = JSON.parse(readFileSync(join(__dirname, "../../eas.json"), "utf8")) as EasConfig;
const profiles = ["development", "preview", "production"] as const;

describe("eas.json", () => {
  test.each(profiles)("the %s profile sets APP_VARIANT to its own name", (name) => {
    expect(eas.build[name]?.env?.APP_VARIANT).toBe(name);
  });

  test("the development profile builds a development client", () => {
    expect(eas.build.development?.developmentClient).toBe(true);
  });

  test.each(["preview", "production"] as const)("the %s profile is not a development client", (name) => {
    expect(eas.build[name]?.developmentClient).not.toBe(true);
  });

  test.each(profiles)("the %s profile reads the environment variables of the same name", (name) => {
    expect(eas.build[name]?.environment).toBe(name);
  });

  const buildTypes: [string, string][] = [
    ["development", "apk"],
    ["preview", "apk"],
    ["production", "app-bundle"],
  ];
  test.each(buildTypes)("the %s profile builds: %s", (name, buildType) => {
    expect(eas.build[name]?.android?.buildType).toBe(buildType);
  });

  test("every API address set in a profile uses https", () => {
    const addresses = Object.values(eas.build)
      .map((profile) => profile.env?.EXPO_PUBLIC_API_URL)
      .filter((address): address is string => Boolean(address));
    expect(addresses.every((address) => address.startsWith("https://"))).toBe(true);
  });

  test("the app version is managed by EAS", () => {
    expect(eas.cli?.appVersionSource).toBe("remote");
  });
});
