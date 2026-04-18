import { useState, useEffect } from "react";
import { productsApi } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";
import { localizeCategory } from "@/i18n/productContent";
import ProductCard from "./ProductCard";

export default function ProductGrid() {
  const [products, setProducts] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const limit = 12;
  const { t, lang } = useI18n();

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setCategory(p.get("categoria") ?? "");
    setSearch(p.get("buscar") ?? "");
  }, []);

  useEffect(() => {
    productsApi.categories().then((r) => setCategories(r.data ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params: string[] = [`limit=${limit}`, `offset=${(page - 1) * limit}`];
    if (category) params.push(`category=${encodeURIComponent(category)}`);
    if (search) params.push(`search=${encodeURIComponent(search)}`);

    productsApi.list(`?${params.join("&")}`)
      .then((r) => {
        setProducts(r.data ?? []);
        setTotal(r.total ?? 0);
      })
      .catch(() => setError(t("products.errorLoad")))
      .finally(() => setLoading(false));
  }, [category, search, page]);

  const totalPages = Math.ceil(total / limit);

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 1 1-14 0 7 7 0 0 1 14 0z" />
          </svg>
          <input
            type="text"
            placeholder={t("products.searchPlaceholder")}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="w-full pl-9 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => { setCategory(""); setPage(1); }}
            className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              !category ? "bg-indigo-600 text-white" : "bg-white border border-gray-300 text-gray-700 hover:border-indigo-400"
            }`}
          >
            {t("products.all")}
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => { setCategory(c.slug); setPage(1); }}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                category === c.slug
                  ? "bg-indigo-600 text-white"
                  : "bg-white border border-gray-300 text-gray-700 hover:border-indigo-400"
              }`}
            >
              {localizeCategory(c, lang).name}
            </button>
          ))}
        </div>
      </div>

      {/* Results count */}
      {!loading && (
        <p className="text-sm text-gray-500 mb-4">
          {total} {total === 1 ? t("products.result") : t("products.results")}
          {category && ` ${t("products.inCategory", { name: localizeCategory(categories.find((c) => c.slug === category) ?? { slug: category, name: category }, lang).name })}`}
          {search && ` ${t("products.forSearch", { query: search })}`}
        </p>
      )}

      {/* Grid */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 overflow-hidden animate-pulse">
              <div className="h-48 bg-gray-200" />
              <div className="p-4 space-y-2">
                <div className="h-4 bg-gray-200 rounded w-3/4" />
                <div className="h-3 bg-gray-200 rounded w-full" />
                <div className="h-3 bg-gray-200 rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-16 text-red-500">{error}</div>
      ) : products.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <svg className="w-16 h-16 mx-auto mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 0 1 5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
          </svg>
          <p className="font-medium">{t("products.noResults")}</p>
          <p className="text-sm mt-1">{t("products.noResultsHint")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {products.map((p) => (
            <ProductCard key={p.id} product={p} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 mt-8">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 rounded-lg border border-gray-300 text-sm disabled:opacity-40 hover:border-indigo-400 transition-colors"
          >
            {t("products.prev")}
          </button>
          <span className="px-4 py-2 text-sm text-gray-600">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 rounded-lg border border-gray-300 text-sm disabled:opacity-40 hover:border-indigo-400 transition-colors"
          >
            {t("products.next")}
          </button>
        </div>
      )}
    </div>
  );
}
