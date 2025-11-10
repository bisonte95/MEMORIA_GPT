# MEMORIA_GPT

Rol: Actúa como un DevOps + Backend senior que automatiza al máximo.
Objetivo: Crear un repositorio “memoria-tarifas-api” con una API FastAPI + SQLite para servir de memoria externa de un agente GPT (no toca los Excel). Después, desplegar en Render.com (plan gratis) y entregar una URL HTTPS lista para usar en las Actions del GPT. Finalmente, dame un paso a paso para integrarlo en ChatGPT (OpenAPI) y validarlo.

0) Requisitos funcionales

La API debe exponer estos endpoints:

POST /get_tariff
Entrada: { origen, destino, tipo_servicio, peso, fecha?, precio_base? }
Lógica: aplica parches vigentes sobre precio_base (si viene; si no, usar 1000 como placeholder), registra en historico_consultas, devuelve { precio_base, precio_final, parches_aplicados, avisos } (avisos = últimas 5 notas coincidentes por ruta).

POST /patch_tariff
Entrada: { route_from, route_to, service_type, weight_range?, target_field, operacion, valor, efectivo_desde?, efectivo_hasta?, nota?, autor? }
Inserta un parche de tarifa (no modifica los Excel).

POST /add_note
Entrada: { origen, destino, empresa?, categoria, gravedad, nota, fecha?, autor? }
Inserta una nota/incidencia operativa.

POST /ingest_albaran
Entrada: multipart/form-data con file (JSON) → {"header":{...},"lineas":[...]}.
Inserta en albaranes (cabecera) y albaran_lineas (detalle).

1) Estructura del repo a crear

Genera un repo con estos archivos y contenidos exactos:

schema.sql

-- Memoria externa para el agente GPT (sin tocar Excel)

CREATE TABLE IF NOT EXISTS parches_tarifa(
  id_parche INTEGER PRIMARY KEY AUTOINCREMENT,
  origen TEXT, destino TEXT, tipo_servicio TEXT,
  rango_peso_min REAL, rango_peso_max REAL,
  campo_objetivo TEXT,           -- 'precio', 'recargo_fuel', etc.
  operacion TEXT,                -- 'set' | 'percent_up' | 'percent_down' | 'add' | 'subtract'
  valor REAL,
  efectivo_desde DATE, efectivo_hasta DATE,
  nota TEXT, autor TEXT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS historico_consultas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  origen TEXT, destino TEXT, tipo_servicio TEXT,
  peso REAL,
  empresa_elegida TEXT, precio_final REAL, tiempo_calculo_ms INTEGER,
  session_id TEXT, usuario TEXT
);

CREATE TABLE IF NOT EXISTS notas_operativas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  origen TEXT, destino TEXT, empresa TEXT,
  categoria TEXT,               -- incidencia | preferencia | veto | SLA | otro
  gravedad TEXT,                -- baja | media | alta
  nota TEXT, fecha DATE,
  autor TEXT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS albaranes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hoja_ruta_num TEXT,
  fecha TEXT,
  transportista_redactado TEXT,
  matricula TEXT, cif TEXT, booking TEXT,
  bruto_total REAL, bultos_total INTEGER,
  ts_ingesta TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS albaran_lineas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  albaran_id INTEGER REFERENCES albaranes(id),
  albaran_num TEXT, cliente_proveedor TEXT,
  direccion_ciudad_raw TEXT, cp TEXT, pais TEXT,
  bultos REAL, peso_bruto REAL
);


crear_db.py

import sqlite3
from pathlib import Path

schema = Path("schema.sql").read_text(encoding="utf-8")
con = sqlite3.connect("memoria.db")
con.executescript(schema)
con.commit()
con.close()
print("OK: memoria.db creada")


app.py

from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
import sqlite3, time, json

DB = "memoria.db"
app = FastAPI(title="Memoria tarifas", version="1.0")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

