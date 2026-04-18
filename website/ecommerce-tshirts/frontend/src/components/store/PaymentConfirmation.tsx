import { formatCLP, setCartCount } from "@/lib/storeApi";
import { useEffect, useState } from "react";
import { useI18n } from "@/i18n/useI18n";

export default function PaymentConfirmation() {
  const [confirming, setConfirming] = useState(true);
  const [countdown, setCountdown] = useState(5);
  const [params, setParams] = useState({ orderId: "", orderNumber: "", status: "", txId: "", total: "0" });
  const { t, localePath } = useI18n();

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setParams({
      orderId:     p.get("order_id")     ?? "",
      orderNumber: p.get("order_number") ?? "",
      status:      p.get("status")       ?? "",
      txId:        p.get("tx")           ?? "",
      total:       p.get("total")        ?? "0",
    });
  }, []);

  useEffect(() => {
    if (countdown <= 0) { setConfirming(false); return; }
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  const { orderId, orderNumber, status, txId, total } = params;
  const approved = status === "approved";
  const totalNum = parseInt(total, 10) || 0;

  useEffect(() => {
    if (!confirming && approved) setCartCount(0);
  }, [confirming, approved]);

  // ── Loading screen ───────────────────────────────────────────
  if (confirming) {
    return (
      <div className="max-w-lg mx-auto text-center py-20">
        <div className="relative w-24 h-24 mx-auto mb-8">
          <svg className="w-24 h-24 -rotate-90" viewBox="0 0 96 96">
            <circle cx="48" cy="48" r="40" fill="none" stroke="#e5e7eb" strokeWidth="6" />
            <circle
              cx="48" cy="48" r="40" fill="none"
              stroke="#4f46e5" strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${(5 - countdown) * 50.3} 251.3`}
              className="transition-all duration-1000 ease-linear"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-2xl font-bold text-indigo-600">
            {countdown}
          </span>
        </div>

        <h1 className="text-2xl font-bold text-gray-800 mb-3">{t("confirm.confirming")}</h1>
        <p className="text-gray-500 text-sm">{t("confirm.verifying")}</p>

        <div className="flex justify-center gap-1.5 mt-6">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-2 h-2 rounded-full bg-indigo-400"
              style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
            />
          ))}
        </div>

        <style>{`
          @keyframes bounce {
            0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
            40% { transform: translateY(-8px); opacity: 1; }
          }
        `}</style>
      </div>
    );
  }

  // ── Result screen ────────────────────────────────────────────
  return (
    <div className="max-w-lg mx-auto text-center py-10">
      <div className={`w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 ${
        approved ? "bg-green-100" : "bg-red-100"
      }`}>
        {approved ? (
          <svg className="w-12 h-12 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="w-12 h-12 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        )}
      </div>

      <h1 className={`text-2xl font-bold mb-2 ${approved ? "text-green-700" : "text-red-700"}`}>
        {approved ? t("confirm.approved") : t("confirm.rejected")}
      </h1>

      <p className="text-gray-500 mb-8">
        {approved ? t("confirm.approvedDesc") : t("confirm.rejectedDesc")}
      </p>

      {/* Order details */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 text-left space-y-3 mb-8">
        <h2 className="font-semibold text-gray-900 border-b border-gray-100 pb-2 mb-3">{t("confirm.orderDetails")}</h2>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">{t("confirm.orderNumber")}</span>
          <span className="font-mono font-semibold text-gray-900">{orderNumber}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">{t("confirm.txId")}</span>
          <span className="font-mono text-xs text-gray-700 break-all">{txId || "—"}</span>
        </div>
        {totalNum > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">{t("confirm.totalCharged")}</span>
            <span className="font-bold text-indigo-600">{formatCLP(totalNum)}</span>
          </div>
        )}
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">{t("confirm.status")}</span>
          <span className={`font-semibold px-2 py-0.5 rounded-full text-xs ${
            approved ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
          }`}>
            {approved ? t("confirm.approvedStatus") : t("confirm.rejectedStatus")}
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-col sm:flex-row gap-3 justify-center">
        {approved ? (
          <>
            <a
              href={localePath("/mi-cuenta/pedidos")}
              className="bg-indigo-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors"
            >
              {t("confirm.viewOrders")}
            </a>
            <a
              href={localePath("/productos")}
              className="border border-gray-300 text-gray-700 px-6 py-3 rounded-lg font-semibold hover:border-gray-400 transition-colors"
            >
              {t("confirm.continueShopping")}
            </a>
          </>
        ) : (
          <>
            <a
              href={localePath("/checkout")}
              className="bg-red-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-red-700 transition-colors"
            >
              {t("confirm.tryAgain")}
            </a>
            <a
              href={localePath("/carrito")}
              className="border border-gray-300 text-gray-700 px-6 py-3 rounded-lg font-semibold hover:border-gray-400 transition-colors"
            >
              {t("confirm.backToCart")}
            </a>
          </>
        )}
      </div>

      {/* Observability link */}
      <div className="mt-10 p-4 bg-gray-50 rounded-xl border border-gray-200 text-sm">
        <p className="text-gray-500 mb-2">{t("confirm.grafanaNote")}</p>
        <a
          href="http://localhost:3000/explore"
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-600 hover:text-indigo-800 font-medium"
        >
          Tempo Traces → order_id: {orderId}
        </a>
      </div>
    </div>
  );
}
