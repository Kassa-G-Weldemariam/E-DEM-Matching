import * as Notifications from "expo-notifications";
import { Slot } from "expo-router";
import { StatusBar } from "expo-status-bar";

import { AuthProvider } from "../src/auth/AuthProvider";
import { API_URL_PROBLEM } from "../src/config";
import { ConfigProblem } from "../src/ui/ConfigProblem";

// Show notifications even while the app is open (Android hides them otherwise).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export default function RootLayout() {
  if (API_URL_PROBLEM) return <ConfigProblem message={API_URL_PROBLEM} />;
  return (
    <AuthProvider>
      <StatusBar style="auto" />
      <Slot />
    </AuthProvider>
  );
}
