import { latencyText } from "./latency";
import * as Notifications from "expo-notifications";
import { useCallback, useEffect, useRef, useState } from "react";

const describeNotification = (notification: Notifications.Notification): string => {
  const { title, body, data } = notification.request.content;
  return `${title ?? "(no title)"} | ${body ?? ""} | ${JSON.stringify(data ?? {})}`;
};

/** A live log of notifications. */
export function useNotificationLog(limit = 30) {
  const [lines, setLines] = useState<string[]>([]);

  const add = useCallback(
    (text: string) => {
      const time = new Date().toLocaleTimeString();
      setLines((previous) => [`${time}  ${text}`, ...previous].slice(0, limit));
    },
    [limit],
  );

  useEffect(() => {
    const subscription = Notifications.addNotificationReceivedListener((notification) =>
      add(
        `RECEIVED (app open): ${describeNotification(notification)}${latencyText(notification.request.content.data)}`,
      ),
    );
    return () => subscription.remove();
  }, [add]);

  // Covers a tap while the app runs AND the notification that started the app from closed.
  const lastResponse = Notifications.useLastNotificationResponse();
  const logged = useRef<string | null>(null);
  useEffect(() => {
    if (!lastResponse) return;
    const key = `${lastResponse.notification.request.identifier}:${lastResponse.actionIdentifier}`;
    if (logged.current === key) return;
    logged.current = key;
    add(`OPENED FROM A NOTIFICATION: ${describeNotification(lastResponse.notification)}`);
  }, [lastResponse, add]);

  const clear = useCallback(() => setLines([]), []);
  return { lines, clear };
}
