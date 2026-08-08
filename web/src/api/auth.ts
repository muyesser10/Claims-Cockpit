// Minimal JWT auth for the S3-8 login flow. No context/provider — every
// protected screen already polls via TanStack Query, so a 401 from
// authenticatedFetch surfaces as that query's isError state, which every
// screen already renders (CLAUDE.md: every screen needs an error state).

const TOKEN_KEY = "auth_token";

interface LoginResponse {
  access_token: string;
  token_type: string;
}

// API tamamen kapalıyken fetch bir yanıt üretmeden TypeError ile reject eder
// ("Failed to fetch" / "NetworkError when attempting to fetch resource" —
// tarayıcıya göre değişen, İngilizce metinler). Durum kodu yok, dolayısıyla
// aşağıdaki HTTP eşlemeleri hiç çalışmıyor ve o çıplak İngilizce mesaj
// doğrudan ekranda görünüyordu.
const NETWORK_ERROR_MESSAGE = "Sunucuya ulaşılamıyor, bağlantınızı kontrol edin.";

// fetch'i sarmalar: yalnızca ağ katmanı hatasını Türkçeleştirir, HTTP yanıtına
// (durum kodu dahil) dokunmaz — onu çağıran kendi bağlamına göre yorumluyor.
async function fetchOrNetworkError(url: string, options?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch {
    throw new Error(NETWORK_ERROR_MESSAGE);
  }
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetchOrNetworkError("/api/auth/login", {
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

  // Aynı ağ hatası buradan da geçiyor: her ekranın sorgusu bu fonksiyonu
  // kullandığı için API kapalıyken ErrorScreen "Failed to fetch" yerine
  // Türkçe mesajı gösteriyor.
  return fetchOrNetworkError(url, { ...options, headers });
}
