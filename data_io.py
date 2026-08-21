"""
Entrada de datos: plantilla de Excel, lectura/validación, y conversión
del DataFrame de la tabla editable de Streamlit hacia objetos Delivery.
"""
from __future__ import annotations
from typing import List, Tuple
import io

import pandas as pd

from models import Delivery

COLUMNS = ["modelo", "delivery", "bulto_extra", "largo_ft", "ancho_ft", "alto_ft"]
COLUMN_LABELS = {
    "modelo": "Modelo",
    "delivery": "Delivery",
    "bulto_extra": "Bulto extra",
    "largo_ft": "Largo (ft)",
    "ancho_ft": "Ancho (ft)",
    "alto_ft": "Alto (ft)",
}


def empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame({
        "modelo": pd.Series(dtype="str"),
        "delivery": pd.Series(dtype="Int64"),
        "bulto_extra": pd.Series(dtype="str"),
        "largo_ft": pd.Series(dtype="float"),
        "ancho_ft": pd.Series(dtype="float"),
        "alto_ft": pd.Series(dtype="float"),
    })


def sample_dataframe(n: int = 6) -> pd.DataFrame:
    import random
    random.seed(7)
    modelos = ["TR-450", "TR-620", "LD-300", "LD-500", "XC-100"]
    rows = []
    for i in range(n):
        # la mayoría sin bulto extra (vacío); algunas con 1, 2 o 3 ("y", "yy", "yyy")
        n_bultos = random.choices([0, 1, 2, 3], weights=[70, 18, 8, 4])[0]
        rows.append({
            "modelo": random.choice(modelos),
            "delivery": 1000 + i,
            "bulto_extra": "y" * n_bultos,
            "largo_ft": round(random.uniform(5.0, 9.5), 2),
            "ancho_ft": round(random.uniform(3.0, 4.1), 2),
            "alto_ft": round(random.uniform(3.5, 6.5), 2),
        })
    return pd.DataFrame(rows)


def make_template_excel_bytes() -> bytes:
    df = sample_dataframe(3)
    df = df.rename(columns=COLUMN_LABELS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Deliveries")
        ws = writer.sheets["Deliveries"]
        widths = [14, 12, 12, 12, 12, 12]
        for col_idx, w in enumerate(widths, start=1):
            ws.column_dimensions[chr(64 + col_idx)].width = w
    buf.seek(0)
    return buf.read()


def read_excel_to_dataframe(file) -> pd.DataFrame:
    """Lee un excel subido por el usuario y normaliza nombres de columnas,
    aceptando tanto encabezados en español (con acentos/espacios) como
    los nombres técnicos internos."""
    raw = pd.read_excel(file)
    reverse_labels = {v.lower(): k for k, v in COLUMN_LABELS.items()}
    norm_cols = {}
    for c in raw.columns:
        key = str(c).strip().lower()
        if key in reverse_labels:
            norm_cols[c] = reverse_labels[key]
        elif key in COLUMNS:
            norm_cols[c] = key
        else:
            # intenta coincidencias parciales comunes
            if "model" in key:
                norm_cols[c] = "modelo"
            elif "deliver" in key:
                norm_cols[c] = "delivery"
            elif "bulto" in key or "extra" in key:
                norm_cols[c] = "bulto_extra"
            elif "larg" in key:
                norm_cols[c] = "largo_ft"
            elif "anch" in key:
                norm_cols[c] = "ancho_ft"
            elif "alt" in key:
                norm_cols[c] = "alto_ft"
    df = raw.rename(columns=norm_cols)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Al excel le faltan columnas requeridas: " + ", ".join(COLUMN_LABELS[m] for m in missing)
        )
    df = df[COLUMNS].copy()
    df = _coerce_column_dtypes(df)
    return df


def _coerce_column_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Fuerza los tipos de columna esperados por la tabla editable de
    Streamlit. En particular, 'bulto_extra' debe quedar como texto (nunca
    NaN/float), porque celdas vacías en un Excel se leen como NaN numérico
    y eso choca con el TextColumn de la UI."""
    df["modelo"] = df["modelo"].apply(lambda v: "" if pd.isna(v) else str(v).strip())

    def _norm_bulto(v):
        if pd.isna(v):
            return ""
        if isinstance(v, (int, float)):
            # por si en el excel llega ya como número (p.ej. 2) en vez de 'yy'
            return str(int(v)) if float(v).is_integer() else str(v)
        return str(v).strip()

    df["bulto_extra"] = df["bulto_extra"].apply(_norm_bulto).astype(str)

    for col in ("largo_ft", "ancho_ft", "alto_ft"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["delivery"] = pd.to_numeric(df["delivery"], errors="coerce").astype("Int64")

    return df


def parse_bulto_extra(raw) -> int:
    """Convierte el valor capturado en la columna 'bulto extra' a un entero:
    vacío/NaN -> 0; 'y' -> 1; 'yy' -> 2; 'yyy' -> 3; etc (no distingue
    mayúsculas/minúsculas). Si ya viene como número, se respeta tal cual.
    Cualquier otro texto se considera inválido."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 0
    if isinstance(raw, (int, float)):
        if pd.isna(raw):
            return 0
        return int(raw)
    text = str(raw).strip()
    if text == "" or text.lower() == "nan":
        return 0
    if text.isdigit():
        return int(text)
    if all(ch.lower() == "y" for ch in text):
        return len(text)
    raise ValueError("bulto extra inválido: usa 'y' repetida (y, yy, yyy...) o déjalo vacío")


def dataframe_to_deliveries(df: pd.DataFrame) -> Tuple[List[Delivery], List[str]]:
    """Convierte el DataFrame a una lista de Delivery. Regresa también una
    lista de advertencias/errores por fila para mostrar al usuario."""
    deliveries: List[Delivery] = []
    errors: List[str] = []
    df = df.dropna(how="all")

    for i, row in df.iterrows():
        row_label = f"Fila {i + 1}"
        try:
            modelo = str(row["modelo"]).strip()
            if not modelo or modelo.lower() == "nan":
                errors.append(f"{row_label}: falta el modelo.")
                continue
            delivery_val = row["delivery"]
            if pd.isna(delivery_val):
                errors.append(f"{row_label}: falta el número de delivery.")
                continue
            delivery_int = int(delivery_val)

            try:
                bulto_count = parse_bulto_extra(row["bulto_extra"])
            except ValueError as e:
                errors.append(f"{row_label}: {e}.")
                continue

            largo = float(row["largo_ft"])
            ancho = float(row["ancho_ft"])
            alto = float(row["alto_ft"]) if not pd.isna(row["alto_ft"]) else 0.0

            if largo <= 0 or ancho <= 0:
                errors.append(f"{row_label}: largo y ancho deben ser mayores a 0.")
                continue

            deliveries.append(Delivery(
                modelo=modelo, delivery=delivery_int, bulto_extra=bulto_count,
                largo_ft=largo, ancho_ft=ancho, alto_ft=alto,
            ))
        except Exception as e:
            errors.append(f"{row_label}: dato inválido ({e}).")

    return deliveries, errors
