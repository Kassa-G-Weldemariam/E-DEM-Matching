import type { ConfigContext, ExpoConfig } from "expo/config";

// Plain http is only allowed in development: preview and production builds need https.
const variant = (): string => process.env.APP_VARIANT ?? "development";

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: config.name ?? "E-DEM Donor",
  slug: config.slug ?? "edem-donor",
  android: {
    ...config.android,
    // On EAS the file comes from a "file" environment variable, so it is never committed.
    googleServicesFile: process.env.GOOGLE_SERVICES_JSON ?? "./google-services.json",
  },
  plugins: [
    ...(config.plugins ?? []),
    ["expo-build-properties", { android: { usesCleartextTraffic: variant() === "development" } }],
  ],
});
