# Push notification test results

- Date: 2026-11-13
- Phone: Samsung Galaxy M14 (SM-M145F/DS)
- Android version: 15
- Build: development build, EAS, Expo SDK 58

**Result:** pass = works, or behaves the way Android documents. fail = a real risk the app has to handle.

"From Enter" includes the script start-up (and the 20 s `--delay` where noted). "From sent" starts when
Firebase accepted the message, so it is the closer measure of delivery time. All times were taken by hand
with a stopwatch, so treat them as accurate to about one second.

## Tier A: must work

| # | Scenario | Result | From Enter (s) | From sent (s) | Notes |
|---|---|---|---|---|---|
| A1 | App open | pass | 6.6 | 2.2 | |
| A2 | App in background | pass | 8.8 | 2.0 | |
| A3 | App closed | pass | 33.4 | 3.0 | includes --delay 20 |
| A4 | Screen locked | pass | 31 | 1.6 | includes --delay 20 |
| A5 | Airplane mode within limit | pass | 1:04 | 10.1 | one minute offline; 10 s after reconnecting |
| A6 | Logout cleans up | pass | n/a | n/a | no device left to send to |

## Tier B: real-world risks

| # | Scenario | Result | From Enter (s) | From sent (s) | Notes |
|---|---|---|---|---|---|
| B1 | Deep sleep (30 min) | pass | 20 | 10.0 | phone unplugged and untouched for 30 minutes; about 5 times slower than usual, still seconds |
| B2 | Battery saver | pass | 34 | 3.3 | includes --delay 20 |
| B3 | Battery: Restricted / Optimized | pass | 27.0 / 24.8 | 3.9 / 4.0 | includes --delay 20 |
| B4a | Samsung "Sleeping apps" | pass | 33.9 | 3.0 | includes --delay 20 |
| B4b | Samsung "Deep sleeping apps" | **fail** | n/a | n/a | not delivered; waited 15 min (the message lifetime was 10 min) |
| B4c | "Never auto sleeping apps" (allow list) | pass | 26.2 | 2.4 | includes --delay 20 |
| B5 | Force stop | pass | 1:40 after opening the app | n/a | not delivered while stopped; arrived after the app was opened |
| B6 | Notifications switched off | pass | n/a | n/a | backend reports SENT, phone shows nothing, as expected |
| B7 | Do Not Disturb | pass | 8 | 1.1 | delivered while Do Not Disturb was on |

## Tier C: backend lifecycle

| # | Scenario | Result | From Enter (s) | From sent (s) | Notes |
|---|---|---|---|---|---|
| C1 | Expiry | pass | n/a | n/a | --ttl 30: did not arrive |
| C2 | Uninstall cleanup | pass | n/a | n/a | dead token detected on the first send |
| C3 | Shared phone | pass | n/a | n/a | token moved to the second user |
| C4 | Burst of 3 | pass | 4.2, 7.0, 7.9 | 1.9, 2.2, 3.8 | all three arrived as separate notifications |

## Summary

In normal use (app open, background, closed, locked, battery saver, Restricted, Sleeping apps, Do Not
Disturb) a push arrived about 1 to 4 seconds after Firebase accepted it. Two situations took about 10
seconds: a phone waking after 30 minutes of deep sleep, and a phone reconnecting after airplane mode.
The only case where the push did not arrive was Samsung's "Deep sleeping apps".

## What surprised me

- Delivery was fast and steady across every normal situation. I expected the battery restrictions
  (Battery saver, Restricted) to cause more trouble than they did.
- Samsung's three lists behave very differently. "Sleeping apps" still received the push, but
  "Deep sleeping apps" blocked it completely.
- A push sent while the app was force-stopped was held and delivered after the app was opened.
- The backend found out about an uninstalled app on the very first send.

## What this means for the app

- A push is a hint, not the data. When one arrives or is tapped, the app fetches the request from the API,
  because the request may already be fulfilled or cancelled by then.
- The app never relies on push alone: the request list screen shows open requests too.
- The app checks the notification permission and channel on every start and shows a warning when they are
  off. The backend cannot see this, because it reports SENT either way.
- Donor onboarding asks the donor to allow background activity: battery not Restricted, and the app not in
  "Sleeping apps" or "Deep sleeping apps". It also explains Do Not Disturb.
- Donors in "Deep sleeping apps" cannot be reached by push. An SMS fallback, now out of scope, is the
  answer to consider in a later phase.
- The 10-minute message lifetime is right: an old emergency request is not delivered late.
- Dead tokens clean themselves up, so no scheduled cleanup is needed for now.

## Limitations of these measurements

- One phone, one brand, one Android version. Other brands have different battery rules.
- Delivery time varies from one send to the next, so a result cannot be repeated exactly.
- Times were taken by hand with a stopwatch, which is easy to get wrong by a fraction of a second, so two
  decimals suggest more precision than there is. Read the figures as ranges.

## Not tested

- Whether a push held for an app in "Deep sleeping apps" is delivered later, or lost (the test used the
  default 10-minute message lifetime).
- A phone left unused for several days, which is when Samsung moves apps to "Sleeping apps" by itself.
- A second phone brand.