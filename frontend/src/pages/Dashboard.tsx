import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import { listPapers } from "../api/client";
import type { Paper } from "../types/paper";

export default function Dashboard() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPapers();
  }, []);

  async function loadPapers() {
    try {
      const result = await listPapers({ page: 1, page_size: 100 });
      setPapers(result.papers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load papers");
    } finally {
      setLoading(false);
    }
  }

  if (loading) return <div className="text-center py-12">Loading...</div>;
  if (error) return <div className="text-center py-12 text-red-400">{error}</div>;

  // Year distribution
  const yearCounts: Record<number, number> = {};
  papers.forEach((p) => {
    if (p.publication_year) {
      yearCounts[p.publication_year] = (yearCounts[p.publication_year] || 0) + 1;
    }
  });
  const yearData = Object.entries(yearCounts)
    .map(([year, count]) => ({ year, count }))
    .sort((a, b) => Number(a.year) - Number(b.year));

  // Source distribution
  const sourceCounts: Record<string, number> = {};
  papers.forEach((p) => {
    sourceCounts[p.source] = (sourceCounts[p.source] || 0) + 1;
  });
  const sourceData = Object.entries(sourceCounts).map(([name, value]) => ({ name, value }));
  const COLORS = ["#3b82f6", "#10b981", "#f59e0b"];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Research Dashboard</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-800 rounded-lg p-4">
          <div className="text-sm text-slate-400">Total Papers</div>
          <div className="text-3xl font-bold text-blue-400">{papers.length}</div>
        </div>
        <div className="bg-slate-800 rounded-lg p-4">
          <div className="text-sm text-slate-400">Review Papers</div>
          <div className="text-3xl font-bold text-green-400">
            {papers.filter((p) => p.is_review).length}
          </div>
        </div>
        <div className="bg-slate-800 rounded-lg p-4">
          <div className="text-sm text-slate-400">Unique Sources</div>
          <div className="text-3xl font-bold text-yellow-400">{sourceData.length}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-800 rounded-lg p-4">
          <h3 className="text-lg font-semibold mb-4">Papers by Year</h3>
          {yearData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={yearData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="year" stroke="#94a3b8" />
                <YAxis stroke="#94a3b8" />
                <Tooltip contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155" }} />
                <Bar dataKey="count" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-center py-12 text-slate-500">No year data available</div>
          )}
        </div>

        <div className="bg-slate-800 rounded-lg p-4">
          <h3 className="text-lg font-semibold mb-4">Papers by Source</h3>
          {sourceData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={sourceData} cx="50%" cy="50%" outerRadius={80} dataKey="value" label={({ name, value }) => `${name}: ${value}`}>
                  {sourceData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155" }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-center py-12 text-slate-500">No source data available</div>
          )}
        </div>
      </div>

      <div className="bg-slate-800 rounded-lg p-4">
        <h3 className="text-lg font-semibold mb-4">Recent Papers</h3>
        {papers.length > 0 ? (
          <div className="space-y-2">
            {papers.slice(0, 5).map((paper) => (
              <div key={paper.paper_id} className="border border-slate-700 rounded p-3">
                <div className="font-medium">{paper.title}</div>
                <div className="text-sm text-slate-400 mt-1">
                  {paper.authors.slice(0, 3).join(", ")} {paper.authors.length > 3 ? "et al." : ""} •{" "}
                  {paper.publication_year || "n.d."} • {paper.source}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-slate-500">No papers yet. Start a search!</div>
        )}
      </div>
    </div>
  );
}
