// Talks to the E-DEM backend. It has no React or Expo code, so it can be tested on its own.

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export type User = { id: string; email: string; role: string; is_active: boolean };

export type Session = {
  accessToken: string;
  refreshToken: string;
  deviceId: string | null;
  user: User | null; // cached, so the app can open without a network
};

export interface SessionStore {
  load(): Promise<Session | null>;
  save(session: Session): Promise<void>;
  clear(): Promise<void>;
}

type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;
type Envelope = { data?: unknown; error?: { code?: string; message?: string } };
type ClientOptions = { timeoutMs?: number };

export const DEFAULT_TIMEOUT_MS = 15_000;

export class ApiClient {
  private baseUrl: string;
  private store: SessionStore;
  private fetchImpl: FetchLike;
  private timeoutMs: number;
  private refreshInFlight: Promise<boolean> | null = null;
  private endListeners = new Set<() => void>();

  constructor(
    baseUrl: string,
    store: SessionStore,
    fetchImpl: FetchLike = (url, init) => fetch(url, init),
    options: ClientOptions = {},
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.store = store;
    this.fetchImpl = fetchImpl;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** Called when the server rejects the refresh token and the login is gone. Returns an unsubscribe function. */
  onSessionEnded(listener: () => void): () => void {
    this.endListeners.add(listener);
    return () => {
      this.endListeners.delete(listener);
    };
  }

  private async send(path: string, init: RequestInit = {}, accessToken?: string): Promise<Response> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers, signal: controller.signal });
    } catch {
      throw new ApiError(
        0,
        "NETWORK_ERROR",
        controller.signal.aborted
          ? "The server took too long to answer. Try again."
          : "Cannot reach the server. Check the connection and the API address.",
      );
    } finally {
      clearTimeout(timer);
    }
  }

  private async parse<T>(response: Response): Promise<T> {
    let body: Envelope | null = null;
    try {
      body = (await response.json()) as Envelope;
    } catch {
      body = null; // for example an HTML error page from a proxy
    }
    if (response.ok) return (body?.data ?? null) as T;
    throw new ApiError(
      response.status,
      body?.error?.code ?? "HTTP_ERROR",
      body?.error?.message ?? `Request failed (${response.status})`,
    );
  }

  /** Several requests can fail with 401 at once: they all share ONE refresh. */
  private refreshSession(): Promise<boolean> {
    if (!this.refreshInFlight) {
      this.refreshInFlight = this.doRefresh().finally(() => {
        this.refreshInFlight = null;
      });
    }
    return this.refreshInFlight;
  }

  private async doRefresh(): Promise<boolean> {
    const session = await this.store.load();
    if (!session) return false;
    try {
      const response = await this.send("/auth/refresh", {
        method: "POST",
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      });
      if (!response.ok) {
        // Only a refresh token the server REJECTS ends the session. A failed request
        // (no network) must not log the person out.
        if (response.status === 401 || response.status === 403) {
          await this.store.clear();
          this.endListeners.forEach((listener) => listener());
        }
        return false;
      }
      const body = (await response.json()) as { data?: { access_token?: string } };
      if (!body.data?.access_token) return false;
      await this.store.save({ ...session, accessToken: body.data.access_token });
      return true;
    } catch {
      return false;
    }
  }

  /** A request that needs a login. On 401 it refreshes the access token once and retries. */
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let session = await this.store.load();
    if (!session) throw new ApiError(401, "UNAUTHORIZED", "You are not logged in");

    let response = await this.send(path, init, session.accessToken);
    if (response.status === 401 && (await this.refreshSession())) {
      session = await this.store.load();
      if (session) response = await this.send(path, init, session.accessToken);
    }
    return this.parse<T>(response);
  }

  /** `validate` runs before anything is stored: if it throws, no tokens are kept. */
  async login(email: string, password: string, validate?: (user: User) => void): Promise<User> {
    const response = await this.send("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    const data = await this.parse<{ access_token: string; refresh_token: string; user: User }>(response);
    validate?.(data.user);
    // A new login starts without a device: the phone is registered again for this user.
    await this.store.save({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      deviceId: null,
      user: data.user,
    });
    return data.user;
  }

  me(): Promise<User> {
    return this.request<User>("/auth/me");
  }

  /** Fetches the user again and keeps the cached copy up to date. */
  async refreshUser(): Promise<User> {
    const user = await this.me();
    const session = await this.store.load();
    if (session) await this.store.save({ ...session, user });
    return user;
  }

  async registerDevice(token: string, platform: "android" | "ios"): Promise<string> {
    const device = await this.request<{ id: string }>("/devices", {
      method: "POST",
      body: JSON.stringify({ token, platform }),
    });
    const session = await this.store.load();
    if (session) await this.store.save({ ...session, deviceId: device.id });
    return device.id;
  }

  async removeDevice(): Promise<void> {
    const session = await this.store.load();
    if (!session?.deviceId) return;
    try {
      await this.request(`/devices/${session.deviceId}`, { method: "DELETE" });
    } catch (error) {
      // 404 only means it is already gone.
      if (!(error instanceof ApiError && error.status === 404)) throw error;
    }
  }

  /** Remove this phone from the backend (best effort), then forget the login. */
  async logout(): Promise<void> {
    try {
      await this.removeDevice();
    } catch {
      // Offline or expired: the session is cleared anyway. The backend also deletes
      // dead tokens by itself when a push to them fails.
    }
    await this.store.clear();
  }
}
