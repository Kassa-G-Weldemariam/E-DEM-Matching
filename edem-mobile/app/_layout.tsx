import * as Notifications from "expo-notifications";
import { Slot } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { isExpoGo } from "../src/push/environment";

import { AuthProvider } from "../src/auth/AuthProvider";
import { API_URL_PROBLEM } from "../src/config";
import { ConfigProblem } from "../src/ui/ConfigProblem";

// Show notifications even while the app is open (Android hides them otherwise).
// Expo Go cannot do remote push, so it is skipped there.
if (!isExpoGo) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

export default function RootLayout() {
  if (API_URL_PROBLEM) return <ConfigProblem message={API_URL_PROBLEM} />;
  return (
    <AuthProvider>
      <StatusBar style="auto" />
      <Slot />
    </AuthProvider>
  );
}
