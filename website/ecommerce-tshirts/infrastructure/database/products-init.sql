-- Products DB Schema for Poleras E-commerce

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    category_id INTEGER REFERENCES categories(id),
    base_price DECIMAL(10,2) NOT NULL,
    image_url VARCHAR(500),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_variants (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    size VARCHAR(5) NOT NULL CHECK (size IN ('XS','S','M','L','XL','XXL')),
    color VARCHAR(50) NOT NULL,
    color_hex VARCHAR(7) NOT NULL,
    sku VARCHAR(50) NOT NULL UNIQUE,
    stock INTEGER NOT NULL DEFAULT 0,
    price_override DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id);
CREATE INDEX IF NOT EXISTS idx_variants_sku ON product_variants(sku);

-- ==================== SEED DATA ====================

INSERT INTO categories (name, slug, description) VALUES
('Básica',     'basica',    'Poleras básicas de algodón peinado, ideales para el día a día'),
('Oversize',   'oversize',  'Poleras oversize estilo streetwear, corte holgado y moderno'),
('Estampada',  'estampada', 'Poleras con diseños y estampados exclusivos'),
('Premium',    'premium',   'Poleras premium de materiales selectos como Pima, bambú y modal'),
('Deportiva',  'deportiva', 'Poleras deportivas de alto rendimiento para todo deporte');

