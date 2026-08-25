"""
Optimizador de Embarques — Streamlit app
Calcula el mejor acomodo posible con el algoritmo de optimización y lo
compara contra el acomodo manual real que el usuario ya armó (subiendo un
Excel con la columna 'Caja' indicando a qué caja va cada delivery).
"""
import tempfile
import os

import streamlit as st
import pandas as pd

from models import (
    TRAILER_LENGTH_FT_DEFAULT, TRAILER_WIDTH_FT_DEFAULT, TRAILER_HEIGHT_FT_DEFAULT,
    DEFAULT_GAP_FT, DEFAULT_WALL_MARGIN_FT,
)
from data_io import (
    empty_dataframe, sample_dataframe, make_template_excel_bytes,
    read_excel_to_dataframe, dataframe_to_deliveries, COLUMN_LABELS,
    read_excel_manual_to_dataframe, dataframe_to_deliveries_with_caja,
)
from packing import pack_algorithm, pack_manual_assignment
from visualization import plotly_trailer_figure, comparison_bar_figure
from report import build_pdf_report

st.set_page_config(page_title="Optimizador de Embarques 53'", layout="wide", page_icon="🚚")

# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
if "df" not in st.session_state:
    st.session_state.df = empty_dataframe()
if "result_algo" not in st.session_state:
    st.session_state.result_algo = None
if "result_manual" not in st.session_state:
    st.session_state.result_manual = None
if "manual_items_caja" not in st.session_state:
    st.session_state.manual_items_caja = None

st.title("🚚 Optimizador de Embarques — Cajas Secas 53'")
st.caption(
    "Reduce el número de cajas de 53' usadas para embarcar cargadoras en tarimas, "
    "comparando tu acomodo manual real contra un algoritmo de optimización."
)

# ---------------------------------------------------------------------------
# Barra lateral: parámetros de la caja
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Parámetros de la caja")
    length_ft = st.number_input("Largo interior (ft)", value=TRAILER_LENGTH_FT_DEFAULT, min_value=10.0, step=0.5)
    width_ft = st.number_input("Ancho interior (ft)", value=TRAILER_WIDTH_FT_DEFAULT, min_value=4.0, step=0.1)
    height_ft = st.number_input("Alto interior (ft)", value=TRAILER_HEIGHT_FT_DEFAULT, min_value=4.0, step=0.5,
                                 help="No limita el acomodo porque el producto no se apila, pero se usa para la vista 3D.")

    st.markdown("---")
    st.header("🧩 Reglas de acomodo")
    st.caption(
        "El **bulto extra** se captura con la letra 'y' repetida en la tabla "
        "('y' = 1 bulto extra, 'yy' = 2, 'yyy' = 3, ...) y vacío = sin bulto extra. "
        "Esa cantidad multiplica el largo de la pieza al calcular el espacio que ocupa."
    )
    allow_rotation = st.checkbox(
        "Permitir rotar piezas 90° si mejora el acomodo", value=True,
        help="Si se desactiva, todas las piezas se acomodan con el largo alineado al largo de la caja.")
    gap_ft = st.number_input("Separación entre piezas (ft)", value=DEFAULT_GAP_FT, min_value=0.0, step=0.05, format="%.2f")
    margin_ft = st.number_input("Margen contra pared (ft)", value=DEFAULT_WALL_MARGIN_FT, min_value=0.0, step=0.05, format="%.2f")

    st.markdown("---")
    st.header("📉 Llenado mínimo por caja")
    min_fill_pct = st.slider(
        "% mínimo de largo ocupado para embarcar una caja", min_value=0, max_value=95, value=0, step=5,
        help="Si una caja no alcanza este % de su largo ocupado, no se cuenta como embarcada: sus "
             "órdenes pasan a 'rezagadas' (pendientes de consolidar con el siguiente pedido). "
             "0 = sin mínimo, se embarca cualquier caja con al menos una pieza.")
    if min_fill_pct > 0:
        st.caption(f"Solo se embarcarán cajas con **{min_fill_pct}% o más** de su largo ocupado.")
    else:
        st.caption("Sin mínimo configurado: se embarca cualquier caja con al menos una pieza.")

    st.markdown("---")
    st.caption("El producto puede ir en 2 filas a lo ancho de la caja; el alto no restringe porque no se apila.")

