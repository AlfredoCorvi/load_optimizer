"""
Optimizador de Embarques — Streamlit app
Compara el acomodo manual (simulado) contra un algoritmo de optimización
para reducir el número de cajas secas de 53' usadas al embarcar cargadoras.
"""
import io
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
)
from packing import pack_algorithm, pack_human_like
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
if "result_human" not in st.session_state:
    st.session_state.result_human = None

st.title("🚚 Optimizador de Embarques — Cajas Secas 53'")
st.caption(
    "Reduce el número de cajas de 53' usadas para embarcar cargadoras en tarimas, "
    "comparando el acomodo manual típico contra un algoritmo de optimización."
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
    st.caption("El producto puede ir en 2 filas a lo ancho de la caja; el alto no restringe porque no se apila.")

# ---------------------------------------------------------------------------
# Entrada de datos
# ---------------------------------------------------------------------------
st.header("1️⃣ Datos de las cargadoras")
tab_excel, tab_manual = st.tabs(["📤 Subir Excel", "✍️ Captura manual"])

with tab_excel:
    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader("Sube el Excel con los deliveries", type=["xlsx", "xls"])
    with col2:
        st.write("")
        st.write("")
        st.download_button("⬇️ Descargar plantilla", data=make_template_excel_bytes(),
                            file_name="plantilla_deliveries.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("Columnas requeridas: " + ", ".join(COLUMN_LABELS.values()))

    if uploaded is not None:
        try:
            df_loaded = read_excel_to_dataframe(uploaded)
            st.session_state.df = df_loaded
            st.success(f"Se cargaron {len(df_loaded)} filas del Excel.")
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")

with tab_manual:
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
# Ejecutar comparación
# ---------------------------------------------------------------------------
st.header("2️⃣ Comparar acomodo: manual vs. algoritmo")
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
            result_human = pack_human_like(
                deliveries, length_ft, width_ft, height_ft,
                gap=gap_ft, margin=margin_ft,
            )
            result_algo = pack_algorithm(
                deliveries, length_ft, width_ft, height_ft,
                gap=gap_ft, margin=margin_ft,
                allow_rotation=allow_rotation,
            )
        st.session_state.result_human = result_human
        st.session_state.result_algo = result_algo
        st.session_state.n_input = len(deliveries)

# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------
if st.session_state.result_algo is not None and st.session_state.result_human is not None:
    human = st.session_state.result_human
    algo = st.session_state.result_algo

    st.subheader("📊 Resumen comparativo")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cajas — manual", human.n_trailers)
    m1.metric("Cajas — algoritmo", algo.n_trailers, delta=algo.n_trailers - human.n_trailers, delta_color="inverse")
    m2.metric("Órdenes embarcadas — manual", human.n_placed)
    m2.metric("Órdenes embarcadas — algoritmo", algo.n_placed, delta=algo.n_placed - human.n_placed)
    m3.metric("Fuera de caja — manual", human.n_unplaced)
    m3.metric("Fuera de caja — algoritmo", algo.n_unplaced, delta=algo.n_unplaced - human.n_unplaced, delta_color="inverse")
    m4.metric("Aprovechamiento prom. — manual", f"{human.avg_utilization_pct:.1f}%")
    m4.metric("Aprovechamiento prom. — algoritmo", f"{algo.avg_utilization_pct:.1f}%",
              delta=f"{algo.avg_utilization_pct - human.avg_utilization_pct:+.1f} pp")

    colA, colB = st.columns(2)
    with colA:
        st.plotly_chart(
            comparison_bar_figure(["Cajas usadas", "Fuera de caja"],
                                   [human.n_trailers, human.n_unplaced],
                                   [algo.n_trailers, algo.n_unplaced],
                                   "Cajas usadas y órdenes fuera", "cantidad"),
            use_container_width=True,
        )
    with colB:
        labels = [f"Caja {i+1}" for i in range(max(human.n_trailers, algo.n_trailers))]
        hv = [human.trailers[i].utilization_pct if i < len(human.trailers) else 0 for i in range(len(labels))]
        av = [algo.trailers[i].utilization_pct if i < len(algo.trailers) else 0 for i in range(len(labels))]
        st.plotly_chart(
            comparison_bar_figure(labels, hv, av, "% de piso usado por caja", "% utilización"),
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("📦 Detalle 3D por caja")
    metodo = st.radio("Ver acomodo de:", ["Algoritmo (optimizado)", "Acomodo manual (simulado)"], horizontal=True)
    result_shown = algo if metodo.startswith("Algoritmo") else human

    if result_shown.trailers:
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
        st.info("Este método no generó cajas (sin deliveries válidos).")

    if result_shown.unplaced:
        with st.expander(f"🚫 {len(result_shown.unplaced)} orden(es) que quedaron fuera de la caja"):
            rows = [{"Delivery": d.delivery, "Modelo": d.modelo, "Largo (ft)": d.largo_ft, "Ancho (ft)": d.ancho_ft}
                    for d in result_shown.unplaced]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # -----------------------------------------------------------------------
    # Reporte PDF
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("📄 Reporte PDF")
    empresa = st.text_input("Nombre de la empresa / línea (opcional)", value="")
    notas = st.text_area("Notas adicionales para el reporte (opcional)", value="")

    if st.button("📥 Generar reporte PDF"):
        with st.spinner("Generando reporte PDF con vistas 3D..."):
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "reporte_embarques.pdf")
                build_pdf_report(out_path, human, algo, empresa=empresa, notas=notas)
                with open(out_path, "rb") as f:
                    pdf_bytes = f.read()
        st.session_state.pdf_bytes = pdf_bytes
        st.success("Reporte generado.")

    if "pdf_bytes" in st.session_state:
        st.download_button("⬇️ Descargar reporte PDF", data=st.session_state.pdf_bytes,
                            file_name="reporte_optimizacion_embarques.pdf", mime="application/pdf")
else:
    st.info("Captura o sube tus deliveries y presiona **Calcular mejor acomodo** para ver la comparación.")
