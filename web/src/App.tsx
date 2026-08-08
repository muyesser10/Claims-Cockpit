import type { ReactNode } from "react";
import { Routes, Route, Navigate, NavLink, useNavigate } from "react-router-dom";
import Dashboard from './pages/Dashboard';
import Queue from './pages/Queue';
import Question from './pages/Question';
import Metrics from './pages/Metrics';
import Login from './pages/Login';
import ErrorBoundary from './components/ErrorBoundary';
import { isAuthenticated, logout } from './api/auth';

const navItems = [
  { to: "/", label: "Pano" },
  { to: "/kuyruk", label: "Kuyruk" },
  { to: "/soru", label: "Soru" },
  { to: "/metrikler", label: "Metrikler" },
];

// Minimal route guard — no auth context/provider (S3-8 keeps this
// deliberately simple). A stale/expired token isn't caught here; that
// surfaces as a 401 on the first authenticatedFetch call instead, which
// every screen already renders as its query's error state.
function RequireAuth({ children }: { children: ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="flex items-center gap-4 border-b bg-white px-6 py-3">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `text-sm font-medium ${isActive ? "text-blue-600" : "text-slate-500"}`
            }
          >
            {item.label}
          </NavLink>
        ))}
        <button
          onClick={handleLogout}
          className="ml-auto text-sm font-medium text-slate-500 hover:text-slate-700"
        >
          Çıkış Yap
        </button>
      </nav>
      <main className="p-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    // Bütün route ağacını saran tek sınır: bir render hatası artık beyaz ekran
    // yerine ErrorScreen gösteriyor. Sınır Routes'un dışında olduğu için
    // fallback'te nav da görünmez — çıkış yolu retry butonu ya da sayfa yenileme.
    <ErrorBoundary>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Shell>
                <Dashboard />
              </Shell>
            </RequireAuth>
          }
        />
        <Route
          path="/kuyruk"
          element={
            <RequireAuth>
              <Shell>
                <Queue />
              </Shell>
            </RequireAuth>
          }
        />
        <Route
          path="/soru"
          element={
            <RequireAuth>
              <Shell>
                <Question />
              </Shell>
            </RequireAuth>
          }
        />
        <Route
          path="/metrikler"
          element={
            <RequireAuth>
              <Shell>
                <Metrics />
              </Shell>
            </RequireAuth>
          }
        />
      </Routes>
    </ErrorBoundary>
  );
}