# ---------------------------------------------------------------------------
# Entrada de datos para el algoritmo
# ---------------------------------------------------------------------------
st.header("1️⃣ Datos de las cargadoras")
tab_excel, tab_manual_entry = st.tabs(["📤 Subir Excel", "✍️ Captura manual"])

with tab_excel:
    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader("Sube el Excel con los deliveries", type=["xlsx", "xls"], key="uploader_algo")
    with col2:
        st.write("")
        st.write("")
        st.download_button("⬇️ Descargar plantilla", data=make_template_excel_bytes(),
                            file_name="plantilla_deliveries.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_template_main")
    st.caption("Columnas requeridas: " + ", ".join(v for k, v in COLUMN_LABELS.items() if k != "caja")
               + ". Si el excel ya trae la columna 'Caja', se ignora aquí.")

    if uploaded is not None:
        try:
            df_loaded = read_excel_to_dataframe(uploaded)
            st.session_state.df = df_loaded
            st.success(f"Se cargaron {len(df_loaded)} filas del Excel.")
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")

with tab_manual_entry:
    st.caption("Captura o edita los deliveries directamente en la tabla (doble clic para editar, + para agregar filas).")
    colb1, colb2 = st.columns([1, 1])
    with colb1:
        if st.button("➕ Cargar 6 filas de ejemplo"):
            st.session_state.df = sample_dataframe(6)
    with colb2:
        if st.button("🗑️ Vaciar tabla"):
            st.session_state.df = empty_dataframe()

edited_df = st.data_editor(
    st.session_state.df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "modelo": st.column_config.TextColumn("Modelo"),
        "delivery": st.column_config.NumberColumn("Delivery", format="%d"),
        "bulto_extra": st.column_config.TextColumn(
            "Bulto extra", help="Escribe 'y' por cada bulto extra: y = 1, yy = 2, yyy = 3... Vacío = sin bulto extra."),
        "largo_ft": st.column_config.NumberColumn("Largo (ft)", format="%.2f"),
        "ancho_ft": st.column_config.NumberColumn("Ancho (ft)", format="%.2f"),
        "alto_ft": st.column_config.NumberColumn("Alto (ft)", format="%.2f"),
    },
    key="editor",
)
st.session_state.df = edited_df

# ---------------------------------------------------------------------------
# Ejecutar algoritmo
# ---------------------------------------------------------------------------
st.header("2️⃣ Calcular mejor acomodo")
run = st.button("🚀 Calcular mejor acomodo", type="primary")

if run:
    deliveries, errors = dataframe_to_deliveries(st.session_state.df)
    if errors:
        with st.expander(f"⚠️ {len(errors)} fila(s) con problemas (se ignoraron)", expanded=True):
            for e in errors:
                st.write("- " + e)
    if not deliveries:
        st.warning("No hay deliveries válidos para procesar.")
    else:
        with st.spinner(f"Optimizando acomodo de {len(deliveries)} deliveries..."):
            result_algo = pack_algorithm(
                deliveries, length_ft, width_ft, height_ft,
                gap=gap_ft, margin=margin_ft,
                allow_rotation=allow_rotation, min_fill_pct=min_fill_pct,
            )
        st.session_state.result_algo = result_algo
        # si ya había un acomodo manual cargado de una corrida anterior, se
        # limpia para evitar comparar contra un input de deliveries distinto
        st.session_state.result_manual = None
        st.session_state.manual_items_caja = None
        st.session_state.n_input = len(deliveries)

# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------
if st.session_state.result_algo is not None:
    algo = st.session_state.result_algo

    st.markdown("---")
    st.header("3️⃣ Comparar contra tu acomodo manual")
    st.caption(
        "Sube el Excel de tu acomodo manual ya armado, usando la misma plantilla, "
        "agregando en la columna **Caja** el número de caja (1, 2, 3...) al que "
        "asignaste cada delivery."
    )
    colm1, colm2 = st.columns([2, 1])
    with colm1:
        uploaded_manual = st.file_uploader(
            "Sube el Excel de tu acomodo manual (con columna 'Caja')",
            type=["xlsx", "xls"], key="uploader_manual")
    with colm2:
        st.write("")
        st.write("")
        st.download_button("⬇️ Descargar plantilla", data=make_template_excel_bytes(),
                            file_name="plantilla_deliveries.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_template_manual")

    if uploaded_manual is not None:
        try:
            df_manual = read_excel_manual_to_dataframe(uploaded_manual)
            items_caja, errors_manual = dataframe_to_deliveries_with_caja(df_manual)
            if errors_manual:
                with st.expander(f"⚠️ {len(errors_manual)} fila(s) con problemas (se ignoraron)", expanded=True):
                    for e in errors_manual:
                        st.write("- " + e)
            if not items_caja:
                st.warning("No hay filas válidas con asignación de caja en ese Excel.")
            else:
                st.session_state.manual_items_caja = items_caja
                st.success(f"Se cargó tu acomodo manual: {len(items_caja)} deliveries asignados a caja.")
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")

    # recalcula el acomodo manual con los parámetros actuales de la barra
    # lateral (largo mínimo, rotación, etc.) cada vez que algo cambie, sin
    # necesidad de volver a subir el excel
    if st.session_state.manual_items_caja is not None:
        st.session_state.result_manual = pack_manual_assignment(
            st.session_state.manual_items_caja, length_ft, width_ft, height_ft,
            gap=gap_ft, margin=margin_ft, allow_rotation=allow_rotation,
            min_fill_pct=min_fill_pct,
        )

    manual = st.session_state.result_manual

    st.markdown("---")
    st.subheader("📊 Resumen")
    if manual is not None:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Cajas — manual", manual.n_trailers)
        m1.metric("Cajas — algoritmo", algo.n_trailers, delta=algo.n_trailers - manual.n_trailers, delta_color="inverse")
        m2.metric("Órdenes embarcadas — manual", manual.n_placed)
        m2.metric("Órdenes embarcadas — algoritmo", algo.n_placed, delta=algo.n_placed - manual.n_placed)
        m3.metric("Rezagadas (caja no llegó al mínimo) — manual", manual.n_rezagadas)
        m3.metric("Rezagadas (caja no llegó al mínimo) — algoritmo", algo.n_rezagadas,
                  delta=algo.n_rezagadas - manual.n_rezagadas, delta_color="inverse")
        m4.metric("Fuera de caja — manual", manual.n_unplaced)
        m4.metric("Fuera de caja — algoritmo", algo.n_unplaced, delta=algo.n_unplaced - manual.n_unplaced, delta_color="inverse")
        m5.metric("% de largo usado (prom.) — manual", f"{manual.avg_utilization_pct:.1f}%")
        m5.metric("% de largo usado (prom.) — algoritmo", f"{algo.avg_utilization_pct:.1f}%",
                  delta=f"{algo.avg_utilization_pct - manual.avg_utilization_pct:+.1f} pp")

        colA, colB = st.columns(2)
        with colA:
            st.plotly_chart(
                comparison_bar_figure(["Cajas usadas", "Rezagadas", "Fuera de caja"],
                                       [manual.n_trailers, manual.n_rezagadas, manual.n_unplaced],
                                       [algo.n_trailers, algo.n_rezagadas, algo.n_unplaced],
                                       "Cajas usadas, rezagadas y fuera", "cantidad"),
                use_container_width=True,
            )
        with colB:
            labels = [f"Caja {i+1}" for i in range(max(manual.n_trailers, algo.n_trailers))]
            mv = [manual.trailers[i].utilization_pct if i < len(manual.trailers) else 0 for i in range(len(labels))]
            av = [algo.trailers[i].utilization_pct if i < len(algo.trailers) else 0 for i in range(len(labels))]
            st.plotly_chart(
                comparison_bar_figure(labels, mv, av, "% de largo de la caja usado", "% utilización"),
                use_container_width=True,
            )
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Cajas — algoritmo", algo.n_trailers)
        m2.metric("Órdenes embarcadas — algoritmo", algo.n_placed)
        m3.metric("Rezagadas (caja no llegó al mínimo) — algoritmo", algo.n_rezagadas)
        m4.metric("% de largo usado (prom.) — algoritmo", f"{algo.avg_utilization_pct:.1f}%")
        st.info("Sube tu acomodo manual arriba para ver la comparación completa.")

    st.markdown("---")
    st.subheader("📦 Detalle 3D por caja")
    opciones_metodo = ["Algoritmo (optimizado)"]
    if manual is not None:
        opciones_metodo.append("Acomodo manual (tu asignación)")
    metodo = st.radio("Ver acomodo de:", opciones_metodo, horizontal=True)
    result_shown = algo if metodo.startswith("Algoritmo") else manual

    if result_shown and result_shown.trailers:
        idx = st.selectbox("Selecciona la caja", list(range(1, len(result_shown.trailers) + 1)),
                            format_func=lambda i: f"Caja #{i} — {len(result_shown.trailers[i-1].items)} piezas")
        trailer = result_shown.trailers[idx - 1]
        st.plotly_chart(plotly_trailer_figure(trailer), use_container_width=True)

        rows = []
        for item in sorted(trailer.items, key=lambda p: p.x_ft):
            rows.append({
                "Delivery": item.delivery.delivery, "Modelo": item.delivery.modelo,
                "Bulto extra": item.delivery.bulto_extra or 0,
                "Largo original (ft)": round(item.delivery.largo_ft, 2),
                "Largo efectivo (ft)": round(item.delivery.largo_efectivo_ft, 2),
                "Ancho (ft)": round(item.ancho_ft, 2),
                "Alto (ft)": round(item.alto_ft, 2), "Rotada": "Sí" if item.rotated else "No",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Este método no generó cajas todavía.")

    if result_shown and result_shown.unplaced:
        with st.expander(f"🚫 {len(result_shown.unplaced)} orden(es) que quedaron fuera de la caja (no cupieron)"):
            rows = [{"Delivery": d.delivery, "Modelo": d.modelo, "Largo (ft)": d.largo_ft, "Ancho (ft)": d.ancho_ft}
                    for d in result_shown.unplaced]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if result_shown and result_shown.rezagadas:
        with st.expander(f"📉 {len(result_shown.rezagadas)} orden(es) rezagadas (su caja no alcanzó el {min_fill_pct}% mínimo)"):
            rows = [{"Delivery": d.delivery, "Modelo": d.modelo, "Largo (ft)": d.largo_ft, "Ancho (ft)": d.ancho_ft}
                    for d in result_shown.rezagadas]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # -----------------------------------------------------------------------
    # Reporte PDF
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("📄 Reporte PDF")
    if manual is None:
        st.caption("El reporte incluirá solo el acomodo del algoritmo. Sube tu acomodo manual para incluir la comparación.")
    empresa = st.text_input("Nombre de la empresa / línea (opcional)", value="")
    notas = st.text_area("Notas adicionales para el reporte (opcional)", value="")

    if st.button("📥 Generar reporte PDF"):
        with st.spinner("Generando reporte PDF con vistas 3D..."):
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "reporte_embarques.pdf")
                build_pdf_report(out_path, manual, algo, empresa=empresa, notas=notas, min_fill_pct=min_fill_pct)
                with open(out_path, "rb") as f:
                    pdf_bytes = f.read()
        st.session_state.pdf_bytes = pdf_bytes
        st.success("Reporte generado.")

    if "pdf_bytes" in st.session_state:
        st.download_button("⬇️ Descargar reporte PDF", data=st.session_state.pdf_bytes,
                            file_name="reporte_optimizacion_embarques.pdf", mime="application/pdf")
else:
    st.info("Captura o sube tus deliveries y presiona **Calcular mejor acomodo** para continuar.")
