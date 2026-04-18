/**
 * Frontend content translations for dynamic data that comes from the API.
 * The database stores everything in Spanish; this file provides English equivalents
 * keyed by the stable slug / Spanish name.
 */

// ── Categories ───────────────────────────────────────────────────────────────

export const categoryNames: Record<string, string> = {
  basica:    "Basic",
  oversize:  "Oversize",
  estampada: "Printed",
  premium:   "Premium",
  deportiva: "Sports",
};

// ── Colors ───────────────────────────────────────────────────────────────────

export const colorNames: Record<string, string> = {
  "Blanco":      "White",
  "Negro":       "Black",
  "Gris":        "Grey",
  "Azul Marino": "Navy Blue",
  "Verde Oliva": "Olive Green",
  "Sage Green":  "Sage Green",
  "Camel":       "Camel",
  "Lavanda":     "Lavender",
  "Beige":       "Beige",
  "Lila":        "Lilac",
  "Verde Neón":  "Neon Green",
  "Azul":        "Blue",
};

// ── Products (keyed by slug) ──────────────────────────────────────────────────

interface ProductTranslation {
  name: string;
  description: string;
}

export const productContent: Record<string, ProductTranslation> = {
  "polera-basica-blanca": {
    name: "White Basic Tee",
    description: "100% combed cotton, classic straight cut. Perfect for everyday wear.",
  },
  "polera-basica-negra": {
    name: "Black Basic Tee",
    description: "100% combed cotton black tee — a wardrobe essential you can never go wrong with.",
  },
  "polera-basica-gris": {
    name: "Grey Basic Tee",
    description: "Heathered grey cotton tee, versatile and comfortable for daily use.",
  },
  "polera-basica-azul-marino": {
    name: "Navy Blue Basic Tee",
    description: "Navy blue cotton tee, elegant and classic for any occasion.",
  },
  "polera-basica-verde-oliva": {
    name: "Olive Green Basic Tee",
    description: "Olive green cotton tee — an on-trend earthy tone for this season.",
  },
  "oversize-urban-negro": {
    name: "Urban Oversize Black",
    description: "Urban-cut oversize tee, perfect for a modern streetwear look.",
  },
  "oversize-urban-blanco": {
    name: "Urban Oversize White",
    description: "White oversize tee — the streetwear basic you can't go without.",
  },
  "oversize-sage-green": {
    name: "Oversize Sage Green",
    description: "Oversize tee in sage green, a rising trend in sustainable fashion.",
  },
  "oversize-camel": {
    name: "Oversize Camel",
    description: "Camel-toned oversize tee, sophisticated and versatile for any style.",
  },
  "oversize-lavanda": {
    name: "Oversize Lavender",
    description: "Pastel lavender oversize tee — cool, fresh, and right on trend.",
  },
  "estampada-mountains": {
    name: "Mountains Print Tee",
    description: "Tee with a minimalist mountain print, made for outdoor lovers.",
  },
  "estampada-geometric": {
    name: "Geometric Print Tee",
    description: "Tee with an abstract geometric design in neutral tones.",
  },
  "estampada-sunset": {
    name: "Sunset Print Tee",
    description: "Vibrant sunset print tee with unique warm color palette.",
  },
  "estampada-botanica": {
    name: "Botanical Print Tee",
    description: "Delicate botanical print tee — perfect for summer.",
  },
  "estampada-retro-wave": {
    name: "Retro Wave Print Tee",
    description: "80s-inspired retro design tee with neon colors on a dark background.",
  },
  "premium-pima-blanca": {
    name: "Premium Pima Cotton White",
    description: "100% Peruvian Pima cotton tee — exceptional softness and superior durability.",
  },
  "premium-pima-negra": {
    name: "Premium Pima Cotton Black",
    description: "Black Pima cotton tee — accessible luxury for everyday wear.",
  },
  "premium-linen-blend": {
    name: "Premium Linen Blend",
    description: "Linen-cotton blend tee, lightweight and breathable for summer.",
  },
  "premium-bamboo-gris": {
    name: "Premium Bamboo Grey",
    description: "Eco-friendly bamboo fiber tee — soft, sustainable, and temperature-regulating.",
  },
  "premium-modal-negra": {
    name: "Premium Modal Black",
    description: "Modal tee made from natural fibers with a perfect drape and silky touch.",
  },
  "deportiva-dry-fit-blanca": {
    name: "Dry-Fit Sports White",
    description: "Sports tee with Dry-Fit technology — absorbs moisture and dries rapidly.",
  },
  "deportiva-dry-fit-negra": {
    name: "Dry-Fit Sports Black",
    description: "Black Dry-Fit sports tee — ideal for running, the gym, or any sport.",
  },
  "deportiva-compresion-azul": {
    name: "Blue Compression Sports Tee",
    description: "Blue compression tee — enhances performance and muscle recovery.",
  },
  "deportiva-trail-verde": {
    name: "Trail Running Green",
    description: "Trail running tee in neon green, ultra-light with UV 50+ protection.",
  },
  "deportiva-yoga-lila": {
    name: "Yoga Lilac Sports Tee",
    description: "Yoga and pilates tee in lilac with soft 4-way stretch fabric.",
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Returns the localized version of a product object.
 * When lang is "es" the original API values are returned unchanged.
 */
export function localizeProduct<T extends { slug?: string; name?: string; description?: string; category_name?: string; category_slug?: string }>(
  product: T,
  lang: "en" | "es",
): T {
  if (lang === "es") return product;
  const t = product.slug ? productContent[product.slug] : undefined;
  return {
    ...product,
    name:          t?.name        ?? product.name,
    description:   t?.description ?? product.description,
    category_name: product.category_slug
      ? (categoryNames[product.category_slug] ?? product.category_name)
      : product.category_name,
  };
}

/**
 * Returns the localized category name.
 */
export function localizeCategory<T extends { slug?: string; name?: string }>(
  category: T,
  lang: "en" | "es",
): T {
  if (lang === "es") return category;
  return {
    ...category,
    name: category.slug ? (categoryNames[category.slug] ?? category.name) : category.name,
  };
}

/**
 * Returns the localized color name.
 */
export function localizeColor(color: string, lang: "en" | "es"): string {
  if (lang === "es") return color;
  return colorNames[color] ?? color;
}
