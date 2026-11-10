// EXPO_PUBLIC_* values are copied into the app bundle when it is built, so anyone can read
// them. Never put a secret in an EXPO_PUBLIC_ variable.
export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? "").trim().replace(/\/+$/, "");

// Must match EMERGENCY_CHANNEL_ID in the backend (app/services/push.py).
export const EMERGENCY_CHANNEL_ID = "emergency_requests";

/** Returns what is wrong with the API address, or null when it is fine. */
export function checkApiUrl(url: string, isDevelopment: boolean): string | null {
  if (!url) return "EXPO_PUBLIC_API_URL is not set";
  if (!/^https?:\/\/\S+$/.test(url)) return "EXPO_PUBLIC_API_URL must start with http:// or https://";
  if (!isDevelopment && !url.startsWith("https://")) return "Release builds need an https:// API address";
  return null;
}

export const API_URL_PROBLEM = checkApiUrl(API_URL, __DEV__);
