import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { useAuth } from "../../src/auth/AuthProvider";
import { useNotificationLog } from "../../src/push/useNotificationLog";
import { STEP_LABELS, usePushRegistration, type StepKey, type StepStatus } from "../../src/push/usePushRegistration";
import { styles } from "../../src/ui/styles";

const ICONS: Record<StepStatus, string> = { todo: "·", working: "…", ok: "✓", failed: "✗" };

// Temporary home screen: the push checklist and the notification log.
// The real donor screens replace this one, and the hooks stay.
export default function HomeScreen() {
  const { user, signOut } = useAuth();
  const { steps, register } = usePushRegistration(true);
  const { lines } = useNotificationLog();
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

      {(Object.keys(STEP_LABELS) as StepKey[]).map((key) => (
        <View key={key} style={styles.step}>
          <Text style={styles.stepLabel}>
            {ICONS[steps[key].status]} {STEP_LABELS[key]}
          </Text>
          {steps[key].detail ? (
            <Text style={steps[key].status === "failed" ? styles.error : styles.detail}>{steps[key].detail}</Text>
          ) : null}
        </View>
      ))}

      <Pressable style={styles.button} onPress={() => void register()}>
        <Text style={styles.buttonText}>Register this phone again</Text>
      </Pressable>
      <Pressable style={[styles.button, styles.secondary, busy && styles.disabled]} disabled={busy} onPress={onLogout}>
        <Text style={styles.buttonText}>{busy ? "Logging out..." : "Log out"}</Text>
      </Pressable>

      <Text style={styles.subtitle}>Event log (newest first)</Text>
      {lines.length === 0 ? <Text style={styles.detail}>Nothing yet</Text> : null}
      {lines.map((line, index) => (
        <Text key={`${index}-${line}`} style={styles.logLine}>
          {line}
        </Text>
      ))}
    </ScrollView>
  );
}
