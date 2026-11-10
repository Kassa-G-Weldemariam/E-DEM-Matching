import { describe, expect, test } from "@jest/globals";

import { ApiClient, ApiError, type Session, type SessionStore, type User } from "../api/client";

class MemoryStore implements SessionStore {
  session: Session | null;
  constructor(session: Session | null = null) {
    this.session = session;
  }
  async load() {
    return this.session;
  }
  async save(session: Session) {
    this.session = session;
  }
  async clear() {
    this.session = null;
  }
}

type Reply = { status: number; body?: unknown } | Error;
type Call = { url: string; init?: RequestInit };

/** A stand-in for fetch. The replies are handed out in the order the requests arrive. */
function fakeFetch(replies: Reply[]) {
  const calls: Call[] = [];
  const impl = async (url: string, init?: RequestInit): Promise<Response> => {
    calls.push({ url, init });
    const reply = replies.shift();
    if (!reply) throw new Error(`unexpected request: ${url}`);
    if (reply instanceof Error) throw reply;
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: async () => {
        if (reply.body === undefined) throw new Error("the body is not JSON");
        return reply.body;
      },
    } as unknown as Response;
  };
  return { impl, calls };
}

const donor: User = { id: "1", email: "d@x.org", role: "donor", is_active: true };
const ok = (data: unknown): Reply => ({ status: 200, body: { success: true, data } });
const fail = (status: number, code: string, message: string): Reply => ({
  status,
  body: { success: false, error: { code, message } },
});
const expired = (): Reply => fail(401, "UNAUTHORIZED", "Token has expired");
const session = (changes: Partial<Session> = {}): Session => ({
  accessToken: "access-1",
  refreshToken: "refresh-1",
  deviceId: null,
  user: donor,
  ...changes,
});
const header = (call: Call, name: string) => (call.init?.headers as Record<string, string>)[name];
const bodyOf = (call: Call) => JSON.parse(call.init?.body as string);
const refreshCalls = (calls: Call[]) => calls.filter((call) => call.url.endsWith("/auth/refresh"));
const loginReply = (user: User = donor): Reply => ok({ access_token: "a", refresh_token: "r", user });

describe("login", () => {
  test("stores the tokens and the user, and returns the user", async () => {
    const store = new MemoryStore();
    const { impl, calls } = fakeFetch([loginReply()]);
    const user = await new ApiClient("http://api/v1", store, impl).login("d@x.org", "pw");
    expect(user.email).toBe("d@x.org");
    expect(store.session).toEqual({ accessToken: "a", refreshToken: "r", deviceId: null, user: donor });
    expect(calls[0].url).toBe("http://api/v1/auth/login");
    expect(bodyOf(calls[0])).toEqual({ email: "d@x.org", password: "pw" });
  });

  test("a wrong password gives the server's message and stores nothing", async () => {
    const store = new MemoryStore();
    const { impl } = fakeFetch([fail(401, "UNAUTHORIZED", "Invalid email or password")]);
    const attempt = new ApiClient("http://api/v1", store, impl).login("d@x.org", "bad");
    await expect(attempt).rejects.toMatchObject({
      status: 401,
      code: "UNAUTHORIZED",
      message: "Invalid email or password",
    });
    expect(store.session).toBeNull();
  });

  test("a new login forgets the device of the previous login", async () => {
    const store = new MemoryStore(session({ deviceId: "old-device" }));
    const { impl } = fakeFetch([loginReply()]);
    await new ApiClient("http://api/v1", store, impl).login("d@x.org", "pw");
    expect(store.session?.deviceId).toBeNull();
  });

  test("trailing slashes in the base URL are ignored", async () => {
    const { impl, calls } = fakeFetch([fail(401, "UNAUTHORIZED", "no")]);
    await new ApiClient("http://api/v1///", new MemoryStore(), impl).login("a@x.org", "p").catch(() => undefined);
    expect(calls[0].url).toBe("http://api/v1/auth/login");
  });

  test("a failed validation stores nothing", async () => {
    const store = new MemoryStore();
    const { impl } = fakeFetch([loginReply({ ...donor, role: "hospital" })]);
    const attempt = new ApiClient("http://api/v1", store, impl).login("h@x.org", "pw", () => {
      throw new Error("not allowed");
    });
    await expect(attempt).rejects.toThrow("not allowed");
    expect(store.session).toBeNull();
  });

  test("the validator receives the user, and a passing one lets the login finish", async () => {
    const store = new MemoryStore();
    const { impl } = fakeFetch([loginReply()]);
    const seen: string[] = [];
    await new ApiClient("http://api/v1", store, impl).login("d@x.org", "pw", (user) => {
      seen.push(user.role);
    });
    expect(seen).toEqual(["donor"]);
    expect(store.session).not.toBeNull();
  });
});

