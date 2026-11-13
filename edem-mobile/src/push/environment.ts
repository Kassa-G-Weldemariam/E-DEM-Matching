import Constants, { ExecutionEnvironment } from "expo-constants";

/** Expo Go cannot do remote push notifications (removed in SDK 53). A development build can. */
export function isExpoGoEnvironment(environment: ExecutionEnvironment | null | undefined): boolean {
  return environment === ExecutionEnvironment.StoreClient;
}

export const isExpoGo = isExpoGoEnvironment(Constants.executionEnvironment);
