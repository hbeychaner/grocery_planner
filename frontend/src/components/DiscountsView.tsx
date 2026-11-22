import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Clock, ExternalLink, RefreshCw, Search, Tag } from "lucide-react";
import { useLang, type AppLang } from "../i18n";

interface ProductSale {
  sale_type: string;
  price: number | string;
  original_price?: number | string | null;
  unit_price?: number | string | null;
  discount_percentage?: number | null;
  started_at?: string | null;
  ends_at?: string | null;
  remaining?: number | null;
  welcome_price?: boolean;
  unlimited_amount?: boolean;
}

interface StoreProduct {
  store: "rohlik" | "kosik";
  product_id: string;
  name: string;
  brand?: string | null;
  price: number | string;
  original_price?: number | string | null;
  is_on_sale: boolean;
  discount_percentage?: number | null;
  sale_type?: string | null;
  sale_ends_at?: string | null;
  sales: ProductSale[];
  unit_type: string;
  unit_price?: number | string | null;
  image_url?: string | null;
  url?: string | null;
}

interface DiscountedProductItem {
  query: string;
  category?: string | null;
  product: StoreProduct;
  best_sale?: ProductSale | null;
  all_sales: ProductSale[];
}

interface DiscountTrackerResponse {
  scanned_queries: number;
  total_discounts: number;
  fetched_at: string;
  cached?: boolean;
  items: DiscountedProductItem[];
}

