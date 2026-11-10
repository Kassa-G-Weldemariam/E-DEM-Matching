import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { useAuth } from "../../src/auth/AuthProvider";
import { API_URL } from "../../src/config";
import { styles } from "../../src/ui/styles";

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error));

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onLogin() {
    setBusy(true);
    setError("");
    try {
      await signIn(email.trim(), password);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>E-DEM Donor</Text>
      <Text style={styles.body}>Server: {API_URL}</Text>
      <TextInput
        style={styles.input}
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable style={[styles.button, busy && styles.disabled]} disabled={busy} onPress={onLogin}>
        <Text style={styles.buttonText}>{busy ? "Logging in..." : "Log in"}</Text>
      </Pressable>
    </View>
  );
}
