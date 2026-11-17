import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { searchLiterature } from "../api/client";
import type { SearchResponse, TopicInput } from "../types/paper";

export default function Discovery() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [keywords, setKeywords] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [sources, setSources] = useState(["openalex", "crossref"]);
  const [preferReviews, setPreferReviews] = useState(false);
  const [topK, setTopK] = useState(40);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);

  async function handleSearch() {
    if (!topic.trim()) {
      setError("Please enter a research topic");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const input: TopicInput = {
        topic: topic.trim(),
        keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
        year_from: yearFrom ? parseInt(yearFrom) : undefined,
        year_to: yearTo ? parseInt(yearTo) : undefined,
        sources,
        prefer_reviews: preferReviews,
        top_k: topK,
        expand_keywords: true,
      };
      const response = await searchLiterature(input);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  function toggleSource(source: string) {
    setSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Literature Discovery</h2>

      <div className="bg-slate-800 rounded-lg p-6 space-y-4">
        <div>
          <label className="block text-sm font-medium mb-2">Research Topic *</label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g., LLM Agent for smart contract vulnerability detection"
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Keywords (comma-separated)</label>
          <input
            type="text"
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="e.g., smart contract, vulnerability, LLM, agent"
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-400"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-2">Year From</label>
            <input
              type="number"
              value={yearFrom}
              onChange={(e) => setYearFrom(e.target.value)}
              placeholder="2020"
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Year To</label>
            <input
              type="number"
              value={yearTo}
              onChange={(e) => setYearTo(e.target.value)}
              placeholder="2024"
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Sources</label>
          <div className="flex gap-4">
            {["openalex", "crossref", "arxiv"].map((source) => (
              <label key={source} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={sources.includes(source)}
                  onChange={() => toggleSource(source)}
                  className="rounded"
                />
                <span className="capitalize">{source}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={preferReviews}
              onChange={(e) => setPreferReviews(e.target.checked)}
              className="rounded"
            />
            <span>Prefer review papers</span>
          </label>
          <div className="flex items-center gap-2">
            <label className="text-sm">Max results:</label>
            <input
              type="number"
              value={topK}
              onChange={(e) => setTopK(parseInt(e.target.value) || 40)}
              min={1}
              max={200}
              className="w-20 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-white"
            />
          </div>
        </div>

        <button
          onClick={handleSearch}
          disabled={loading || !topic.trim()}
          className="w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded font-medium transition"
        >
          {loading ? "Searching..." : "Start Search"}
        </button>

        {error && (
          <div className="p-3 bg-red-900/30 border border-red-700 rounded text-red-300">
            <strong>Error:</strong> {error}
            <button onClick={handleSearch} className="ml-2 underline">
              Retry
            </button>
          </div>
        )}
      </div>

      {result && (
        <div className="bg-slate-800 rounded-lg p-6 space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-xl font-semibold">Search Results</h3>
            <button
              onClick={() => navigate("/library")}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm"
            >
              View in Library →
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-slate-400">Papers Found</div>
              <div className="text-2xl font-bold">{result.papers.length}</div>
            </div>
            <div>
              <div className="text-slate-400">Duration</div>
              <div className="text-2xl font-bold">{result.meta.duration_ms}ms</div>
            </div>
            <div>
              <div className="text-slate-400">Cache Hits</div>
              <div className="text-2xl font-bold">{result.meta.cache_hits}</div>
            </div>
            <div>
              <div className="text-slate-400">API Requests</div>
              <div className="text-2xl font-bold">{result.meta.requests_made}</div>
            </div>
          </div>

          {result.source_errors.length > 0 && (
            <div className="p-3 bg-yellow-900/30 border border-yellow-700 rounded">
              <strong className="text-yellow-300">Source Errors:</strong>
              <ul className="mt-2 text-sm text-yellow-200 space-y-1">
                {result.source_errors.map((err, i) => (
                  <li key={i}>
                    {err.source}: {err.detail} (HTTP {err.status || "unknown"})
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="text-xs text-slate-400 bg-slate-900/50 p-3 rounded">
            <strong>Notice:</strong> {result.meta.notice}
          </div>

          <div className="space-y-2">
            {result.papers.slice(0, 10).map((paper) => (
              <div key={paper.paper_id} className="border border-slate-700 rounded p-3">
                <div className="font-medium">{paper.title}</div>
                <div className="text-sm text-slate-400 mt-1">
                  {paper.authors.slice(0, 3).join(", ")} {paper.authors.length > 3 ? "et al." : ""} •{" "}
                  {paper.publication_year || "n.d."} • {paper.source}
                  {paper.is_review && <span className="ml-2 px-2 py-0.5 bg-green-900/50 text-green-300 rounded text-xs">Review</span>}
                </div>
                {paper.abstract && (
                  <div className="text-xs text-slate-500 mt-2 line-clamp-2">{paper.abstract}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
