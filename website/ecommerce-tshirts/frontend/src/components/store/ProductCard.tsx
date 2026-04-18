import { formatCLP } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";
import { localizeProduct } from "@/i18n/productContent";

interface Props {
  product: {
    slug: string;
    name: string;
    description: string;
    base_price: number;
    category_name: string;
    image_url?: string;
    variants?: Array<{ stock: number }>;
  };
}

const SHIRT_COLORS = [
  "bg-slate-800", "bg-indigo-500", "bg-red-500",
  "bg-emerald-500", "bg-amber-400", "bg-pink-400",
];

function hashColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % SHIRT_COLORS.length;
  return SHIRT_COLORS[h];
}

export default function ProductCard({ product }: Props) {
  const { t, lang, localePath } = useI18n();
  const p = localizeProduct(product, lang);
  const inStock = !p.variants || p.variants.some((v) => v.stock > 0);
  const colorClass = hashColor(p.name);

  return (
    <a
      href={`${localePath("/productos/detalle")}?producto=${product.slug}`}
      className="group block bg-white rounded-xl overflow-hidden border border-gray-200 hover:border-indigo-300 hover:shadow-lg transition-all duration-200"
    >
      {/* Image placeholder */}
      <div className={`${colorClass} h-48 flex items-center justify-center relative overflow-hidden`}>
        <svg className="w-24 h-24 text-white/30" fill="currentColor" viewBox="0 0 24 24">
          <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
        </svg>
        <div className="absolute top-2 left-2">
          <span className="bg-white/90 text-gray-700 text-xs font-medium px-2 py-0.5 rounded-full">
            {p.category_name}
          </span>
        </div>
        {!inStock && (
          <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
            <span className="bg-white text-gray-800 text-sm font-semibold px-3 py-1 rounded-full">
              {t("productCard.outOfStock")}
            </span>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-4">
        <h3 className="font-semibold text-gray-900 group-hover:text-indigo-600 transition-colors line-clamp-1">
          {p.name}
        </h3>
        <p className="text-gray-500 text-sm mt-1 line-clamp-2">{p.description}</p>
        <div className="flex items-center justify-between mt-3">
          <span className="text-lg font-bold text-indigo-600">{formatCLP(product.base_price)}</span>
          <span className="text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded-full">
            {t("productCard.viewDetail")}
          </span>
        </div>
      </div>
    </a>
  );
}
