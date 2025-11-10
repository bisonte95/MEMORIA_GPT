# app.py - API FastAPI para la memoria externa (tarifas, notas y albaranes)
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

DB_PATH = Path(__file__).with_name("memoria.db")
app = FastAPI(title="Memoria tarifas", version="1.0")


# ---------------------------
# Utilidades de base de datos
# ---------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db_exists() -> None:
    """Valida que memoria.db exista antes de leer/escribir."""
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="memoria.db no existe. Ejecuta `python crear_db.py` antes.")


# ---------------------------
# Modelos Pydantic (entrada)
# ---------------------------
ServiceType = Literal["groupage", "FTL", "LTL", "otro"]
OperationType = Literal["set", "percent_up", "percent_down", "add", "subtract"]
CategoriaType = Literal["incidencia", "preferencia", "veto", "SLA", "otro"]
GravedadType = Literal["baja", "media", "alta"]


class GetTariffIn(BaseModel):
    origen: str
    destino: str
    tipo_servicio: ServiceType
    peso: float
    fecha: Optional[str] = None
    precio_base: Optional[float] = None
    session_id: Optional[str] = None
    usuario: Optional[str] = None
    empresa_elegida: Optional[str] = None


class WeightRange(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class PatchTariffIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    origen: str = Field(alias="route_from")
    destino: str = Field(alias="route_to")
    tipo_servicio: ServiceType = Field(alias="service_type")
    weight_range: Optional[WeightRange] = None
    campo_objetivo: str = Field(alias="target_field")
    operacion: OperationType
    valor: float
    efectivo_desde: Optional[str] = None
    efectivo_hasta: Optional[str] = None
    nota: Optional[str] = None
    autor: Optional[str] = "gpt"


class AddNoteIn(BaseModel):
    origen: str
    destino: str
    empresa: Optional[str] = None
    categoria: CategoriaType
    gravedad: GravedadType
    nota: str
    fecha: Optional[str] = None
    autor: Optional[str] = "gpt"


# ---------------------------
# Lógica de negocio
# ---------------------------
def aplicar_parches(precio_inicial: float, parches: List[Dict[str, Any]]) -> float:
    """Aplica los parches secuencialmente y devuelve el precio final redondeado."""
    precio = float(precio_inicial)
    for parche in parches:
        operacion = parche["operacion"]
        valor = float(parche["valor"])
        if operacion == "set":
            precio = valor
        elif operacion == "percent_up":
            precio *= 1 + (valor / 100)
        elif operacion == "percent_down":
            precio *= 1 - (valor / 100)
        elif operacion == "add":
            precio += valor
        elif operacion == "subtract":
            precio -= valor
    return round(precio, 2)


# ---------------------------
# Endpoints
# ---------------------------
@app.post("/patch_tariff")
def patch_tariff(payload: PatchTariffIn) -> Dict[str, Any]:
    ensure_db_exists()
    rango_min = payload.weight_range.min if payload.weight_range else None
    rango_max = payload.weight_range.max if payload.weight_range else None

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO parches_tarifa(
              origen, destino, tipo_servicio, rango_peso_min, rango_peso_max,
              campo_objetivo, operacion, valor, efectivo_desde, efectivo_hasta,
              nota, autor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.origen,
                payload.destino,
                payload.tipo_servicio,
                rango_min,
                rango_max,
                payload.campo_objetivo,
                payload.operacion,
                payload.valor,
                payload.efectivo_desde,
                payload.efectivo_hasta,
                payload.nota,
                payload.autor,
            ),
        )
    return {"ok": True}


@app.post("/add_note")
def add_note(payload: AddNoteIn) -> Dict[str, Any]:
    ensure_db_exists()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO notas_operativas(
              origen, destino, empresa, categoria, gravedad, nota, fecha, autor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.origen,
                payload.destino,
                payload.empresa,
                payload.categoria,
                payload.gravedad,
                payload.nota,
                payload.fecha,
                payload.autor,
            ),
        )
    return {"ok": True}


