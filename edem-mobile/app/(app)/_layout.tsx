import { Redirect, Stack } from "expo-router";

import { useAuth } from "../../src/auth/AuthProvider";
import { LoadingScreen } from "../../src/ui/LoadingScreen";

export default function AppLayout() {
  const { status } = useAuth();
  if (status === "loading") return <LoadingScreen />;
  if (status === "signedOut") return <Redirect href="/login" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
