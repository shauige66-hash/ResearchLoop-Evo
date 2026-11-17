import { useEffect, useState } from "react";

interface PlaceholderProps {
  phase: number;
  title: string;
  description: string;
}

export default function Placeholder({ phase, title, description }: PlaceholderProps) {
  const [status, setStatus] = useState<"loading" | "not_implemented" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    checkStatus();
  }, []);

  async function checkStatus() {
    try {
      // Try to call a future endpoint to confirm it returns 501
      const endpoints: Record<number, string> = {
        2: "/api/gaps/discover",
        3: "/api/experiments/design",
        4: "/api/evolve/skills",
        5: "/api/skills/evaluate",
      };
      const endpoint = endpoints[phase];
      if (!endpoint) {
        setStatus("not_implemented");
        return;
      }

      const response = await fetch(endpoint, { method: "POST" });
      if (response.status === 501) {
        setStatus("not_implemented");
      } else {
        setStatus("error");
        setError(`Unexpected status: ${response.status}`);
      }
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Network error");
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">{title}</h2>

      <div className="bg-slate-800 rounded-lg p-8 text-center">
        <div className="text-6xl mb-4">🚧</div>
        <h3 className="text-xl font-semibold mb-2">Phase {phase} — Not Yet Implemented</h3>
        <p className="text-slate-400 mb-6">{description}</p>

        {status === "loading" && (
          <div className="text-slate-500">Checking status...</div>
        )}

        {status === "not_implemented" && (
          <div className="bg-yellow-900/30 border border-yellow-700 rounded p-4 text-left">
            <strong className="text-yellow-300">Status:</strong>
            <p className="text-sm text-yellow-200 mt-2">
              This module is planned for Phase {phase} but has not been implemented yet.
              The backend endpoint correctly returns HTTP 501 (Not Implemented).
            </p>
          </div>
        )}

        {status === "error" && (
          <div className="bg-red-900/30 border border-red-700 rounded p-4 text-left">
            <strong className="text-red-300">Error:</strong>
            <p className="text-sm text-red-200 mt-2">{error}</p>
          </div>
        )}

        <div className="mt-6 text-sm text-slate-500">
          Current progress: Phase 1 (Literature Discovery) is complete.
          <br />
          See <code className="bg-slate-900 px-1 rounded">TASKS.md</code> for the full roadmap.
        </div>
      </div>
    </div>
  );
}
