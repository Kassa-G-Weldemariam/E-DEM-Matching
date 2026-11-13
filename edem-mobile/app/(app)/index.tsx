import { useState } from "react";
import { Pressable, ScrollView, Text } from "react-native";

import { useAuth } from "../../src/auth/AuthProvider";
import { isExpoGo } from "../../src/push/environment";
import { PushPanel } from "../../src/push/PushPanel";
import { styles } from "../../src/ui/styles";

// Temporary home screen. The real donor screens replace this one, and PushPanel's hooks stay.
export default function HomeScreen() {
  const { user, signOut } = useAuth();
  const [busy, setBusy] = useState(false);

  async function onLogout() {
    setBusy(true);
    await signOut();
  }

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Logged in</Text>
      <Text style={styles.body}>
        {user?.email} ({user?.role})
      </Text>

      {isExpoGo ? (
        <>
          <Text style={styles.subtitle}>Push notifications are off</Text>
          <Text style={styles.body}>
            You are running inside Expo Go. Expo removed push notifications from Expo Go in SDK 53. Close Expo Go and
            open the E-DEM Donor development build on this phone instead.
          </Text>
        </>
      ) : (
        <PushPanel />
      )}

      <Pressable style={[styles.button, styles.secondary, busy && styles.disabled]} disabled={busy} onPress={onLogout}>
        <Text style={styles.buttonText}>{busy ? "Logging out..." : "Log out"}</Text>
      </Pressable>
    </ScrollView>
  );
}
