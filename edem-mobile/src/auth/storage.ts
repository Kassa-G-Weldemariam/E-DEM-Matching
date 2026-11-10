import * as SecureStore from "expo-secure-store";

import type { Session, SessionStore } from "../api/client";

const KEY = "edem_session";

// Encrypted storage (Android Keystore). Tokens must never go in plain AsyncStorage.
export const secureStore: SessionStore = {
  async load() {
    const raw = await SecureStore.getItemAsync(KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as Session;
    } catch {
      return null;
    }
  },
  async save(session) {
    await SecureStore.setItemAsync(KEY, JSON.stringify(session));
  },
  async clear() {
    await SecureStore.deleteItemAsync(KEY);
  },
};
