import { useState, useEffect } from "react";
import { cartApi, ordersApi, paymentsApi, formatCLP, getUser } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";

export default function CheckoutForm() {
  const [cart, setCart] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState<"shipping" | "payment">("shipping");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const { t, localePath } = useI18n();

  const [shipping, setShipping] = useState({
    street: "", city: "Santiago", region: "RM", zip: "",
  });

  const [payMethod, setPayMethod] = useState("credit_card");
  const [cardNumber, setCardNumber] = useState("");

  useEffect(() => {
    const user = getUser();
    if (!user) {
      window.location.href = localePath("/mi-cuenta") + "?redirect=" + localePath("/checkout");
      return;
    }
    cartApi.get()
      .then((r) => setCart(r.data))
      .catch(() => setError(t("checkout.errorLoad")))
      .finally(() => setLoading(false));
  }, []);

  const handleShippingSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!shipping.street || !shipping.city || !shipping.zip) {
      setError(t("checkout.errorShipping"));
      return;
    }
    setError("");
    setStep("payment");
  };

  const handlePayment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (payMethod !== "bank_transfer" && !cardNumber.trim()) {
      setError(t("checkout.errorCard"));
      return;
    }
    setError("");
    setSubmitting(true);

    try {
      const orderRes = await ordersApi.create(shipping);
      const orderId = orderRes.data?.id;
      const orderNumber = orderRes.data?.order_number;

      const payRes = await paymentsApi.process(orderId, payMethod, cardNumber || undefined);
      const payStatus = payRes.data?.status;
      const txId = payRes.data?.transaction_id;

      const params = new URLSearchParams({
        order_id: orderId,
        order_number: orderNumber,
        status: payStatus,
        tx: txId ?? "",
        total: cart?.total ?? 0,
      });
      window.location.href = localePath("/checkout/confirmacion") + "?" + params.toString();
    } catch (e: any) {
      setError(e.message ?? t("checkout.errorPayment"));
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-1/3" />
        <div className="h-40 bg-gray-200 rounded-xl" />
        <div className="h-40 bg-gray-200 rounded-xl" />
      </div>
    );
  }

  const items = cart?.items ?? [];

  if (items.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-gray-500">{t("checkout.emptyCart")}</p>
        <a href={localePath("/productos")} className="mt-4 inline-block text-indigo-600 hover:underline">
          {t("checkout.viewProducts")}
        </a>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8">
      {/* Form */}
      <div className="lg:col-span-2 space-y-6">
        {/* Steps indicator */}
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 text-sm font-medium ${step === "shipping" ? "text-indigo-600" : "text-green-600"}`}>
            <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step === "shipping" ? "bg-indigo-600 text-white" : "bg-green-500 text-white"}`}>
              {step === "shipping" ? "1" : "✓"}
            </span>
            {t("checkout.stepShipping")}
          </div>
          <div className={`flex-1 h-0.5 ${step === "payment" ? "bg-indigo-300" : "bg-gray-200"}`} />
          <div className={`flex items-center gap-2 text-sm font-medium ${step === "payment" ? "text-indigo-600" : "text-gray-400"}`}>
            <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step === "payment" ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-500"}`}>
              2
            </span>
            {t("checkout.stepPayment")}
          </div>
        </div>

        {/* Shipping form */}
        {step === "shipping" && (
          <form onSubmit={handleShippingSubmit} className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">{t("checkout.shippingAddress")}</h2>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("checkout.street")}</label>
              <input
                type="text"
                placeholder={t("checkout.streetPlaceholder")}
                value={shipping.street}
                onChange={(e) => setShipping({ ...shipping, street: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("checkout.city")}</label>
                <input
                  type="text"
                  value={shipping.city}
                  onChange={(e) => setShipping({ ...shipping, city: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("checkout.region")}</label>
                <select
                  value={shipping.region}
                  onChange={(e) => setShipping({ ...shipping, region: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="RM">Región Metropolitana</option>
                  <option value="V">Valparaíso</option>
                  <option value="VIII">Biobío</option>
                  <option value="IX">La Araucanía</option>
                  <option value="XIV">Los Ríos</option>
                  <option value="X">Los Lagos</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("checkout.zip")}</label>
              <input
                type="text"
                placeholder={t("checkout.zipPlaceholder")}
                value={shipping.zip}
                onChange={(e) => setShipping({ ...shipping, zip: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                required
              />
            </div>

            {error && <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</p>}

            <button type="submit" className="w-full bg-indigo-600 text-white py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors">
              {t("checkout.continuePayment")}
            </button>
          </form>
        )}

        {/* Payment form */}
        {step === "payment" && (
          <form onSubmit={handlePayment} className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
            <div className="flex items-center gap-3">
              <button type="button" onClick={() => setStep("shipping")} className="text-indigo-600 hover:text-indigo-800 text-sm">
                {t("checkout.editShipping")}
              </button>
              <h2 className="text-lg font-semibold text-gray-900">{t("checkout.paymentMethod")}</h2>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {[
                { id: "credit_card",   labelKey: "checkout.creditCard",   icon: "💳" },
                { id: "debit_card",    labelKey: "checkout.debitCard",    icon: "💰" },
                { id: "bank_transfer", labelKey: "checkout.bankTransfer", icon: "🏦" },
              ].map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setPayMethod(m.id)}
                  className={`p-3 rounded-lg border-2 text-center transition-colors ${
                    payMethod === m.id
                      ? "border-indigo-600 bg-indigo-50"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="text-2xl mb-1">{m.icon}</div>
                  <div className="text-xs font-medium text-gray-700">{t(m.labelKey)}</div>
                </button>
              ))}
            </div>

            {payMethod !== "bank_transfer" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("checkout.cardNumber")}</label>
                <input
                  type="text"
                  placeholder="4111 1111 1111 1234"
                  value={cardNumber}
                  onChange={(e) => setCardNumber(e.target.value)}
                  maxLength={19}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-xs text-gray-400 mt-1">{t("checkout.cardTip")}</p>
              </div>
            )}

            {payMethod === "bank_transfer" && (
              <div className="bg-blue-50 text-blue-700 text-sm p-3 rounded-lg">
                {t("checkout.bankInfo")}
              </div>
            )}

            {error && <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</p>}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-green-600 text-white py-3 rounded-lg font-semibold hover:bg-green-700 transition-colors disabled:opacity-60"
            >
              {submitting ? t("checkout.processing") : t("checkout.pay", { amount: formatCLP(cart?.total ?? 0) })}
            </button>
          </form>
        )}
      </div>

      {/* Order summary */}
      <div className="lg:col-span-1">
        <div className="bg-white rounded-xl border border-gray-200 p-5 sticky top-20">
          <h3 className="font-semibold text-gray-900 mb-4">{t("checkout.yourOrder")}</h3>
          <div className="space-y-3 max-h-60 overflow-y-auto">
            {items.map((item: any) => (
              <div key={item.id} className="flex gap-3 text-sm">
                <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <svg className="w-5 h-5 text-indigo-300" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
                  </svg>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-800 truncate">{item.product_name}</p>
                  <p className="text-gray-500 text-xs">{item.variant_description} × {item.quantity}</p>
                </div>
                <span className="font-medium text-gray-700">{formatCLP(parseFloat(item.unit_price) * item.quantity)}</span>
              </div>
            ))}
          </div>
          <div className="border-t border-gray-200 mt-4 pt-4 space-y-2 text-sm">
            <div className="flex justify-between text-gray-600">
              <span>{t("checkout.subtotal")}</span><span>{formatCLP(cart?.subtotal ?? cart?.total)}</span>
            </div>
            <div className="flex justify-between text-gray-600">
              <span>{t("checkout.shipping2")}</span><span className="text-green-600">{t("checkout.free")}</span>
            </div>
            <div className="flex justify-between font-bold text-gray-900 text-base pt-1 border-t border-gray-200">
              <span>{t("checkout.total")}</span>
              <span className="text-indigo-600">{formatCLP(cart?.total)}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
