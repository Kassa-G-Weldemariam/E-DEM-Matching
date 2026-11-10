import { Redirect, Stack } from "expo-router";

import { useAuth } from "../../src/auth/AuthProvider";
import { LoadingScreen } from "../../src/ui/LoadingScreen";

export default function AuthLayout() {
  const { status } = useAuth();
  if (status === "loading") return <LoadingScreen />;
  if (status === "signedIn") return <Redirect href="/" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
