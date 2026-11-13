import { Pressable, Text, View } from "react-native";

import { styles } from "../ui/styles";
import { useNotificationLog } from "./useNotificationLog";
import { STEP_LABELS, usePushRegistration, type StepKey, type StepStatus } from "./usePushRegistration";

const ICONS: Record<StepStatus, string> = { todo: "·", working: "…", ok: "✓", failed: "✗" };

/** The push checklist and the notification log. Only mount it in a build that supports push. */
export function PushPanel() {
  const { steps, register } = usePushRegistration(true);
  const { lines } = useNotificationLog();

  return (
    <View style={styles.panel}>
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

      <Text style={styles.subtitle}>Event log (newest first)</Text>
      {lines.length === 0 ? <Text style={styles.detail}>Nothing yet</Text> : null}
      {lines.map((line, index) => (
        <Text key={`${index}-${line}`} style={styles.logLine}>
          {line}
        </Text>
      ))}
    </View>
  );
}
