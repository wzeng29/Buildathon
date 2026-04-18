import { useState, useEffect } from "react";
import { productsApi, cartApi, formatCLP, getUser, setCartCount, getCartCount } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";
import { localizeProduct, localizeColor } from "@/i18n/productContent";

export default function ProductDetail() {
  const slug = typeof window !== "undefined"
    ? new URLSearchParams(window.location.search).get("producto") ?? ""
    : "";
  const [product, setProduct] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedSize, setSelectedSize] = useState("");
  const [selectedColor, setSelectedColor] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [adding, setAdding] = useState(false);
  const [addedMsg, setAddedMsg] = useState("");
  const { t, lang, localePath } = useI18n();

  useEffect(() => {
    productsApi.get(slug)
      .then((r) => {
        setProduct(r.data);
        const first = r.data?.variants?.[0];
        if (first) {
          setSelectedSize(first.size);
          setSelectedColor(first.color);
        }
      })
      .catch(() => setError(t("detail.notFound")))
      .finally(() => setLoading(false));
  }, [slug]);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto animate-pulse grid grid-cols-1 md:grid-cols-2 gap-10">
        <div className="bg-gray-200 rounded-2xl h-96" />
        <div className="space-y-4">
          <div className="h-8 bg-gray-200 rounded w-2/3" />
          <div className="h-4 bg-gray-200 rounded w-full" />
          <div className="h-4 bg-gray-200 rounded w-3/4" />
        </div>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="text-center py-16">
        <p className="text-red-500 font-medium">{error || t("detail.notFound")}</p>
        <a href={localePath("/productos")} className="mt-4 inline-block text-indigo-600 hover:underline">
          {t("detail.backToProducts")}
        </a>
      </div>
    );
  }

  const lp = localizeProduct(
    { ...product, slug: product.slug, category_slug: product.category?.slug ?? product.category_slug },
    lang,
  );
  const sizes = [...new Set<string>(product.variants.map((v: any) => v.size))];
  const colors = [...new Set<string>(
    product.variants
      .filter((v: any) => v.size === selectedSize)
      .map((v: any) => v.color)
  )];

  const selectedVariant = product.variants.find(
    (v: any) => v.size === selectedSize && v.color === selectedColor
  );

  const maxQty = selectedVariant?.stock ?? 0;

  const handleAddToCart = async () => {
    const user = getUser();
    if (!user) {
      window.location.href = localePath("/mi-cuenta") + "?redirect=" + localePath("/productos/detalle") + "?producto=" + slug;
      return;
    }
    if (!selectedVariant) return;

    setAdding(true);
    try {
      await cartApi.add(selectedVariant.id, quantity);
      const newCount = getCartCount() + quantity;
      setCartCount(newCount);
      setAddedMsg(t("detail.added"));
      setTimeout(() => setAddedMsg(""), 3000);
    } catch (e: any) {
      setAddedMsg(e.message ?? t("detail.added"));
      setTimeout(() => setAddedMsg(""), 3000);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto">
      <nav className="text-sm text-gray-500 mb-6 flex items-center gap-2">
        <a href={localePath("/")} className="hover:text-indigo-600">{t("detail.home")}</a>
        <span>/</span>
        <a href={localePath("/productos")} className="hover:text-indigo-600">{t("detail.products")}</a>
        <span>/</span>
        <span className="text-gray-900">{product.name}</span>
      </nav>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
        {/* Image */}
        <div className="bg-gradient-to-br from-indigo-100 to-purple-100 rounded-2xl flex items-center justify-center h-96 md:h-auto">
          <svg className="w-40 h-40 text-indigo-300" fill="currentColor" viewBox="0 0 24 24">
            <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
          </svg>
        </div>

        {/* Details */}
        <div className="space-y-5">
          <div>
            <span className="text-sm text-indigo-600 font-medium bg-indigo-50 px-2 py-1 rounded-full">
              {lp.category_name}
            </span>
            <h1 className="text-2xl font-bold text-gray-900 mt-2">{lp.name}</h1>
            <p className="text-gray-600 mt-2">{lp.description}</p>
          </div>

          <div className="text-3xl font-bold text-indigo-600">{formatCLP(product.base_price)}</div>

          {/* Size selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t("detail.size")}</label>
            <div className="flex flex-wrap gap-2">
              {sizes.map((size: string) => (
                <button
                  key={size}
                  onClick={() => {
                    setSelectedSize(size);
                    const firstColor = product.variants.find((v: any) => v.size === size)?.color;
                    if (firstColor) setSelectedColor(firstColor);
                  }}
                  className={`w-12 h-12 rounded-lg border-2 text-sm font-semibold transition-colors ${
                    selectedSize === size
                      ? "border-indigo-600 bg-indigo-600 text-white"
                      : "border-gray-300 text-gray-700 hover:border-indigo-400"
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          {/* Color selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t("detail.color")}: <span className="font-normal text-gray-500">{localizeColor(selectedColor, lang)}</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {colors.map((color: string) => {
                const variant = product.variants.find((v: any) => v.size === selectedSize && v.color === color);
                return (
                  <button
                    key={color}
                    onClick={() => setSelectedColor(color)}
                    disabled={!variant || variant.stock === 0}
                    title={localizeColor(color, lang)}
                    className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
                      selectedColor === color
                        ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                        : "border-gray-300 text-gray-600 hover:border-gray-400"
                    } disabled:opacity-40 disabled:cursor-not-allowed`}
                  >
                    {localizeColor(color, lang)}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Stock */}
          {selectedVariant && (
            <p className={`text-sm font-medium ${maxQty > 5 ? "text-green-600" : maxQty > 0 ? "text-amber-600" : "text-red-600"}`}>
              {maxQty > 5
                ? t("detail.inStock", { n: maxQty })
                : maxQty > 0
                ? t("detail.lowStock", { n: maxQty })
                : t("detail.noStock")}
            </p>
          )}

          {/* Quantity + Add to cart */}
          <div className="flex items-center gap-3">
            <div className="flex items-center border border-gray-300 rounded-lg overflow-hidden">
              <button
                onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                className="px-3 py-2 text-gray-600 hover:bg-gray-100 transition-colors"
              >
                −
              </button>
              <span className="px-4 py-2 text-sm font-medium min-w-[2rem] text-center">{quantity}</span>
              <button
                onClick={() => setQuantity((q) => Math.min(maxQty, q + 1))}
                disabled={quantity >= maxQty}
                className="px-3 py-2 text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40"
              >
                +
              </button>
            </div>
            <button
              onClick={handleAddToCart}
              disabled={adding || maxQty === 0 || !selectedVariant}
              className="flex-1 bg-indigo-600 text-white py-3 px-6 rounded-lg font-semibold hover:bg-indigo-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {adding
                ? t("detail.adding")
                : maxQty === 0
                ? t("detail.outOfStock")
                : t("detail.addToCart")}
            </button>
          </div>

          {addedMsg && (
            <div className={`text-sm font-medium px-4 py-2 rounded-lg ${
              addedMsg.includes("!") || addedMsg.includes("Added") ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
            }`}>
              {addedMsg}
            </div>
          )}

          {/* SKU */}
          {selectedVariant && (
            <p className="text-xs text-gray-400">SKU: {selectedVariant.sku}</p>
          )}
        </div>
      </div>
    </div>
  );
}
