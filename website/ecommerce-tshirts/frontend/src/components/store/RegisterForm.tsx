import { useState } from "react";
import { authApi, saveAuth } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";

interface Props {
  redirect?: string;
  onSwitchToLogin: () => void;
}

export default function RegisterForm({ redirect = "/", onSwitchToLogin }: Props) {
  const [form, setForm] = useState({ firstname: "", lastname: "", email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { t } = useI18n();

  const set = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.password.length < 6) {
      setError(t("auth.passwordMin"));
      return;
    }
    setError("");
    setLoading(true);
    try {
      const res = await authApi.register(form.firstname, form.lastname, form.email, form.password);
      saveAuth(res.data.token, res.data.user);
      window.location.href = redirect;
    } catch (e: any) {
      setError(e.message ?? t("auth.errorRegister"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t("auth.firstName")}</label>
          <input
            type="text"
            value={form.firstname}
            onChange={set("firstname")}
            placeholder="Juan"
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t("auth.lastName")}</label>
          <input
            type="text"
            value={form.lastname}
            onChange={set("lastname")}
            placeholder="Pérez"
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">{t("auth.email")}</label>
        <input
          type="email"
          autoComplete="email"
          value={form.email}
          onChange={set("email")}
          placeholder="tu@email.com"
          required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">{t("auth.password")}</label>
        <input
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={set("password")}
          placeholder="••••••••"
          minLength={6}
          required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <p className="text-xs text-gray-400 mt-1">{t("auth.passwordHint")}</p>
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-indigo-600 text-white py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors disabled:opacity-60"
      >
        {loading ? t("auth.creating") : t("auth.createBtn")}
      </button>

      <p className="text-center text-sm text-gray-500">
        {t("auth.hasAccount")}{" "}
        <button type="button" onClick={onSwitchToLogin} className="text-indigo-600 font-medium hover:underline">
          {t("auth.signIn")}
        </button>
      </p>
    </form>
  );
}