function parseTimestamp(ts?: string | null): Date | null {
  if (!ts) return null;
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatCountdown(
  endsAt: string | null | undefined,
  lang: AppLang,
  t: (en: string, cs: string) => string
): { label: string; urgent: boolean } {
  const end = parseTimestamp(endsAt);
  if (!end) {
    return { label: t("Ongoing / No end date", "Bez data ukončení"), urgent: false };
  }
  const diffMs = end.getTime() - Date.now();
  if (diffMs <= 0) {
    return { label: t("Ending today", "Končí dnes"), urgent: true };
  }
  const totalHours = Math.floor(diffMs / (1000 * 60 * 60));
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  const dateStr = end.toLocaleDateString(lang === "cs" ? "cs-CZ" : "en-US", {
    month: "short",
    day: "numeric",
  });
  if (days >= 1) {
    return {
      label:
        lang === "cs"
          ? `Končí za ${days}d ${hours}h (${dateStr})`
          : `Ends in ${days}d ${hours}h (${dateStr})`,
      urgent: days <= 2,
    };
  }
  const mins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
  return {
    label: lang === "cs" ? `Končí za ${hours}h ${mins}m` : `Ends in ${hours}h ${mins}m`,
    urgent: true,
  };
}

function saleTypeLabel(sale: ProductSale, t: (en: string, cs: string) => string): string {
  const tNorm = sale.sale_type.toLowerCase();
  if (tNorm === "expiration") return t("Near-Expiry", "Blízká expirace");
  if (tNorm === "premium") return sale.welcome_price ? t("Xtra / For You", "Xtra / Pro vás") : "Xtra";
  if (tNorm === "longtermaction") return t("Long-Term Sale", "Dlouhodobá akce");
  if (tNorm === "shorttermaction") return t("Short-Term Sale", "Krátkodobá akce");
  if (tNorm === "multipack") return t("Multipack Deal", "Výhodné balení");
  if (tNorm === "sale" || tNorm === "action") return t("Sale", "Akce");
  return sale.sale_type;
}

function saleBadgeStyle(sale: ProductSale): string {
  const t = sale.sale_type.toLowerCase();
  if (t === "expiration") return "bg-amber-100 text-amber-800 border-amber-200";
  if (t === "premium") return "bg-violet-100 text-violet-800 border-violet-200";
  return "bg-rose-100 text-rose-800 border-rose-200";
}

export function DiscountsView() {
  const { lang, t } = useLang();
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [storeFilter, setStoreFilter] = useState<"all" | "rohlik" | "kosik">("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "promo" | "expiration">("all");
  const [sortBy, setSortBy] = useState<"discount" | "ending" | "price">("discount");
  const [includeExpiration, setIncludeExpiration] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DiscountTrackerResponse | null>(null);

  const loadDiscounts = useCallback(
    async (searchTerm: string, incExp: boolean, forceRefresh = false) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (searchTerm.trim()) params.set("q", searchTerm.trim());
        params.set("include_expiration", String(incExp));
        if (forceRefresh) params.set("refresh", "true");
        const resp = await fetch(`/api/v1/discounts?${params.toString()}`);
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body.detail || "Failed to load discounts");
        }
        const json: DiscountTrackerResponse = await resp.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load discounts");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    loadDiscounts("", true);
  }, [loadDiscounts]);

  function handleSearchSubmit(e: FormEvent) {
    e.preventDefault();
    setActiveQuery(query.trim());
    loadDiscounts(query, includeExpiration);
  }

  function handleClearSearch() {
    setQuery("");
    setActiveQuery("");
    loadDiscounts("", includeExpiration);
  }

  function handleToggleExpiration(checked: boolean) {
    setIncludeExpiration(checked);
    if (!checked && typeFilter === "expiration") {
      setTypeFilter("all");
    }
    loadDiscounts(activeQuery, checked);
  }

  const filteredItems = useMemo(() => {
    const raw = data?.items || [];
    return raw
      .filter((item) => {
        if (storeFilter !== "all" && item.product.store !== storeFilter) return false;
        if (typeFilter === "expiration") {
          return item.all_sales.some((s) => s.sale_type.toLowerCase() === "expiration");
        }
        if (typeFilter === "promo") {
          return item.all_sales.some((s) => s.sale_type.toLowerCase() !== "expiration");
        }
        return true;
      })
      .sort((a, b) => {
        if (sortBy === "ending") {
          const aEnd = parseTimestamp(a.best_sale?.ends_at)?.getTime() ?? Number.MAX_SAFE_INTEGER;
          const bEnd = parseTimestamp(b.best_sale?.ends_at)?.getTime() ?? Number.MAX_SAFE_INTEGER;
          if (aEnd !== bEnd) return aEnd - bEnd;
        }
        if (sortBy === "price") {
          return Number(a.best_sale?.price ?? a.product.price) - Number(b.best_sale?.price ?? b.product.price);
        }
        const aPct = a.best_sale?.discount_percentage ?? 0;
        const bPct = b.best_sale?.discount_percentage ?? 0;
        if (bPct !== aPct) return bPct - aPct;
        return Number(a.product.price) - Number(b.product.price);
      });
  }, [data, storeFilter, typeFilter, sortBy]);

  const stats = useMemo(() => {
    const pcts = filteredItems
      .map((i) => i.best_sale?.discount_percentage)
      .filter((v): v is number => typeof v === "number" && v > 0);
    const avgPct = pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : 0;
    const maxPct = pcts.length ? Math.max(...pcts) : 0;
    const endingSoon = filteredItems.filter((i) => {
      const d = parseTimestamp(i.best_sale?.ends_at);
      if (!d) return false;
      const hours = (d.getTime() - Date.now()) / (1000 * 60 * 60);
      return hours <= 48;
    }).length;
    return { count: filteredItems.length, avgPct, maxPct, endingSoon };
  }, [filteredItems]);

  return (
    <div className="space-y-6">
      {/* Header & Search Controls */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Tag className="w-5 h-5 text-indigo-600" />
              <span>{t("Live Discount Tracker", "Sledování slev a akcí")}</span>
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              {t(
                "Tracks active sales, Xtra / For-You discounts, and near-expiry markdowns with end dates and remaining stock.",
                "Sleduje aktivní akce, Xtra / Pro vás slevy a zlevněné položky před expirací včetně konce platnosti a skladových zásob."
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={() => loadDiscounts(activeQuery, includeExpiration, true)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>
              {loading
                ? t("Scanning...", "Hledám...")
                : t("Refresh Live", "Obnovit živě")}
            </span>
          </button>
        </div>

        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t(
                "Scan discounts for a specific product (e.g., 'butter', 'máslo', 'pilsner') or leave blank for watchlist...",
                "Hledat slevy pro konkrétní produkt (např. 'máslo', 'mléko', 'pilsner') nebo nechat prázdné pro sledované položky..."
              )}
              className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition cursor-pointer"
          >
            {t("Scan", "Hledat")}
          </button>
          {activeQuery && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="px-4 py-2.5 rounded-xl border border-slate-200 text-slate-600 text-sm font-medium hover:bg-slate-50 cursor-pointer"
            >
              {t("Watchlist", "Sledované")}
            </button>
          )}
        </form>

        {/* Filters */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50">
              {(["all", "rohlik", "kosik"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStoreFilter(s)}
                  className={`px-2.5 py-1 rounded-md font-medium capitalize cursor-pointer ${
                    storeFilter === s ? "bg-white text-slate-900 shadow-2xs" : "text-slate-600"
                  }`}
                >
                  {s === "all" ? t("All Stores", "Všechny obchody") : s === "rohlik" ? "Rohlík" : "Košík"}
                </button>
              ))}
            </div>

            <div className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50">
              {(
                [
                  { id: "all", label: t("All Types", "Všechny typy") },
                  { id: "promo", label: t("Sales & Xtra", "Akce a Xtra") },
                  { id: "expiration", label: t("Near-Expiry", "Blízká expirace") },
                ] as const
              ).map((tOpt) => (
                <button
                  key={tOpt.id}
                  type="button"
                  onClick={() => setTypeFilter(tOpt.id)}
                  className={`px-2.5 py-1 rounded-md font-medium cursor-pointer ${
                    typeFilter === tOpt.id ? "bg-white text-slate-900 shadow-2xs" : "text-slate-600"
                  }`}
                >
                  {tOpt.label}
                </button>
              ))}
            </div>

            <label className="inline-flex items-center gap-1.5 text-slate-600 ml-1 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={includeExpiration}
                onChange={(e) => handleToggleExpiration(e.target.checked)}
                className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span>{t("Include Near-Expiry", "Včetně blízké expirace")}</span>
            </label>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-slate-500">{t("Sort:", "Řadit:")}</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "discount" | "ending" | "price")}
              className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="discount">{t("Biggest % Off", "Největší sleva %")}</option>
              <option value="ending">{t("Ending Soonest", "Končí nejdříve")}</option>
              <option value="price">{t("Lowest Price", "Nejnižší cena")}</option>
            </select>
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-xl border border-slate-200 bg-white p-3.5">
            <div className="text-[11px] text-slate-500 font-medium">{t("Active Discounts", "Aktivní slevy")}</div>
            <div className="text-xl font-bold text-slate-900 mt-0.5">{stats.count}</div>
            <div className="text-[11px] text-slate-400">
              {t(
                `Across ${data.scanned_queries} ${activeQuery ? "query" : "watchlist items"}`,
                `Napříč ${data.scanned_queries} ${activeQuery ? "dotazem" : "sledovanými položkami"}`
              )}
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-3.5">
            <div className="text-[11px] text-slate-500 font-medium">{t("Top Discount", "Nejvyšší sleva")}</div>
            <div className="text-xl font-bold text-emerald-700 mt-0.5">
              {stats.maxPct > 0 ? `-${stats.maxPct}%` : "—"}
            </div>
            <div className="text-[11px] text-slate-400">{t("Best markdown found", "Nejvýhodnější akce")}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-3.5">
            <div className="text-[11px] text-slate-500 font-medium">{t("Average Savings", "Průměrná sleva")}</div>
            <div className="text-xl font-bold text-indigo-700 mt-0.5">
              {stats.avgPct > 0 ? `-${stats.avgPct}%` : "—"}
            </div>
            <div className="text-[11px] text-slate-400">{t("Across filtered deals", "Z vyfiltrovaných položek")}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-3.5">
            <div className="text-[11px] text-slate-500 font-medium">{t("Ending ≤ 48h", "Končí do 48 h")}</div>
            <div className="text-xl font-bold text-amber-700 mt-0.5">{stats.endingSoon}</div>
            <div className="text-[11px] text-slate-400">{t("Time-sensitive deals", "Časově omezené akce")}</div>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center text-sm text-slate-500">
          Scanning Rohlík &amp; Košík for live discounts...
        </div>
      )}

      {!loading && data && filteredItems.length === 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center text-sm text-slate-500">
          No active discounts matched your current filters.
        </div>
      )}

      {/* Discount Grid */}
      {filteredItems.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
          {filteredItems.map((item) => {
            const p = item.product;
            const best = item.best_sale;
            const displayPrice = best ? Number(best.price) : Number(p.price);
            const displayOrig = best?.original_price
              ? Number(best.original_price)
              : p.original_price
              ? Number(p.original_price)
              : null;
            const displayUnit = best?.unit_price
              ? Number(best.unit_price)
              : p.unit_price
              ? Number(p.unit_price)
              : null;
            const countdown = formatCountdown(best?.ends_at, lang, t);

            return (
              <div
                key={`${p.store}-${p.product_id}`}
                className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs flex gap-3.5 items-start"
              >
                <div className="w-16 h-16 rounded-xl bg-slate-50 border border-slate-100 shrink-0 flex items-center justify-center overflow-hidden">
                  {p.image_url ? (
                    <img src={p.image_url} alt={p.name} className="w-full h-full object-contain" />
                  ) : (
                    <span className="text-[10px] text-slate-400">No img</span>
                  )}
                </div>

                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-md ${
                        p.store === "rohlik"
                          ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                          : "bg-amber-50 text-amber-800 border border-amber-200"
                      }`}
                    >
                      {p.store === "rohlik" ? "Rohlík.cz" : "Košík.cz"}
                    </span>
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 capitalize">
                      {item.query}
                    </span>
                    {item.all_sales.map((s, sIdx) => (
                      <span
                        key={`${s.sale_type}-${sIdx}`}
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-md border ${saleBadgeStyle(s)}`}
                      >
                        {s.discount_percentage ? `-${s.discount_percentage}% ` : ""}
                        {saleTypeLabel(s, t)}
                      </span>
                    ))}
                  </div>

                  <div>
                    {p.brand && <div className="text-[11px] text-slate-500">{p.brand}</div>}
                    <div className="text-sm font-semibold text-slate-900 leading-snug">{p.name}</div>
                  </div>

                  {/* Duration & Stock */}
                  <div className="flex flex-wrap items-center gap-3 text-[11px]">
                    <span
                      className={`inline-flex items-center gap-1 font-medium ${
                        countdown.urgent ? "text-amber-700" : "text-slate-500"
                      }`}
                    >
                      <Clock className="w-3 h-3" />
                      <span>{countdown.label}</span>
                    </span>
                    {best?.remaining != null && (
                      <span className="text-slate-500 font-medium">
                        {lang === "cs" ? `Zbývá ${best.remaining} ks` : `${best.remaining} left`}
                      </span>
                    )}
                  </div>

                  {/* Price Row */}
                  <div className="flex items-baseline justify-between pt-1">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-base font-bold text-slate-900">
                        {displayPrice.toFixed(2)} CZK
                      </span>
                      {displayOrig && displayOrig > displayPrice && (
                        <span className="text-xs text-slate-400 line-through">
                          {displayOrig.toFixed(2)} CZK
                        </span>
                      )}
                      {displayUnit != null && (
                        <span className="text-[11px] text-slate-500">
                          ({displayUnit.toFixed(2)} CZK/{p.unit_type})
                        </span>
                      )}
                    </div>
                    {p.url && (
                      <a
                        href={p.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 shrink-0"
                      >
                        <span>{t("Open", "Otevřít")}</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
