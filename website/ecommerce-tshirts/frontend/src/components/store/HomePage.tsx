import { useState, useEffect } from "react";
import { productsApi, formatCLP } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";
import { localizeCategory } from "@/i18n/productContent";
import ProductCard from "./ProductCard";

export default function HomePage() {
  const [featured, setFeatured] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { t, lang, localePath } = useI18n();

  useEffect(() => {
    Promise.all([
      productsApi.list("?limit=8"),
      productsApi.categories(),
    ]).then(([prodRes, catRes]) => {
      setFeatured(prodRes.data ?? []);
      setCategories(catRes.data ?? []);
    }).finally(() => setLoading(false));
  }, []);

  const CATEGORY_COLORS = [
    "from-slate-700 to-slate-900",
    "from-indigo-500 to-purple-700",
    "from-rose-500 to-pink-700",
    "from-emerald-500 to-teal-700",
    "from-amber-400 to-orange-600",
  ];

  return (
    <div>
      {/* Hero */}
      <section className="relative bg-gradient-to-br from-indigo-600 via-purple-600 to-pink-500 text-white overflow-hidden">
        <div className="absolute inset-0 opacity-10">
          {Array.from({ length: 12 }).map((_, i) => (
            <svg
              key={i}
              className="absolute"
              style={{ top: `${(i * 17) % 90}%`, left: `${(i * 23) % 90}%`, opacity: 0.5 }}
              width="60" height="60" fill="currentColor" viewBox="0 0 24 24"
            >
              <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
            </svg>
          ))}
        </div>
        <div className="container mx-auto px-4 py-20 relative z-10 text-center">
          <div className="inline-block bg-white/20 backdrop-blur-sm text-white text-sm font-medium px-4 py-1.5 rounded-full mb-6">
            {t("home.badge")}
          </div>
          <h1 className="text-4xl md:text-6xl font-bold mb-4">
            {t("home.heroTitle1")}<br />{t("home.heroTitle2")}
          </h1>
          <p className="text-lg text-white/80 max-w-xl mx-auto mb-8">
            {t("home.heroDesc")}
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <a
              href={localePath("/productos")}
              className="bg-white text-indigo-700 px-8 py-3 rounded-xl font-semibold hover:bg-indigo-50 transition-colors shadow-lg"
            >
              {t("home.viewCatalog")}
            </a>
            <a
              href={localePath("/productos") + "?categoria=oversize"}
              className="border-2 border-white/60 text-white px-8 py-3 rounded-xl font-semibold hover:bg-white/10 transition-colors"
            >
              {t("nav.oversize")} Collection →
            </a>
          </div>
        </div>
      </section>

      {/* Categories */}
      <section className="container mx-auto px-4 py-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-6">{t("home.categories")}</h2>
        {loading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-24 bg-gray-200 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {categories.map((cat, i) => (
              <a
                key={cat.id}
                href={`${localePath("/productos")}?categoria=${encodeURIComponent(cat.slug)}`}
                className={`bg-gradient-to-br ${CATEGORY_COLORS[i % CATEGORY_COLORS.length]} text-white rounded-xl p-4 flex flex-col items-center justify-center h-24 hover:scale-105 transition-transform shadow-sm`}
              >
                <span className="font-semibold text-sm text-center">{localizeCategory(cat, lang).name}</span>
                <span className="text-white/70 text-xs mt-1">{t("home.viewAll")}</span>
              </a>
            ))}
          </div>
        )}
      </section>

      {/* Featured products */}
      <section className="container mx-auto px-4 py-4 pb-12">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-900">{t("home.featuredProducts")}</h2>
          <a href={localePath("/productos")} className="text-indigo-600 text-sm font-medium hover:underline">
            {t("home.viewAllProducts")}
          </a>
        </div>
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="bg-white rounded-xl border border-gray-200 overflow-hidden animate-pulse">
                <div className="h-48 bg-gray-200" />
                <div className="p-4 space-y-2">
                  <div className="h-4 bg-gray-200 rounded w-3/4" />
                  <div className="h-3 bg-gray-200 rounded" />
                  <div className="h-6 bg-gray-200 rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {featured.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        )}
      </section>

      {/* Value props */}
      <section className="bg-indigo-50 border-y border-indigo-100 py-10">
        <div className="container mx-auto px-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 text-center">
            {[
              { icon: "🚚", titleKey: "home.freeShipping", descKey: "home.freeShippingDesc" },
              { icon: "↩️", titleKey: "home.returns",      descKey: "home.returnsDesc" },
              { icon: "🛡️", titleKey: "home.securePay",    descKey: "home.securePayDesc" },
            ].map((item) => (
              <div key={item.titleKey} className="flex flex-col items-center gap-2">
                <span className="text-3xl">{item.icon}</span>
                <h3 className="font-semibold text-gray-900">{t(item.titleKey)}</h3>
                <p className="text-gray-500 text-sm">{t(item.descKey)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
