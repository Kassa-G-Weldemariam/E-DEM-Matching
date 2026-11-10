import { ActivityIndicator, View } from "react-native";

import { styles } from "./styles";

export function LoadingScreen() {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" />
    </View>
  );
}
