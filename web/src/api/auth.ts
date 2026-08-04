// Minimal JWT auth for the S3-8 login flow. No context/provider — every
// protected screen already polls via TanStack Query, so a 401 from
// authenticatedFetch surfaces as that query's isError state, which every
// screen already renders (CLAUDE.md: every screen needs an error state).

const TOKEN_KEY = "auth_token";

interface LoginResponse {
  access_token: string;
  token_type: string;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    throw new Error(
      res.status === 401 ? "Geçersiz e-posta veya şifre" : `Giriş başarısız: ${res.status}`,
    );
  }
  const data: LoginResponse = await res.json();
  localStorage.setItem(TOKEN_KEY, data.access_token);
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

// Wraps fetch(), attaching Authorization: Bearer <token>. Rejects up front
// (no network call) when there is no token — callers see that as a failed
// query the same way they would see any other fetch failure.
export async function authenticatedFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  if (!token) {
    return Promise.reject(new Error("Not authenticated"));
  }

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);

  return fetch(url, { ...options, headers });
}