class GetTariffIn(BaseModel):
    origen: str
    destino: str
    tipo_servicio: str
    peso: float
    fecha: Optional[str] = None
    precio_base: Optional[float] = None

class PatchTariffIn(BaseModel):
    route_from: str
    route_to: str
    service_type: str
    weight_range: Optional[Dict[str, float]] = None
    target_field: str
    operacion: str          # set | percent_up | percent_down | add | subtract
    valor: float
    efectivo_desde: Optional[str] = None
    efectivo_hasta: Optional[str] = None
    nota: Optional[str] = None
    autor: Optional[str] = "gpt"

class AddNoteIn(BaseModel):
    origen: str
    destino: str
    empresa: Optional[str] = None
    categoria: str
    gravedad: str
    nota: str
    fecha: Optional[str] = None
    autor: Optional[str] = "gpt"

def aplicar_parches(precio_inicial: float, parches: List[dict]) -> float:
    precio = float(precio_inicial)
    for p in parches:
        op = p["operacion"]; val = float(p["valor"])
        if op == "set": precio = val
        elif op == "percent_up": precio *= (1 + val/100)
        elif op == "percent_down": precio *= (1 - val/100)
        elif op == "add": precio += val
        elif op == "subtract": precio -= val
    return round(precio, 2)

@app.post("/patch_tariff")
def patch_tariff(payload: PatchTariffIn):
    wr = payload.weight_range or {}
    with db() as conn:
        conn.execute("""
          INSERT INTO parches_tarifa(origen,destino,tipo_servicio,rango_peso_min,rango_peso_max,
            campo_objetivo,operacion,valor,efectivo_desde,efectivo_hasta,nota,autor)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (payload.route_from, payload.route_to, payload.service_type,
              wr.get("min"), wr.get("max"),
              payload.target_field, payload.operacion, payload.valor,
              payload.efectivo_desde, payload.efectivo_hasta,
              payload.nota, payload.autor))
    return {"ok": True}

@app.post("/add_note")
def add_note(payload: AddNoteIn):
    with db() as conn:
        conn.execute("""
          INSERT INTO notas_operativas(origen,destino,empresa,categoria,gravedad,nota,fecha,autor)
          VALUES (?,?,?,?,?,?,?,?)
        """, (payload.origen, payload.destino, payload.empresa, payload.categoria,
              payload.gravedad, payload.nota, payload.fecha, payload.autor))
    return {"ok": True}

@app.post("/ingest_albaran")
async def ingest_albaran(file: UploadFile = File(...)):
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
        hdr, lines = data["header"], data["lineas"]
        with db() as conn:
            cur = conn.execute("""
              INSERT INTO albaranes(hoja_ruta_num,fecha,transportista_redactado,matricula,cif,booking,bruto_total,bultos_total)
              VALUES (?,?,?,?,?,?,?,?)
            """, (hdr.get("hoja_ruta_num"), hdr.get("fecha"), hdr.get("transportista_redactado"),
                  hdr.get("matricula"), hdr.get("cif"), hdr.get("booking"),
                  hdr.get("bruto_total"), hdr.get("bultos_total")))
            albaran_id = cur.lastrowid
            for ln in lines:
                conn.execute("""
                  INSERT INTO albaran_lineas(albaran_id,albaran_num,cliente_proveedor,direccion_ciudad_raw,cp,pais,bultos,peso_bruto)
                  VALUES (?,?,?,?,?,?,?,?)
                """, (albaran_id, ln.get("albaran"), ln.get("cliente_proveedor"), ln.get("direccion_ciudad_raw"),
                      ln.get("cp"), ln.get("pais"), ln.get("bultos"), ln.get("peso_bruto")))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"Formato no soportado: {e}"}

@app.post("/get_tariff")
def get_tariff(payload: GetTariffIn):
    t0 = time.time()
    precio_base = payload.precio_base if payload.precio_base is not None else 1000.0
    fecha_ref = payload.fecha or "2099-01-01"
    with db() as conn:
        rows = conn.execute("""
          SELECT campo_objetivo, operacion, valor, efectivo_desde, efectivo_hasta, nota, autor, ts
          FROM parches_tarifa
          WHERE origen=? AND destino=? AND tipo_servicio=?
            AND (rango_peso_min IS NULL OR rango_peso_min <= ?)
            AND (rango_peso_max IS NULL OR rango_peso_max >= ?)
            AND (efectivo_desde IS NULL OR ? >= efectivo_desde)
            AND (efectivo_hasta IS NULL OR ? <= efectivo_hasta)
          ORDER BY ts ASC
        """, (payload.origen, payload.destino, payload.tipo_servicio,
              payload.peso, payload.peso, fecha_ref, fecha_ref)).fetchall()
        parches = [dict(r) for r in rows]

    parches_precio = [p for p in parches if p["campo_objetivo"] == "precio"]
    precio_final = aplicar_parches(precio_base, parches_precio)

    dur_ms = int((time.time() - t0) * 1000)
    with db() as conn:
        conn.execute("""
          INSERT INTO historico_consultas(origen,destino,tipo_servicio,peso,empresa_elegida,precio_final,tiempo_calculo_ms)
          VALUES (?,?,?,?,?,?,?)
        """, (payload.origen, payload.destino, payload.tipo_servicio, payload.peso, None, precio_final, dur_ms))

    with db() as conn:
        rows = conn.execute("""
          SELECT empresa, categoria, gravedad, nota, fecha
          FROM notas_operativas
          WHERE origen=? AND destino=?
          ORDER BY ts DESC LIMIT 5
        """, (payload.origen, payload.destino)).fetchall()
        avisos = [dict(r) for r in rows]

    return {
        "precio_base": precio_base,
        "precio_final": precio_final,
        "parches_aplicados": parches,
        "avisos": avisos
    }


requirements.txt

fastapi==0.115.0
uvicorn==0.30.6
pydantic==2.9.2


Procfile

web: python crear_db.py && uvicorn app:app --host 0.0.0.0 --port $PORT


openapi_memoria.yaml (poner luego la URL de Render)

openapi: 3.1.0
info:
  title: Memoria tarifas
  version: '1.0'
servers:
  - url: https://REEMPLAZA-ESTO.onrender.com
paths:
  /get_tariff:
    post:
      summary: Devuelve precio final aplicando parches y avisos
      operationId: getTariff
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                origen: { type: string }
                destino: { type: string }
                tipo_servicio: { type: string, enum: [groupage, FTL, LTL, otro] }
                peso: { type: number }
                fecha: { type: string, description: "YYYY-MM-DD", nullable: true }
                precio_base: { type: number, description: "Precio base calculado por el GPT desde los Excel", nullable: true }
              required: [origen, destino, tipo_servicio, peso]
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  precio_base: { type: number }
                  precio_final: { type: number }
                  parches_aplicados:
                    type: array
                    items:
                      type: object
                      properties:
                        campo_objetivo: { type: string }
                        operacion: { type: string }
                        valor: { type: number }
                        efectivo_desde: { type: string, nullable: true }
                        efectivo_hasta: { type: string, nullable: true }
                        nota: { type: string, nullable: true }
                        autor: { type: string, nullable: true }
                        ts: { type: string, nullable: true }
                  avisos:
                    type: array
                    items:
                      type: object
                      properties:
                        empresa: { type: string, nullable: true }
                        categoria: { type: string }
                        gravedad: { type: string }
                        nota: { type: string }
                        fecha: { type: string, nullable: true }
  /patch_tariff:
    post:
      summary: Inserta un parche de tarifa (no toca Excel)
      operationId: patchTariff
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                route_from: { type: string }
                route_to: { type: string }
                service_type: { type: string, enum: [groupage, FTL, LTL, otro] }
                weight_range:
                  type: object
                  properties:
                    min: { type: number }
                    max: { type: number }
                target_field: { type: string, enum: [precio, recargo_fuel] }
                operacion: { type: string, enum: [set, percent_up, percent_down, add, subtract] }
                valor: { type: number }
                efectivo_desde: { type: string, nullable: true }
                efectivo_hasta: { type: string, nullable: true }
                nota: { type: string, nullable: true }
                autor: { type: string, nullable: true }
              required: [route_from, route_to, service_type, target_field, operacion, valor]
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  ok: { type: boolean }
  /add_note:
    post:
      summary: Inserta una nota/incidencia operativa
      operationId: addNote
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                origen: { type: string }
                destino: { type: string }
                empresa: { type: string, nullable: true }
                categoria: { type: string, enum: [incidencia, preferencia, veto, SLA, otro] }
                gravedad: { type: string, enum: [baja, media, alta] }
                nota: { type: string }
                fecha: { type: string, nullable: true }
                autor: { type: string, nullable: true }
              required: [origen, destino, categoria, gravedad, nota]
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  ok: { type: boolean }
  /ingest_albaran:
    post:
      summary: Ingesta un albarán como fichero JSON (cabecera + líneas)
      operationId: ingestAlbaran
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                file:
                  type: string
                  format: binary
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  ok: { type: boolean }
                  error: { type: string, nullable: true }


README.md

Explica: qué hace la API, cómo correrla local, cómo desplegar en Render (Build: pip install -r requirements.txt; Start: python crear_db.py && uvicorn app:app --host 0.0.0.0 --port $PORT), cómo probar en /docs, cómo integrar el OpenAPI en GPT (Actions).

2) Automatiza despliegue en Render (sin admin local)

Crea el repo en mi GitHub (memoria-tarifas-api), sube los archivos.

Ve a render.com → New → Web Service → conectar con mi repo.

Configura:

Build Command: pip install -r requirements.txt

Start Command: python crear_db.py && uvicorn app:app --host 0.0.0.0 --port $PORT

Plan: Free

Espera a que Render compile y arranque.

Devuélveme la URL HTTPS pública (ej. https://memoria-tarifas-api.onrender.com).

3) Validación automática

Con la URL de Render:

Prueba POST /patch_tariff con:

{
  "route_from":"Elorrio",
  "route_to":"Munich",
  "service_type":"groupage",
  "target_field":"precio",
  "operacion":"percent_up",
  "valor":5,
  "efectivo_desde":"2025-11-10",
  "nota":"ajuste prueba"
}


Luego POST /get_tariff con:

{
  "origen":"Elorrio",
  "destino":"Munich",
  "tipo_servicio":"groupage",
  "peso":350,
  "fecha":"2025-11-10",
  "precio_base":1000
}


Debe devolver precio_final ≈ 1050. Captura respuesta y pégamela.

4) Instrucciones para integrar en ChatGPT (Actions)

Abre tu GPT → Acciones (Actions) → Importar OpenAPI.

Pega openapi_memoria.yaml y reemplaza servers.url por la URL de Render.

Guarda. Verifica que aparecen las 4 acciones sin errores.

Dame un mini-guion para usarlo:

Subir 5% (patch_tariff)

Consultar tarifa (get_tariff, pasando precio_base)

Añadir incidencia (add_note)

Subir albarán JSON (ingest_albaran)

5) Entregables finales

URL del repo público.

URL HTTPS de Render.

Respuestas JSON de las pruebas.

Instrucciones paso a paso (copiar/pegar) para mí.

6) Consideraciones

No tocar Excel; la API solo aplica parches sobre el “precio_base” que calcule el GPT.

Sin dependencias extra (solo fastapi/uvicorn/pydantic).

Sistema de archivos efímero en Render: crear_db.py debe recrear memoria.db en cada arranque.

Más adelante migraremos a Postgres si hace falta persistencia duradera.

Empieza creando el repo y los archivos. Pausa y espera mi “OK” antes de desplegar en Render.