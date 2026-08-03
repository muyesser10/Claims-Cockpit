import { Routes, Route, NavLink } from "react-router-dom";
import Dashboard from './pages/Dashboard';
import Queue from './pages/Queue';
import Question from './pages/Question';
import Metrics from './pages/Metrics';

const navItems = [
  { to: "/", label: "Pano" },
  { to: "/kuyruk", label: "Kuyruk" },
  { to: "/soru", label: "Soru" },
  { to: "/metrikler", label: "Metrikler" },
];

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="flex gap-4 border-b bg-white px-6 py-3">
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
      </nav>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/kuyruk" element={<Queue />} />
          <Route path="/soru" element={<Question/>} />
          <Route path="/metrikler" element={<Metrics />} />
        </Routes>
      </main>
    </div>
  );
}