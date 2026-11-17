import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard" },
  { path: "/discovery", label: "Literature Discovery" },
  { path: "/library", label: "Literature Library" },
  { path: "/matrix", label: "Literature Matrix" },
  { path: "/report", label: "Research Report" },
  { path: "/gaps", label: "Research Gap" },
  { path: "/experiments", label: "Experiment Lab" },
  { path: "/evolution", label: "Evolution Lab" },
  { path: "/skills", label: "Skill Registry" },
  { path: "/workflow", label: "18-Step Workflow" },
  { path: "/dossier", label: "Research Dossier" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();

  return (
    <div className="flex min-h-screen bg-slate-900 text-slate-100">
      <aside className="w-64 bg-slate-800 border-r border-slate-700 p-4">
        <h1 className="text-xl font-bold mb-6 text-blue-400">ResearchLoop Evo</h1>
        <nav className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`block px-3 py-2 rounded text-sm transition ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-slate-300 hover:bg-slate-700"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  );
}
