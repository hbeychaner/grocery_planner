export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  auth_provider: string;
}

export interface AuthStatus {
  authenticated: boolean;
  user: AuthUser | null;
  google_oauth_enabled: boolean;
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const resp = await fetch("/api/v1/auth/me");
  if (!resp.ok) {
    return { authenticated: false, user: null, google_oauth_enabled: false };
  }
  return resp.json();
}

export async function loginLocal(email: string, password: string): Promise<AuthStatus> {
  const resp = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || "Sign in failed");
  return data;
}

export async function registerLocal(
  email: string,
  password: string,
  displayName?: string
): Promise<AuthStatus> {
  const resp = await fetch("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || "Registration failed");
  return data;
}

export async function logoutUser(): Promise<void> {
  await fetch("/api/v1/auth/logout", { method: "POST" });
}

export async function sendA2AMessage(text: string): Promise<string> {
  const id = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  const resp = await fetch("/a2a", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "A2A-Version": "1.0",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id,
      method: "SendMessage",
      params: {
        message: {
          messageId: id,
          role: "ROLE_USER",
          parts: [{ text }],
        },
      },
    }),
  });
  const rpc = await resp.json();
  if (rpc.error) {
    throw new Error(rpc.error.message || "Agent error");
  }
  const res = rpc.result || {};
  const parts =
    res.task?.status?.message?.parts ||
    res.message?.parts ||
    res.status?.message?.parts ||
    [];
  const texts = parts.map((p: { text?: string }) => p.text).filter(Boolean);
  return texts.length > 0 ? texts.join("\n") : JSON.stringify(res);
}