describe("authenticated requests", () => {
  test("send the access token as a bearer token", async () => {
    const { impl, calls } = fakeFetch([ok(donor)]);
    await new ApiClient("http://api/v1", new MemoryStore(session()), impl).me();
    expect(header(calls[0], "Authorization")).toBe("Bearer access-1");
  });

  test("without a session they fail at once, without calling the server", async () => {
    const { impl, calls } = fakeFetch([]);
    await expect(new ApiClient("http://api/v1", new MemoryStore(), impl).me()).rejects.toMatchObject({ status: 401 });
    expect(calls).toHaveLength(0);
  });

  test("an expired access token is refreshed once and the request is retried", async () => {
    const store = new MemoryStore(session());
    const { impl, calls } = fakeFetch([expired(), ok({ access_token: "access-2" }), ok({ value: 1 })]);
    const result = await new ApiClient("http://api/v1", store, impl).request("/anything");
    expect(result).toEqual({ value: 1 });
    expect(store.session?.accessToken).toBe("access-2");
    expect(calls[1].url).toBe("http://api/v1/auth/refresh");
    expect(bodyOf(calls[1])).toEqual({ refresh_token: "refresh-1" });
    expect(header(calls[2], "Authorization")).toBe("Bearer access-2");
  });

  test("a rejected refresh token ends the session and tells the app", async () => {
    const store = new MemoryStore(session());
    const { impl } = fakeFetch([expired(), expired()]);
    const client = new ApiClient("http://api/v1", store, impl);
    let ended = 0;
    client.onSessionEnded(() => {
      ended += 1;
    });
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    expect(store.session).toBeNull();
    expect(ended).toBe(1);
  });

  test("a network failure during the refresh keeps the session and stays quiet", async () => {
    const store = new MemoryStore(session());
    const { impl } = fakeFetch([expired(), new Error("offline")]);
    const client = new ApiClient("http://api/v1", store, impl);
    let ended = 0;
    client.onSessionEnded(() => {
      ended += 1;
    });
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    expect(store.session).not.toBeNull();
    expect(ended).toBe(0);
  });

  test("several requests that expire together share one refresh", async () => {
    const store = new MemoryStore(session());
    const { impl, calls } = fakeFetch([
      expired(),
      expired(),
      ok({ access_token: "access-2" }),
      ok({ done: true }),
      ok({ done: true }),
    ]);
    const client = new ApiClient("http://api/v1", store, impl);
    const results = await Promise.all([client.request("/a"), client.request("/b")]);
    expect(results).toEqual([{ done: true }, { done: true }]);
    expect(refreshCalls(calls)).toHaveLength(1);
  });

  test("no network gives a clear error with status 0", async () => {
    const { impl } = fakeFetch([new Error("offline")]);
    const attempt = new ApiClient("http://api/v1", new MemoryStore(session()), impl).me();
    await expect(attempt).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    await expect(attempt).rejects.toBeInstanceOf(ApiError);
  });

  test("a request that never answers fails after the time limit", async () => {
    const neverAnswers = (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
      });
    const client = new ApiClient("http://api/v1", new MemoryStore(session()), neverAnswers, { timeoutMs: 20 });
    await expect(client.me()).rejects.toMatchObject({
      status: 0,
      code: "NETWORK_ERROR",
      message: expect.stringContaining("too long"),
    });
  });

  test("an error page that is not JSON still gives a readable error", async () => {
    const { impl } = fakeFetch([{ status: 502 }]);
    const attempt = new ApiClient("http://api/v1", new MemoryStore(session()), impl).me();
    await expect(attempt).rejects.toMatchObject({ status: 502, code: "HTTP_ERROR" });
    await expect(attempt).rejects.toThrow("502");
  });

  test("refreshUser keeps the cached user up to date", async () => {
    const store = new MemoryStore(session());
    const updated = { ...donor, email: "new@x.org" };
    const { impl } = fakeFetch([ok(updated)]);
    expect(await new ApiClient("http://api/v1", store, impl).refreshUser()).toEqual(updated);
    expect(store.session?.user).toEqual(updated);
  });

  test("a deactivated account is reported as 403", async () => {
    const { impl } = fakeFetch([fail(403, "FORBIDDEN", "This account has been deactivated")]);
    const attempt = new ApiClient("http://api/v1", new MemoryStore(session()), impl).me();
    await expect(attempt).rejects.toMatchObject({ status: 403, code: "FORBIDDEN" });
  });
});

describe("devices", () => {
  test("registering sends the token and platform, and remembers the device id", async () => {
    const store = new MemoryStore(session());
    const { impl, calls } = fakeFetch([ok({ id: "dev-1" })]);
    const id = await new ApiClient("http://api/v1", store, impl).registerDevice("fcm-token", "android");
    expect(id).toBe("dev-1");
    expect(calls[0].url).toBe("http://api/v1/devices");
    expect(bodyOf(calls[0])).toEqual({ token: "fcm-token", platform: "android" });
    expect(store.session?.deviceId).toBe("dev-1");
  });

  test("removing deletes the device on the server", async () => {
    const { impl, calls } = fakeFetch([ok(null)]);
    await new ApiClient("http://api/v1", new MemoryStore(session({ deviceId: "dev-1" })), impl).removeDevice();
    expect(calls[0].url).toBe("http://api/v1/devices/dev-1");
    expect(calls[0].init?.method).toBe("DELETE");
  });

  test("a device the server no longer knows is not an error", async () => {
    const { impl } = fakeFetch([fail(404, "NOT_FOUND", "Device not found")]);
    const client = new ApiClient("http://api/v1", new MemoryStore(session({ deviceId: "dev-1" })), impl);
    await expect(client.removeDevice()).resolves.toBeUndefined();
  });

  test("without a device id nothing is sent", async () => {
    const { impl, calls } = fakeFetch([]);
    await new ApiClient("http://api/v1", new MemoryStore(session()), impl).removeDevice();
    expect(calls).toHaveLength(0);
  });
});

describe("logout", () => {
  test("removes the device first, then forgets the login", async () => {
    const store = new MemoryStore(session({ deviceId: "dev-1" }));
    const { impl, calls } = fakeFetch([ok(null)]);
    await new ApiClient("http://api/v1", store, impl).logout();
    expect(calls[0].url).toBe("http://api/v1/devices/dev-1");
    expect(store.session).toBeNull();
  });

  test("forgets the login even when removing the device fails", async () => {
    const store = new MemoryStore(session({ deviceId: "dev-1" }));
    const { impl } = fakeFetch([new Error("offline")]);
    await new ApiClient("http://api/v1", store, impl).logout();
    expect(store.session).toBeNull();
  });
});