INSERT INTO products (name, slug, description, category_id, base_price, image_url) VALUES
('Polera Básica Blanca',        'polera-basica-blanca',        'Polera de algodón peinado 100%, corte recto clásico. Ideal para el uso diario.',             1,  9990, 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=600'),
('Polera Básica Negra',         'polera-basica-negra',         'Polera negra de algodón peinado 100%, infaltable en cualquier armario.',                    1,  9990, 'https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?w=600'),
('Polera Básica Gris',          'polera-basica-gris',          'Polera gris jaspeada de algodón, versátil y cómoda para el día a día.',                     1,  9990, 'https://images.unsplash.com/photo-1618354691373-d851c5c3a990?w=600'),
('Polera Básica Azul Marino',   'polera-basica-azul-marino',   'Polera azul marino de algodón, elegante y clásica para cualquier ocasión.',                 1, 11990, 'https://images.unsplash.com/photo-1622445275463-afa2ab738c34?w=600'),
('Polera Básica Verde Oliva',   'polera-basica-verde-oliva',   'Polera verde oliva de algodón, tono terroso de moda esta temporada.',                       1, 11990, 'https://images.unsplash.com/photo-1576566588028-4147f3842f27?w=600'),
('Oversize Urban Negro',        'oversize-urban-negro',        'Polera oversize corte urban, perfecta para el look streetwear moderno.',                    2, 19990, 'https://images.unsplash.com/photo-1529374255404-311a2a4f1fd9?w=600'),
('Oversize Urban Blanco',       'oversize-urban-blanco',       'Polera oversize blanca, el básico streetwear que no puede faltar.',                        2, 19990, 'https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?w=600'),
('Oversize Sage Green',         'oversize-sage-green',         'Polera oversize en tono sage green, tendencia en moda sostenible.',                        2, 21990, 'https://images.unsplash.com/photo-1562157873-818bc0726f68?w=600'),
('Oversize Camel',              'oversize-camel',              'Polera oversize en color camel, sofisticada y versátil para cualquier estilo.',             2, 21990, 'https://images.unsplash.com/photo-1551488831-00ddcb6c6bd3?w=600'),
('Oversize Lavanda',            'oversize-lavanda',            'Polera oversize en color lavanda pastel, fresquita y de tendencia.',                       2, 21990, 'https://images.unsplash.com/photo-1503341960582-b45751874cf0?w=600'),
('Estampada Mountains',         'estampada-mountains',         'Polera con estampado minimalista de montañas, para los amantes del outdoor.',               3, 17990, 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600'),
('Estampada Geometric',         'estampada-geometric',         'Polera con diseño geométrico abstracto en colores neutros.',                               3, 17990, 'https://images.unsplash.com/photo-1556821840-3a63f15732ce?w=600'),
('Estampada Sunset',            'estampada-sunset',            'Polera con vibrante estampado de atardecer, colores cálidos únicos.',                      3, 19990, 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?w=600'),
('Estampada Botánica',          'estampada-botanica',          'Polera con delicado estampado botánico, perfecta para el verano.',                         3, 19990, 'https://images.unsplash.com/photo-1571945153237-4929e783af4a?w=600'),
('Estampada Retro Wave',        'estampada-retro-wave',        'Polera con diseño retro años 80, colores neón sobre fondo oscuro.',                        3, 21990, 'https://images.unsplash.com/photo-1520975954732-35dd22299614?w=600'),
('Premium Pima Cotton Blanca',  'premium-pima-blanca',         'Polera de algodón Pima peruano 100%, suavidad excepcional y durabilidad superior.',        4, 29990, 'https://images.unsplash.com/photo-1527719327859-c6ce80353573?w=600'),
('Premium Pima Cotton Negra',   'premium-pima-negra',          'Polera negra de algodón Pima, el lujo accesible para el día a día.',                       4, 29990, 'https://images.unsplash.com/photo-1618354691438-25bc04584c23?w=600'),
('Premium Linen Blend',         'premium-linen-blend',         'Polera de mezcla lino-algodón, ligera y transpirable para el verano.',                     4, 34990, 'https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=600'),
('Premium Bamboo Gris',         'premium-bamboo-gris',         'Polera de fibra de bambú, eco-friendly, suave y reguladora de temperatura.',               4, 39990, 'https://images.unsplash.com/photo-1434389677669-e08b4cac3105?w=600'),
('Premium Modal Negra',         'premium-modal-negra',         'Polera de modal, tela de origen natural con caída perfecta y tacto sedoso.',               4, 34990, 'https://images.unsplash.com/photo-1598300042247-d088f8ab3a91?w=600'),
('Deportiva Dry-Fit Blanca',    'deportiva-dry-fit-blanca',    'Polera deportiva con tecnología Dry-Fit, absorbe la humedad y seca rápidamente.',          5, 16990, 'https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?w=600'),
('Deportiva Dry-Fit Negra',     'deportiva-dry-fit-negra',     'Polera deportiva negra Dry-Fit, ideal para running, gym o cualquier deporte.',             5, 16990, 'https://images.unsplash.com/photo-1584464491033-06628f3a6b7b?w=600'),
('Deportiva Compresión Azul',   'deportiva-compresion-azul',   'Polera de compresión azul, mejora el rendimiento y la recuperación muscular.',             5, 24990, 'https://images.unsplash.com/photo-1517836357463-d25dfeac3438?w=600'),
('Deportiva Trail Verde',       'deportiva-trail-verde',       'Polera trail running en verde neón, ultraligera con protección UV 50+.',                   5, 27990, 'https://images.unsplash.com/photo-1476480862126-209bfaa8edc8?w=600'),
('Deportiva Yoga Lila',         'deportiva-yoga-lila',         'Polera para yoga y pilates en color lila, tejido suave con 4-way stretch.',                5, 22990, 'https://images.unsplash.com/photo-1506629082955-511b1aa562c8?w=600');

-- Product variants (sizes and colors per product)
-- Product 1: Polera Básica Blanca
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(1,'S','Blanco','#FFFFFF','POL-BAS-BLA-S',15),(1,'M','Blanco','#FFFFFF','POL-BAS-BLA-M',25),
(1,'L','Blanco','#FFFFFF','POL-BAS-BLA-L',20),(1,'XL','Blanco','#FFFFFF','POL-BAS-BLA-XL',10);

-- Product 2: Polera Básica Negra
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(2,'XS','Negro','#000000','POL-BAS-NEG-XS',8),(2,'S','Negro','#000000','POL-BAS-NEG-S',18),
(2,'M','Negro','#000000','POL-BAS-NEG-M',30),(2,'L','Negro','#000000','POL-BAS-NEG-L',22),
(2,'XL','Negro','#000000','POL-BAS-NEG-XL',12),(2,'XXL','Negro','#000000','POL-BAS-NEG-XXL',5);

-- Product 3: Polera Básica Gris
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(3,'S','Gris','#9CA3AF','POL-BAS-GRI-S',12),(3,'M','Gris','#9CA3AF','POL-BAS-GRI-M',20),
(3,'L','Gris','#9CA3AF','POL-BAS-GRI-L',18),(3,'XL','Gris','#9CA3AF','POL-BAS-GRI-XL',8);

-- Product 4: Polera Básica Azul Marino
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(4,'S','Azul Marino','#1E3A5F','POL-BAS-MAR-S',10),(4,'M','Azul Marino','#1E3A5F','POL-BAS-MAR-M',15),
(4,'L','Azul Marino','#1E3A5F','POL-BAS-MAR-L',12),(4,'XL','Azul Marino','#1E3A5F','POL-BAS-MAR-XL',7);

-- Product 5: Polera Básica Verde Oliva
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(5,'XS','Verde Oliva','#6B7C45','POL-BAS-OLI-XS',5),(5,'S','Verde Oliva','#6B7C45','POL-BAS-OLI-S',12),
(5,'M','Verde Oliva','#6B7C45','POL-BAS-OLI-M',18),(5,'L','Verde Oliva','#6B7C45','POL-BAS-OLI-L',10);

-- Product 6: Oversize Urban Negro
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(6,'S','Negro','#000000','POL-OVR-URB-NEG-S',8),(6,'M','Negro','#000000','POL-OVR-URB-NEG-M',20),
(6,'L','Negro','#000000','POL-OVR-URB-NEG-L',15),(6,'XL','Negro','#000000','POL-OVR-URB-NEG-XL',10),
(6,'XXL','Negro','#000000','POL-OVR-URB-NEG-XXL',5);

-- Product 7: Oversize Urban Blanco
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(7,'S','Blanco','#FFFFFF','POL-OVR-URB-BLA-S',10),(7,'M','Blanco','#FFFFFF','POL-OVR-URB-BLA-M',22),
(7,'L','Blanco','#FFFFFF','POL-OVR-URB-BLA-L',18),(7,'XL','Blanco','#FFFFFF','POL-OVR-URB-BLA-XL',8);

-- Product 8: Oversize Sage Green
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(8,'S','Sage Green','#87A878','POL-OVR-SAG-S',6),(8,'M','Sage Green','#87A878','POL-OVR-SAG-M',14),
(8,'L','Sage Green','#87A878','POL-OVR-SAG-L',10),(8,'XL','Sage Green','#87A878','POL-OVR-SAG-XL',6);

-- Product 9: Oversize Camel
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(9,'S','Camel','#C19A6B','POL-OVR-CAM-S',5),(9,'M','Camel','#C19A6B','POL-OVR-CAM-M',12),
(9,'L','Camel','#C19A6B','POL-OVR-CAM-L',8),(9,'XL','Camel','#C19A6B','POL-OVR-CAM-XL',4);

-- Product 10: Oversize Lavanda
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(10,'XS','Lavanda','#E6D7F5','POL-OVR-LAV-XS',4),(10,'S','Lavanda','#E6D7F5','POL-OVR-LAV-S',10),
(10,'M','Lavanda','#E6D7F5','POL-OVR-LAV-M',15),(10,'L','Lavanda','#E6D7F5','POL-OVR-LAV-L',8);

-- Products 11-15: Estampadas
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(11,'S','Blanco','#FFFFFF','POL-EST-MOU-S',8),(11,'M','Blanco','#FFFFFF','POL-EST-MOU-M',15),
(11,'L','Blanco','#FFFFFF','POL-EST-MOU-L',10),(11,'XL','Blanco','#FFFFFF','POL-EST-MOU-XL',5),
(12,'S','Negro','#000000','POL-EST-GEO-S',7),(12,'M','Negro','#000000','POL-EST-GEO-M',12),
(12,'L','Negro','#000000','POL-EST-GEO-L',9),(12,'XL','Negro','#000000','POL-EST-GEO-XL',4),
(13,'S','Blanco','#FFFFFF','POL-EST-SUN-S',6),(13,'M','Blanco','#FFFFFF','POL-EST-SUN-M',10),
(13,'L','Blanco','#FFFFFF','POL-EST-SUN-L',8),(13,'XL','Blanco','#FFFFFF','POL-EST-SUN-XL',3),
(14,'XS','Blanco','#FFFFFF','POL-EST-BOT-XS',3),(14,'S','Blanco','#FFFFFF','POL-EST-BOT-S',8),
(14,'M','Blanco','#FFFFFF','POL-EST-BOT-M',12),(14,'L','Blanco','#FFFFFF','POL-EST-BOT-L',7),
(15,'S','Negro','#1A1A2E','POL-EST-RET-S',5),(15,'M','Negro','#1A1A2E','POL-EST-RET-M',10),
(15,'L','Negro','#1A1A2E','POL-EST-RET-L',7),(15,'XL','Negro','#1A1A2E','POL-EST-RET-XL',3);

-- Products 16-20: Premium
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(16,'S','Blanco','#FFFFFF','POL-PRE-PIM-BLA-S',5),(16,'M','Blanco','#FFFFFF','POL-PRE-PIM-BLA-M',10),
(16,'L','Blanco','#FFFFFF','POL-PRE-PIM-BLA-L',8),(16,'XL','Blanco','#FFFFFF','POL-PRE-PIM-BLA-XL',4),
(17,'S','Negro','#000000','POL-PRE-PIM-NEG-S',5),(17,'M','Negro','#000000','POL-PRE-PIM-NEG-M',10),
(17,'L','Negro','#000000','POL-PRE-PIM-NEG-L',8),(17,'XL','Negro','#000000','POL-PRE-PIM-NEG-XL',4),
(18,'S','Beige','#F5E6D3','POL-PRE-LIN-S',4),(18,'M','Beige','#F5E6D3','POL-PRE-LIN-M',8),
(18,'L','Beige','#F5E6D3','POL-PRE-LIN-L',6),(18,'XL','Beige','#F5E6D3','POL-PRE-LIN-XL',3),
(19,'S','Gris','#9CA3AF','POL-PRE-BAM-S',3),(19,'M','Gris','#9CA3AF','POL-PRE-BAM-M',7),
(19,'L','Gris','#9CA3AF','POL-PRE-BAM-L',5),(19,'XL','Gris','#9CA3AF','POL-PRE-BAM-XL',2),
(20,'S','Negro','#000000','POL-PRE-MOD-S',4),(20,'M','Negro','#000000','POL-PRE-MOD-M',8),
(20,'L','Negro','#000000','POL-PRE-MOD-L',6),(20,'XL','Negro','#000000','POL-PRE-MOD-XL',3);

-- Products 21-25: Deportiva
INSERT INTO product_variants (product_id, size, color, color_hex, sku, stock) VALUES
(21,'S','Blanco','#FFFFFF','POL-DEP-DRY-BLA-S',10),(21,'M','Blanco','#FFFFFF','POL-DEP-DRY-BLA-M',20),
(21,'L','Blanco','#FFFFFF','POL-DEP-DRY-BLA-L',15),(21,'XL','Blanco','#FFFFFF','POL-DEP-DRY-BLA-XL',8),
(22,'S','Negro','#000000','POL-DEP-DRY-NEG-S',10),(22,'M','Negro','#000000','POL-DEP-DRY-NEG-M',20),
(22,'L','Negro','#000000','POL-DEP-DRY-NEG-L',15),(22,'XL','Negro','#000000','POL-DEP-DRY-NEG-XL',8),
(22,'XXL','Negro','#000000','POL-DEP-DRY-NEG-XXL',4),
(23,'S','Azul','#1E40AF','POL-DEP-COM-AZU-S',6),(23,'M','Azul','#1E40AF','POL-DEP-COM-AZU-M',12),
(23,'L','Azul','#1E40AF','POL-DEP-COM-AZU-L',9),(23,'XL','Azul','#1E40AF','POL-DEP-COM-AZU-XL',5),
(24,'S','Verde Neón','#22C55E','POL-DEP-TRA-VER-S',5),(24,'M','Verde Neón','#22C55E','POL-DEP-TRA-VER-M',10),
(24,'L','Verde Neón','#22C55E','POL-DEP-TRA-VER-L',7),(24,'XL','Verde Neón','#22C55E','POL-DEP-TRA-VER-XL',4),
(25,'XS','Lila','#A78BFA','POL-DEP-YOG-LIL-XS',4),(25,'S','Lila','#A78BFA','POL-DEP-YOG-LIL-S',8),
(25,'M','Lila','#A78BFA','POL-DEP-YOG-LIL-M',12),(25,'L','Lila','#A78BFA','POL-DEP-YOG-LIL-L',6);
