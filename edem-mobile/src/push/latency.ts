/** How long a notification took, from the send time the test script puts in its data. */
export function latencyText(data: unknown, now: number = Date.now()): string {
  if (typeof data !== "object" || data === null) return "";
  const sentAt = (data as Record<string, unknown>).sent_at;
  if (typeof sentAt !== "string") return "";
  const sent = Date.parse(sentAt);
  if (Number.isNaN(sent)) return "";

  const seconds = (now - sent) / 1000;
  if (seconds < -5) return " (the phone's clock and the computer's clock differ by more than 5 s)";
  return ` (arrived ${Math.max(0, seconds).toFixed(1)} s after it was sent)`;
}
