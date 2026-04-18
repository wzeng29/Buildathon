import { useState, useEffect } from "react";
import { ordersApi, formatCLP, STATUS_COLORS, getUser } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";

export default function MyOrders() {
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const { t, lang, localePath } = useI18n();

  useEffect(() => {
    const user = getUser();
    if (!user) {
      window.location.href = localePath("/mi-cuenta") + "?redirect=" + localePath("/mi-cuenta/pedidos");
      return;
    }
    ordersApi.list()
      .then((r) => setOrders(r.data ?? []))
      .catch((e: any) => {
        if (e.status === 401) window.location.href = localePath("/mi-cuenta");
        else setError(t("orders.errorLoad"));
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-3 animate-pulse">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex justify-between">
              <div className="space-y-2 w-1/2">
                <div className="h-4 bg-gray-200 rounded w-32" />
                <div className="h-3 bg-gray-200 rounded w-24" />
              </div>
              <div className="h-6 bg-gray-200 rounded w-20" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return <div className="text-center py-10 text-red-500">{error}</div>;
  }

  if (orders.length === 0) {
    return (
      <div className="text-center py-20">
        <svg className="w-16 h-16 mx-auto mb-4 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" />
        </svg>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">{t("orders.empty")}</h2>
        <p className="text-gray-500 mb-6">{t("orders.emptyDesc")}</p>
        <a href={localePath("/productos")} className="bg-indigo-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors">
          {t("orders.viewProducts")}
        </a>
      </div>
    );
  }

  const dateLocale = lang === "es" ? "es-CL" : "en-US";

  return (
    <div className="space-y-3">
      {orders.map((order) => (
        <div key={order.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <button
            onClick={() => setExpanded(expanded === order.id ? null : order.id)}
            className="w-full flex items-center justify-between p-5 hover:bg-gray-50 transition-colors text-left"
          >
            <div className="flex items-center gap-4">
              <div>
                <p className="font-semibold text-gray-900 font-mono">{order.order_number}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {new Date(order.created_at).toLocaleDateString(dateLocale, {
                    year: "numeric", month: "long", day: "numeric"
                  })}
                </p>
              </div>
              <span className={`text-xs font-medium px-2 py-1 rounded-full ${STATUS_COLORS[order.status] ?? "bg-gray-100 text-gray-600"}`}>
                {t("status." + order.status) || order.status}
              </span>
            </div>

            <div className="flex items-center gap-4">
              <div className="text-right">
                <p className="font-bold text-indigo-600">{formatCLP(order.total)}</p>
                <p className="text-xs text-gray-400">{order.items_count ?? "?"} {t("orders.items")}</p>
              </div>
              <svg
                className={`w-5 h-5 text-gray-400 transition-transform ${expanded === order.id ? "rotate-180" : ""}`}
                fill="none" stroke="currentColor" viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </button>

          {expanded === order.id && (
            <div className="border-t border-gray-100 px-5 pb-5">
              <OrderDetail orderId={order.id} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function OrderDetail({ orderId }: { orderId: number }) {
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const { t } = useI18n();

  useEffect(() => {
    ordersApi.get(orderId)
      .then((r) => setDetail(r.data))
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return <div className="py-4 text-sm text-gray-400 animate-pulse">{t("orders.loadingDetail")}</div>;
  }

  if (!detail) return null;

  return (
    <div className="pt-4 space-y-4">
      <div className="space-y-2">
        {detail.items?.map((item: any) => (
          <div key={item.id} className="flex items-center gap-3 text-sm">
            <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-indigo-300" fill="currentColor" viewBox="0 0 24 24">
                <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
              </svg>
            </div>
            <div className="flex-1">
              <p className="font-medium text-gray-800">{item.product_name}</p>
              <p className="text-xs text-gray-500">{item.size} · {item.color} × {item.quantity}</p>
            </div>
            <span className="font-medium text-gray-700">{formatCLP(item.subtotal)}</span>
          </div>
        ))}
      </div>

      <div className="border-t border-gray-100 pt-3 space-y-1 text-sm">
        <div className="flex justify-between text-gray-500">
          <span>{t("orders.subtotal")}</span><span>{formatCLP(detail.subtotal)}</span>
        </div>
        {detail.tax > 0 && (
          <div className="flex justify-between text-gray-500">
            <span>{t("orders.tax")}</span><span>{formatCLP(detail.tax)}</span>
          </div>
        )}
        <div className="flex justify-between text-gray-500">
          <span>{t("orders.shipping")}</span>
          <span className={detail.shipping_cost === 0 ? "text-green-600" : ""}>
            {detail.shipping_cost === 0 ? t("orders.free") : formatCLP(detail.shipping_cost)}
          </span>
        </div>
        <div className="flex justify-between font-bold text-gray-900 pt-1 border-t border-gray-100">
          <span>{t("orders.total")}</span><span className="text-indigo-600">{formatCLP(detail.total)}</span>
        </div>
      </div>

      {detail.shipping_address && (
        <div className="bg-gray-50 rounded-lg p-3 text-xs text-gray-600">
          <p className="font-medium text-gray-700 mb-1">{t("orders.shippingAddress")}</p>
          <p>{detail.shipping_address.street}, {detail.shipping_address.city}</p>
          <p>{detail.shipping_address.region} {detail.shipping_address.zip}</p>
        </div>
      )}
    </div>
  );
}
