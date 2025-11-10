-- schema.sql — estructura de la memoria SQLite (UTF-8)

-- Parches de tarifa aplicados sobre los Excel originales.
CREATE TABLE IF NOT EXISTS parches_tarifa(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  origen TEXT,
  destino TEXT,
  tipo_servicio TEXT,
  rango_peso_min REAL,
  rango_peso_max REAL,
  campo_objetivo TEXT,
  operacion TEXT,
  valor REAL,
  efectivo_desde DATE,
  efectivo_hasta DATE,
  nota TEXT,
  autor TEXT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Histórico de consultas para auditar precios y sugerencias.
CREATE TABLE IF NOT EXISTS historico_consultas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  origen TEXT,
  destino TEXT,
  tipo_servicio TEXT,
  peso REAL,
  empresa_elegida TEXT,
  precio_final REAL,
  tiempo_calculo_ms INTEGER,
  session_id TEXT,
  usuario TEXT
);

-- Notas operativas e incidencias.
CREATE TABLE IF NOT EXISTS notas_operativas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  origen TEXT,
  destino TEXT,
  empresa TEXT,
  categoria TEXT,
  gravedad TEXT,
  nota TEXT,
  fecha DATE,
  autor TEXT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Albaranes: cabecera.
CREATE TABLE IF NOT EXISTS albaranes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hoja_ruta_num TEXT,
  fecha TEXT,
  transportista_redactado TEXT,
  matricula TEXT,
  cif TEXT,
  booking TEXT,
  bruto_total REAL,
  bultos_total INTEGER,
  ts_ingesta TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Albaranes: detalle.
CREATE TABLE IF NOT EXISTS albaran_lineas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  albaran_id INTEGER REFERENCES albaranes(id),
  albaran_num TEXT,
  cliente_proveedor TEXT,
  direccion_ciudad_raw TEXT,
  cp TEXT,
  pais TEXT,
  bultos REAL,
  peso_bruto REAL
);
