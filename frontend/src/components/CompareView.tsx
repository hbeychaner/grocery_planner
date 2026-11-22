import { useState, type FormEvent } from "react";
import { ExternalLink, Search } from "lucide-react";

interface ProductItem {
  product_id: string;
  name: string;
  brand?: string | null;
  price: number | string;
  original_price?: number | string | null;
  is_on_sale?: boolean;
  discount_percentage?: number | null;
  sale_type?: string | null;
  unit_type: string;
  unit_price?: number | string | null;
  package_amount?: number | string | null;
  image_url?: string | null;
  url?: string | null;
}

interface KupiDeal {
  store: string;
  product_name: string;
  price: number;
  unit_price?: number | null;
  unit_type?: string | null;
  url?: string | null;
}

interface ComparisonData {
  query: string;
  query_translated: string;
  advantage: string;
  price_difference: number | string;
  percentage_savings: number | string;
  rohlik_ranked: ProductItem[];
  kosik_ranked: ProductItem[];
  rohlik_candidates: ProductItem[];
  kosik_candidates: ProductItem[];
  primary_pair?: {
    rohlik_product?: ProductItem | null;
    kosik_product?: ProductItem | null;
  } | null;
}

const STAPLES = ["butter", "whole milk", "eggs", "pilsner urquell", "bananas"];

