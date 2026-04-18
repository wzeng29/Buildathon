import { useState, useEffect } from "react";
import { cartApi, formatCLP, getUser, setCartCount } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";

export default function CartView() {
  const [cart, setCart] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updating, setUpdating] = useState<number | null>(null);
  const { t, localePath } = useI18n();

  const fetchCart = async () => {
    try {
      const r = await cartApi.get();
      setCart(r.data);
      setCartCount(r.data?.items?.length ?? 0);
    } catch (e: any) {
      if (e.status === 401) {
        window.location.href = localePath("/mi-cuenta") + "?redirect=" + localePath("/carrito");
      } else {
        setError(t("cart.errorLoad"));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const user = getUser();
    if (!user) {
      window.location.href = localePath("/mi-cuenta") + "?redirect=" + localePath("/carrito");
      return;
    }
    fetchCart();
  }, []);

  const handleUpdate = async (itemId: number, qty: number) => {
    setUpdating(itemId);
    try {
      if (qty <= 0) {
        await cartApi.remove(itemId);
      } else {
        await cartApi.update(itemId, qty);
      }
      await fetchCart();
    } catch (e: any) {
      alert(e.message ?? t("cart.errorUpdate"));
    } finally {
      setUpdating(null);
    }
  };

  const handleClear = async () => {
    if (!confirm(t("cart.confirmClear"))) return;
    try {
      await cartApi.clear();
      await fetchCart();
    } catch {}
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto">
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 flex gap-4">
              <div className="w-20 h-20 bg-gray-200 rounded-lg" />
              <div className="flex-1 space-y-2">
                <div className="h-4 bg-gray-200 rounded w-1/2" />
                <div className="h-3 bg-gray-200 rounded w-1/3" />
                <div className="h-4 bg-gray-200 rounded w-1/4" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="text-center py-16 text-red-500">{error}</div>;
  }

  const items = cart?.items ?? [];

  if (items.length === 0) {
    return (
      <div className="text-center py-20">
        <svg className="w-20 h-20 mx-auto mb-4 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm-8 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4z" />
        </svg>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">{t("cart.empty")}</h2>
        <p className="text-gray-500 mb-6">{t("cart.emptyDesc")}</p>
        <a href={localePath("/productos")} className="bg-indigo-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors">
          {t("cart.viewProducts")}
        </a>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Items */}
      <div className="lg:col-span-2 space-y-3">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            {items.length} {items.length === 1 ? t("cart.item") : t("cart.items")}
          </h2>
          <button onClick={handleClear} className="text-sm text-red-500 hover:text-red-700 transition-colors">
            {t("cart.clear")}
          </button>
        </div>

        {items.map((item: any) => (
          <div key={item.id} className="bg-white rounded-xl border border-gray-200 p-4 flex gap-4 items-center">
            <div className="w-16 h-16 bg-indigo-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <svg className="w-8 h-8 text-indigo-300" fill="currentColor" viewBox="0 0 24 24">
                <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
              </svg>
            </div>

            <div className="flex-1 min-w-0">
              <a href={`${localePath("/productos/detalle")}?producto=${item.product_slug}`} className="font-medium text-gray-900 hover:text-indigo-600 transition-colors truncate block">
                {item.product_name}
              </a>
              <p className="text-sm text-gray-500">{item.variant_description}</p>
              <p className="text-sm font-semibold text-indigo-600 mt-1">{formatCLP(parseFloat(item.unit_price))}</p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center border border-gray-300 rounded-lg overflow-hidden">
                <button
                  onClick={() => handleUpdate(item.id, item.quantity - 1)}
                  disabled={updating === item.id}
                  className="px-2 py-1 text-gray-600 hover:bg-gray-100 transition-colors text-sm disabled:opacity-40"
                >
                  −
                </button>
                <span className="px-2 py-1 text-sm font-medium min-w-[1.5rem] text-center">
                  {updating === item.id ? "…" : item.quantity}
                </span>
                <button
                  onClick={() => handleUpdate(item.id, item.quantity + 1)}
                  disabled={updating === item.id}
                  className="px-2 py-1 text-gray-600 hover:bg-gray-100 transition-colors text-sm disabled:opacity-40"
                >
                  +
                </button>
              </div>
              <button
                onClick={() => handleUpdate(item.id, 0)}
                disabled={updating === item.id}
                className="p-1 text-gray-400 hover:text-red-500 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="text-right text-sm font-bold text-gray-900 min-w-[4rem]">
              {formatCLP(parseFloat(item.unit_price) * item.quantity)}
            </div>
          </div>
        ))}
      </div>

      {/* Summary */}
      <div className="lg:col-span-1">
        <div className="bg-white rounded-xl border border-gray-200 p-5 sticky top-20">
          <h3 className="font-semibold text-gray-900 mb-4">{t("cart.summary")}</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between text-gray-600">
              <span>{t("cart.subtotal")}</span>
              <span>{formatCLP(cart.subtotal ?? cart.total)}</span>
            </div>
            <div className="flex justify-between text-gray-600">
              <span>{t("cart.shipping")}</span>
              <span className="text-green-600">{t("cart.free")}</span>
            </div>
          </div>
          <div className="border-t border-gray-200 mt-4 pt-4">
            <div className="flex justify-between font-bold text-gray-900">
              <span>{t("cart.total")}</span>
              <span className="text-indigo-600">{formatCLP(cart.total)}</span>
            </div>
          </div>
          <a
            href={localePath("/checkout")}
            className="mt-5 w-full block text-center bg-indigo-600 text-white py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors"
          >
            {t("cart.checkout")}
          </a>
          <a href={localePath("/productos")} className="mt-3 w-full block text-center text-sm text-gray-500 hover:text-indigo-600 transition-colors">
            {t("cart.continue")}
          </a>
        </div>
      </div>
    </div>
  );
}
