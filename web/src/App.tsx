import { Routes, Route, NavLink } from "react-router-dom";
import Pano from "./pages/Pano";
import Kuyruk from "./pages/Kuyruk";
import Soru from "./pages/Soru";
import Metrikler from "./pages/Metrikler";

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
          <Route path="/" element={<Pano />} />
          <Route path="/kuyruk" element={<Kuyruk />} />
          <Route path="/soru" element={<Soru />} />
          <Route path="/metrikler" element={<Metrikler />} />
        </Routes>
      </main>
    </div>
  );
}