@app.post("/ingest_albaran")
async def ingest_albaran(file: UploadFile = File(...)) -> Dict[str, Any]:
    ensure_db_exists()
    try:
        payload = json.loads((await file.read()).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalido: {exc}") from exc

    header = payload.get("header")
    lineas = payload.get("lineas")
    if not isinstance(header, dict) or not isinstance(lineas, list):
        raise HTTPException(status_code=400, detail="Se espera {'header': {...}, 'lineas': [...]}.")

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO albaranes(
              hoja_ruta_num, fecha, transportista_redactado, matricula, cif,
              booking, bruto_total, bultos_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                header.get("hoja_ruta_num"),
                header.get("fecha"),
                header.get("transportista_redactado"),
                header.get("matricula"),
                header.get("cif"),
                header.get("booking"),
                header.get("bruto_total"),
                header.get("bultos_total"),
            ),
        )
        albaran_id = cur.lastrowid
        for linea in lineas:
            if not isinstance(linea, dict):
                continue
            conn.execute(
                """
                INSERT INTO albaran_lineas(
                  albaran_id, albaran_num, cliente_proveedor, direccion_ciudad_raw,
                  cp, pais, bultos, peso_bruto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    albaran_id,
                    linea.get("albaran_num") or linea.get("albaran"),
                    linea.get("cliente_proveedor"),
                    linea.get("direccion_ciudad_raw"),
                    linea.get("cp"),
                    linea.get("pais"),
                    linea.get("bultos"),
                    linea.get("peso_bruto"),
                ),
            )

    return {"ok": True, "albaran_id": albaran_id}


@app.post("/get_tariff")
def get_tariff(payload: GetTariffIn) -> Dict[str, Any]:
    ensure_db_exists()
    start = time.perf_counter()
    precio_base = payload.precio_base if payload.precio_base is not None else 1000.0
    fecha_ref = payload.fecha or time.strftime("%Y-%m-%d")

    with get_db() as conn:
        parches_rows = conn.execute(
            """
            SELECT campo_objetivo, operacion, valor, nota, autor, ts
            FROM parches_tarifa
            WHERE origen = ?
              AND destino = ?
              AND tipo_servicio = ?
              AND (rango_peso_min IS NULL OR rango_peso_min <= ?)
              AND (rango_peso_max IS NULL OR rango_peso_max >= ?)
              AND (efectivo_desde IS NULL OR ? >= efectivo_desde)
              AND (efectivo_hasta IS NULL OR ? <= efectivo_hasta)
            ORDER BY ts ASC
            """,
            (
                payload.origen,
                payload.destino,
                payload.tipo_servicio,
                payload.peso,
                payload.peso,
                fecha_ref,
                fecha_ref,
            ),
        ).fetchall()

    parches = [dict(row) for row in parches_rows]
    parches_precio = [p for p in parches if p["campo_objetivo"] == "precio"]
    precio_final = aplicar_parches(precio_base, parches_precio)
    dur_ms = int((time.perf_counter() - start) * 1000)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO historico_consultas(
              origen, destino, tipo_servicio, peso,
              empresa_elegida, precio_final, tiempo_calculo_ms,
              session_id, usuario
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.origen,
                payload.destino,
                payload.tipo_servicio,
                payload.peso,
                payload.empresa_elegida,
                precio_final,
                dur_ms,
                payload.session_id,
                payload.usuario,
            ),
        )
        avisos_rows = conn.execute(
            """
            SELECT empresa, categoria, gravedad, nota, fecha, ts
            FROM notas_operativas
            WHERE origen = ? AND destino = ?
            ORDER BY ts DESC
            LIMIT 5
            """,
            (payload.origen, payload.destino),
        ).fetchall()

    avisos = [dict(row) for row in avisos_rows]

    return {
        "precio_base": round(precio_base, 2),
        "precio_final": precio_final,
        "parches_aplicados": parches,
        "avisos": avisos,
    }
