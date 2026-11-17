import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard", phase: null },
  { path: "/discovery", label: "Literature Discovery", phase: null },
  { path: "/library", label: "Literature Library", phase: null },
  { path: "/matrix", label: "Literature Matrix", phase: null },
  { path: "/report", label: "Research Report", phase: null },
  { path: "/gaps", label: "Research Gap", phase: 2 },
  { path: "/experiments", label: "Experiment Lab", phase: 3 },
  { path: "/evolution", label: "Evolution Lab", phase: 4 },
  { path: "/skills", label: "Skill Registry", phase: 5 },
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
            const isPlaceholder = item.phase !== null;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`block px-3 py-2 rounded text-sm transition ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : isPlaceholder
                    ? "text-slate-500 hover:bg-slate-700"
                    : "text-slate-300 hover:bg-slate-700"
                }`}
              >
                {item.label}
                {isPlaceholder && (
                  <span className="ml-2 text-xs bg-slate-600 px-1.5 py-0.5 rounded">
                    Phase {item.phase}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  );
}
