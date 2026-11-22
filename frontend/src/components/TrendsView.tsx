import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface CategoryRow {
  category: string;
  display_name: string;
  item_count: number;
  avg_rohlik_unit_price: number | null;
  avg_kosik_unit_price: number | null;
  blended_avg_unit_price: number | null;
  avg_bio_unit_price: number | null;
  avg_csu_unit_price: number | null;
  avg_bls_unit_price: number | null;
  wow_change_pct: number | null;
}

interface SeriesPoint {
  recorded_at: string;
  avg_rohlik: number | null;
  avg_kosik: number | null;
  blended_avg: number | null;
  avg_bio: number | null;
  avg_csu: number | null;
  avg_bls: number | null;
}

interface TrackedItem {
  query: string;
  query_cs?: string | null;
  category?: string | null;
  latest_rohlik_unit_price?: number | null;
  latest_kosik_unit_price?: number | null;
  latest_unit_type?: string | null;
}

export function TrendsView() {
  const [mode, setMode] = useState<"comparison" | "generic">("comparison");
  const [normalizeByIncome, setNormalizeByIncome] = useState(false);
  const [rebaseIndex, setRebaseIndex] = useState(false);
  const [days, setDays] = useState("730");
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [selectedCategory, setSelectedCategory] = useState("overall");
  const [seriesPoints, setSeriesPoints] = useState<SeriesPoint[]>([]);
  const [stats, setStats] = useState<{ tracked_items_count?: number; total_snapshots?: number; last_recorded_at?: string }>({});
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [rankedItems, setRankedItems] = useState<TrackedItem[] | null>(null);
  const [filterText, setFilterText] = useState("");
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  function stripAccents(str: string): string {
    return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  async function loadDashboard(
    cat = selectedCategory,
    m = mode,
    norm = normalizeByIncome,
    d = days,
    rebase = rebaseIndex
  ) {
    const [analyticsResp, seriesResp, itemsResp] = await Promise.all([
      fetch(`/api/v1/history/analytics?mode=${m}&normalize_by_income=${norm}`),
      fetch(
        `/api/v1/history/analytics/series?category=${encodeURIComponent(cat)}&days=${d}&mode=${m}&normalize_by_income=${norm}&rebase_index=${rebase}`
      ),
      fetch("/api/v1/history/items"),
    ]);

    if (analyticsResp.ok) {
      const aData = await analyticsResp.json();
      setCategories([aData.overall, ...(aData.categories || [])]);
    }
    if (seriesResp.ok) {
      const sData = await seriesResp.json();
      setSeriesPoints(sData.points || []);
    }
    if (itemsResp.ok) {
      const iData = await itemsResp.json();
      setStats(iData.stats || {});
      setItems(iData.items || []);
    }
  }

  useEffect(() => {
    loadDashboard();
  }, [selectedCategory, mode, normalizeByIncome, days, rebaseIndex]);

  useEffect(() => {
    const q = filterText.trim();
    if (!q) {
      setRankedItems(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const catParam = selectedCategory !== "overall" ? `&category=${encodeURIComponent(selectedCategory)}` : "";
        const resp = await fetch(`/api/v1/history/items/search?q=${encodeURIComponent(q)}${catParam}`);
        if (resp.ok) {
          const data: TrackedItem[] = await resp.json();
          setRankedItems(data);
        }
      } catch (_) {}
    }, 180);
    return () => clearTimeout(timer);
  }, [filterText, selectedCategory]);

  async function triggerAction(endpoint: string, label: string) {
    setStatusMsg(`Running ${label}...`);
    try {
      const resp = await fetch(endpoint, { method: "POST" });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `${label} failed`);
      }
      setStatusMsg(`${label} completed.`);
      await loadDashboard();
    } catch (err) {
      setStatusMsg(err instanceof Error ? err.message : `${label} failed`);
    }
  }

  const activeMeta = categories.find((c) => c.category === selectedCategory) || categories[0];
  const fmtVal = (v: number | null | undefined) =>
    v !== null && v !== undefined
      ? normalizeByIncome
        ? `${v.toFixed(4)}%`
        : `${v.toFixed(2)} CZK`
      : "—";

  const filteredItems = (() => {
    const q = stripAccents(filterText.trim());
    if (!q) {
      return items.filter((it) => selectedCategory === "overall" || it.category === selectedCategory);
    }
    if (rankedItems) {
      return rankedItems;
    }
    const base = items.filter((it) => selectedCategory === "overall" || it.category === selectedCategory);
    return [...base].sort((a, b) => {
      const score = (it: TrackedItem) => {
        const en = stripAccents(it.query);
        const cs = stripAccents(it.query_cs || "");
        if (en === q || cs === q) return 4;
        if (en.startsWith(q) || cs.startsWith(q)) return 3;
        if (en.includes(q) || cs.includes(q)) return 2;
        return 0;
      };
      return score(b) - score(a);
    });
  })();

  return (
    <div className="space-y-5">
      {/* Top KPIs & Actions */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-6">
          <div>
            <div className="text-[11px] font-semibold uppercase text-slate-400">Tracked Groceries</div>
            <div className="text-xl font-bold text-slate-900">{stats.tracked_items_count ?? "—"}</div>
          </div>
          <div>
            <div className="text-[11px] font-semibold uppercase text-slate-400">Recorded Snapshots</div>
            <div className="text-xl font-bold text-slate-900">{stats.total_snapshots ?? "—"}</div>
          </div>
          <div>
            <div className="text-[11px] font-semibold uppercase text-slate-400">Last Check</div>
            <div className="text-sm font-semibold text-slate-700 mt-1">{stats.last_recorded_at || "—"}</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <button
            type="button"
            onClick={() => triggerAction("/api/v1/history/ingest-csu", "ČSÚ Sync")}
            className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 font-medium cursor-pointer"
          >
            Sync ČSÚ
          </button>
          <button
            type="button"
            onClick={() => triggerAction("/api/v1/history/ingest-bls", "US BLS Sync")}
            className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 font-medium cursor-pointer"
          >
            Sync US (BLS)
          </button>
          <button
            type="button"
            onClick={() => triggerAction("/api/v1/history/run?limit=10", "Price Check (10)")}
            className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 font-medium cursor-pointer"
          >
            Run Check (10)
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2 text-xs text-indigo-800">
          {statusMsg}
        </div>
      )}

      {/* Main Analytics Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* Category Selector */}
        <aside className="lg:col-span-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-900">Categories</h3>
            <div className="inline-flex rounded-lg border border-slate-200 p-0.5 text-xs bg-slate-50">
              <button
                type="button"
                onClick={() => setMode("comparison")}
                className={`px-2.5 py-1 rounded-md font-medium cursor-pointer ${
                  mode === "comparison" ? "bg-indigo-600 text-white" : "text-slate-600"
                }`}
              >
                Comparison
              </button>
              <button
                type="button"
                onClick={() => setMode("generic")}
                className={`px-2.5 py-1 rounded-md font-medium cursor-pointer ${
                  mode === "generic" ? "bg-indigo-600 text-white" : "text-slate-600"
                }`}
              >
                Generic
              </button>
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={normalizeByIncome}
              onChange={(e) => setNormalizeByIncome(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600"
            />
            <span>Normalize by Median Income (CZ vs. Midwest US)</span>
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={rebaseIndex}
              onChange={(e) => setRebaseIndex(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600"
            />
            <span>Relative Inflation Mode (Base = 100)</span>
          </label>

          <div className="max-h-80 overflow-y-auto space-y-1 pr-1">
            {categories.map((row) => {
              const active = row.category === selectedCategory;
              return (
                <button
                  key={row.category}
                  type="button"
                  onClick={() => setSelectedCategory(row.category)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs text-left transition cursor-pointer ${
                    active
                      ? "bg-indigo-50 text-indigo-900 font-semibold border border-indigo-200"
                      : "hover:bg-slate-50 text-slate-700 border border-transparent"
                  }`}
                >
                  <span>
                    {row.display_name} ({row.item_count})
                  </span>
                  <span className="text-slate-500">
                    {row.blended_avg_unit_price !== null
                      ? normalizeByIncome
                        ? `${row.blended_avg_unit_price.toFixed(3)}%`
                        : `${row.blended_avg_unit_price.toFixed(1)} CZK`
                      : "—"}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Chart & KPIs */}
        <div className="lg:col-span-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-900">
                {activeMeta?.display_name || "Overall"}
              </h2>
              <p className="text-xs text-slate-500">
                {mode === "comparison"
                  ? "Comparison mode: Rohlík ∩ Košík & ČSÚ ∩ US BLS"
                  : "Generic mode: all available items per source"}
                {normalizeByIncome ? " • Normalized as % of monthly median income" : ""}
                {rebaseIndex ? " • Rebased to Index 100 at start of window" : ""}
              </p>
            </div>
            <select
              value={days}
              onChange={(e) => setDays(e.target.value)}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white"
            >
              <option value="90">Last 3 months</option>
              <option value="365">Last 12 months</option>
              <option value="730">Last 24 months</option>
              <option value="3650">All time</option>
            </select>
          </div>

          {activeMeta && (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2 text-xs">
              <KpiPill label="Blended" value={fmtVal(activeMeta.blended_avg_unit_price)} />
              <KpiPill label="Rohlík" value={fmtVal(activeMeta.avg_rohlik_unit_price)} />
              <KpiPill label="Košík" value={fmtVal(activeMeta.avg_kosik_unit_price)} />
              <KpiPill label="BIO" value={fmtVal(activeMeta.avg_bio_unit_price)} />
              <KpiPill label="ČSÚ Avg" value={fmtVal(activeMeta.avg_csu_unit_price)} />
              <KpiPill label="US BLS" value={fmtVal(activeMeta.avg_bls_unit_price)} />
            </div>
          )}

          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={seriesPoints}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="recorded_at" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={56} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: "11px" }} />
                <Line type="monotone" dataKey="blended_avg" name="Blended" stroke="#0f172a" strokeWidth={2} connectNulls dot={false} />
                <Line type="monotone" dataKey="avg_rohlik" name="Rohlík" stroke="#7c3aed" connectNulls dot={false} />
                <Line type="monotone" dataKey="avg_kosik" name="Košík" stroke="#d97706" connectNulls dot={false} />
                <Line type="monotone" dataKey="avg_bio" name="BIO" stroke="#16a34a" strokeDasharray="4 4" connectNulls dot={false} />
                <Line type="monotone" dataKey="avg_csu" name="ČSÚ Avg" stroke="#64748b" strokeDasharray="2 3" connectNulls dot={false} />
                <Line type="monotone" dataKey="avg_bls" name="US BLS" stroke="#2563eb" strokeDasharray="4 4" connectNulls dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Watchlist Table */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-900">Tracked Watchlist ({filteredItems.length})</h3>
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Filter groceries..."
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-300 w-56"
          />
        </div>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-2 pr-3">Item</th>
                <th className="py-2 pr-3">Czech</th>
                <th className="py-2 pr-3">Category</th>
                <th className="py-2 pr-3">Rohlík</th>
                <th className="py-2">Košík</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.slice(0, 50).map((it) => (
                <tr key={it.query} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-medium text-slate-900 capitalize">{it.query}</td>
                  <td className="py-2 pr-3 text-slate-500">{it.query_cs || "—"}</td>
                  <td className="py-2 pr-3 text-slate-500">{it.category || "—"}</td>
                  <td className="py-2 pr-3">
                    {it.latest_rohlik_unit_price != null
                      ? `${it.latest_rohlik_unit_price.toFixed(2)} / ${it.latest_unit_type || "kg"}`
                      : "—"}
                  </td>
                  <td className="py-2">
                    {it.latest_kosik_unit_price != null
                      ? `${it.latest_kosik_unit_price.toFixed(2)} / ${it.latest_unit_type || "kg"}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function KpiPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
      <div className="text-[10px] text-slate-500 uppercase font-medium">{label}</div>
      <div className="text-xs font-bold text-slate-900 mt-0.5">{value}</div>
    </div>
  );
}
