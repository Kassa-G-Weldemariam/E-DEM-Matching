import { Text, View } from "react-native";

import { styles } from "./styles";

export function ConfigProblem({ message }: { message: string }) {
  return (
    <View style={styles.center}>
      <Text style={styles.title}>App configuration problem</Text>
      <Text style={styles.body}>{message}</Text>
      <Text style={styles.body}>
        Set it in edem-mobile/.env, then restart Metro with &quot;npx expo start --dev-client --clear&quot;.
      </Text>
    </View>
  );
}