export function CompareView() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [kupiDeals, setKupiDeals] = useState<KupiDeal[]>([]);

  async function runSearch(term: string) {
    const clean = term.trim();
    if (!clean) return;
    setQuery(clean);
    setLoading(true);
    setError(null);

    try {
      const [compResp, kupiResp] = await Promise.all([
        fetch(`/api/v1/compare?q=${encodeURIComponent(clean)}&lang=en`),
        fetch(`/api/v1/compare/kupi?q=${encodeURIComponent(clean)}`).catch(() => null),
      ]);
      if (!compResp.ok) {
        const body = await compResp.json().catch(() => ({}));
        throw new Error(body.detail || "Comparison request failed");
      }
      const compData: ComparisonData = await compResp.json();
      setComparison(compData);
      if (kupiResp && kupiResp.ok) {
        const kupiData = await kupiResp.json();
        setKupiDeals(kupiData.deals || []);
      } else {
        setKupiDeals([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch comparison");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    runSearch(query);
  }

  const rohlikList =
    comparison?.rohlik_ranked?.length
      ? comparison.rohlik_ranked
      : comparison?.rohlik_candidates || [];
  const kosikList =
    comparison?.kosik_ranked?.length
      ? comparison.kosik_ranked
      : comparison?.kosik_candidates || [];

  const unitLabel =
    comparison?.primary_pair?.rohlik_product?.unit_type ||
    comparison?.primary_pair?.kosik_product?.unit_type ||
    rohlikList[0]?.unit_type ||
    kosikList[0]?.unit_type ||
    "unit";

  return (
    <div className="space-y-6">
      {/* Search Card */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search any grocery item (e.g., 'butter', 'whole milk', 'blueberries')..."
              required
              className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="px-5 py-2.5 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition cursor-pointer"
          >
            {loading ? "Searching..." : "Compare"}
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-500 font-medium">Quick staples:</span>
          {STAPLES.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => runSearch(item)}
              className="px-3 py-1 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 capitalize transition cursor-pointer"
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {comparison && !loading && (
        <div className="space-y-6">
          {/* Winner Banner */}
          {(comparison.advantage === "rohlik_cheaper" || comparison.advantage === "kosik_cheaper") &&
            Number(comparison.price_difference) > 0 && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
                <strong>
                  {comparison.advantage === "rohlik_cheaper" ? "Rohlík is cheaper." : "Košík is cheaper."}
                </strong>{" "}
                Save {comparison.price_difference} CZK per {unitLabel === "pcs" ? "piece" : unitLabel} (
                {comparison.percentage_savings}%).
              </div>
            )}

          {/* Side-by-side Store Columns */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <StoreColumn title="Rohlík.cz" accent="text-emerald-700" products={rohlikList} />
            <StoreColumn title="Košík.cz" accent="text-amber-700" products={kosikList} />
          </div>

          {/* Kupi.cz Supermarket Promos */}
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">
                Brick-and-Mortar Supermarket Deals (Kupi.cz)
              </h3>
              <p className="text-xs text-slate-500">
                Active promotions across Tesco, Lidl, Penny, Kaufland, Billa &amp; Albert
              </p>
            </div>
            {kupiDeals.length === 0 ? (
              <p className="text-xs text-slate-400">
                No active Kupi.cz leaflet promotions found for this item.
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                {kupiDeals.map((d, idx) => (
                  <div
                    key={`${d.store}-${idx}`}
                    className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-1.5"
                  >
                    <div className="text-[11px] font-bold uppercase tracking-wide text-slate-600">
                      {d.store}
                    </div>
                    <div className="text-xs font-semibold text-slate-900 line-clamp-2">
                      {d.product_name}
                    </div>
                    <div className="flex items-baseline justify-between pt-1">
                      <span className="text-sm font-bold text-emerald-700">
                        {Number(d.price).toFixed(2)} CZK
                      </span>
                      {d.unit_price && (
                        <span className="text-[11px] text-slate-500">
                          {Number(d.unit_price).toFixed(2)} CZK / {d.unit_type}
                        </span>
                      )}
                    </div>
                    {d.url && (
                      <a
                        href={d.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-600 hover:underline pt-1"
                      >
                        View deal <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StoreColumn({
  title,
  accent,
  products,
}: {
  title: string;
  accent: string;
  products: ProductItem[];
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-3">
      <div className={`text-sm font-bold ${accent}`}>{title}</div>
      {products.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-400">
          No matching products found on {title}.
        </div>
      ) : (
        <div className="space-y-2.5">
          {products.map((p, idx) => (
            <div
              key={`${p.product_id}-${idx}`}
              className={`rounded-xl border p-3 flex gap-3 items-start ${
                idx === 0 ? "border-indigo-300 bg-indigo-50/30" : "border-slate-200 bg-white"
              }`}
            >
              <div className="w-12 h-12 rounded-lg bg-slate-50 border border-slate-100 shrink-0 flex items-center justify-center overflow-hidden">
                {p.image_url ? (
                  <img src={p.image_url} alt={p.name} className="w-full h-full object-contain" />
                ) : (
                  <span className="text-[10px] text-slate-400">No img</span>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap gap-1.5 mb-1">
                  {idx === 0 && (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-indigo-100 text-indigo-800">
                      Best Value
                    </span>
                  )}
                  {p.is_on_sale && (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-red-100 text-red-700">
                      {p.discount_percentage ? `-${p.discount_percentage}%` : "SALE"}
                      {p.sale_type === "premium" ? " Xtra" : ""}
                    </span>
                  )}
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-slate-100 text-slate-600">
                    {p.unit_type}
                  </span>
                </div>
                {p.brand && <div className="text-[11px] text-slate-500">{p.brand}</div>}
                <div className="text-xs font-semibold text-slate-900 leading-snug">{p.name}</div>
                <div className="flex items-baseline justify-between mt-2">
                  <div>
                    <span className="text-sm font-bold text-slate-900">
                      {Number(p.price).toFixed(2)} CZK
                    </span>
                    {p.original_price && Number(p.original_price) > Number(p.price) && (
                      <span className="text-[11px] text-slate-400 line-through ml-1.5">
                        {Number(p.original_price).toFixed(2)} CZK
                      </span>
                    )}
                    {p.unit_price && (
                      <span className="text-[11px] text-slate-500 ml-2">
                        ({Number(p.unit_price).toFixed(2)} CZK/{p.unit_type})
                      </span>
                    )}
                  </div>
                  {p.url && (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] font-medium text-indigo-600 hover:underline"
                    >
                      Open
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
