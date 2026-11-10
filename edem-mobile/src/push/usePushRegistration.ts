import * as Notifications from "expo-notifications";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";

import { api } from "../api/instance";
import { getFcmToken, requestNotificationPermission, setupNotificationChannel } from "./notifications";

export type StepKey = "channel" | "permission" | "token" | "registered";
export type StepStatus = "todo" | "working" | "ok" | "failed";
export type Steps = Record<StepKey, { status: StepStatus; detail: string }>;

export const STEP_LABELS: Record<StepKey, string> = {
  channel: "Notification channel",
  permission: "Permission",
  token: "FCM token",
  registered: "Registered with the backend",
};

const freshSteps = (): Steps => ({
  channel: { status: "todo", detail: "" },
  permission: { status: "todo", detail: "" },
  token: { status: "todo", detail: "" },
  registered: { status: "todo", detail: "" },
});

/** Registers this phone for push whenever `enabled` is true, and again if Firebase changes the token. */
export function usePushRegistration(enabled: boolean) {
  const [steps, setSteps] = useState<Steps>(freshSteps());
  const running = useRef(false);

  const register = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    const set = (key: StepKey, status: StepStatus, detail = "") =>
      setSteps((previous) => ({ ...previous, [key]: { status, detail } }));

    setSteps(freshSteps());
    let current: StepKey = "channel";
    try {
      set("channel", "working");
      await setupNotificationChannel();
      set("channel", "ok", "emergency_requests");

      current = "permission";
      set("permission", "working");
      if (!(await requestNotificationPermission())) {
        set("permission", "failed", "Denied. Allow notifications for this app in the Android settings.");
        return;
      }
      set("permission", "ok", "granted");

      current = "token";
      set("token", "working");
      const token = await getFcmToken();
      set("token", "ok", `${token.slice(0, 12)}... (${token.length} characters)`);

      current = "registered";
      set("registered", "working");
      const deviceId = await api.registerDevice(token, Platform.OS === "ios" ? "ios" : "android");
      set("registered", "ok", `device ${deviceId.slice(0, 8)}`);
    } catch (error) {
      set(current, "failed", error instanceof Error ? error.message : String(error));
    } finally {
      running.current = false;
    }
  }, []);

  useEffect(() => {
    if (enabled) void register();
  }, [enabled, register]);

  // Firebase can change a phone's token at any time. Register the new one.
  useEffect(() => {
    if (!enabled) return;
    const subscription = Notifications.addPushTokenListener(() => {
      void register();
    });
    return () => subscription.remove();
  }, [enabled, register]);

  return { steps, register };
}
