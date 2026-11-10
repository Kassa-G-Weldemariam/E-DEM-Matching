import { StyleSheet } from "react-native";

export const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  screen: { flexGrow: 1, padding: 24, paddingTop: 64, gap: 10, backgroundColor: "#fff" },
  title: { fontSize: 22, fontWeight: "700" },
  subtitle: { fontSize: 16, fontWeight: "600", marginTop: 16 },
  body: { fontSize: 14, color: "#333" },
  input: { borderWidth: 1, borderColor: "#bbb", borderRadius: 8, padding: 10, fontSize: 16 },
  button: { backgroundColor: "#b3261e", borderRadius: 8, padding: 12, alignItems: "center" },
  secondary: { backgroundColor: "#555" },
  disabled: { opacity: 0.6 },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  step: { paddingVertical: 4 },
  stepLabel: { fontSize: 15, fontWeight: "600" },
  detail: { fontSize: 13, color: "#555" },
  error: { fontSize: 13, color: "#b3261e" },
  logLine: { fontSize: 12, color: "#222", fontFamily: "monospace" },
});
