/* eslint-disable import/namespace */
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { EMERGENCY_CHANNEL_ID } from "../config";

/** Android 13+ shows the permission prompt only AFTER a channel exists, so this comes first. */
export async function setupNotificationChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync(EMERGENCY_CHANNEL_ID, {
    name: "Emergency blood requests",
    importance: Notifications.AndroidImportance.MAX,
    vibrationPattern: [0, 400, 200, 400],
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    enableVibrate: true,
  });
}

export async function requestNotificationPermission(): Promise<boolean> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  const asked = await Notifications.requestPermissionsAsync();
  return asked.granted;
}

/** The phone's native FCM token: this is what the backend sends to through Firebase. */
export async function getFcmToken(): Promise<string> {
  if (!Device.isDevice) throw new Error("Push notifications need a real phone, not an emulator");
  const token = await Notifications.getDevicePushTokenAsync();
  if (typeof token.data !== "string" || token.data.length < 20) {
    throw new Error("The phone returned an unexpected token format");
  }
  return token.data;
}
