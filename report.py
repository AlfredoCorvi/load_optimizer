"""
Generación del reporte PDF: portada + comparación humano vs algoritmo +
una página por caja con su vista 3D y la tabla de deliveries que contiene.
"""
from __future__ import annotations
from typing import List
import io
import datetime

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
)
from reportlab.lib.enums import TA_CENTER

from models import PackingResult
from visualization import matplotlib_trailer_image

styles = getSampleStyleSheet()
STYLE_TITLE = ParagraphStyle("TitleBig", parent=styles["Title"], fontSize=22, spaceAfter=6)
STYLE_SUB = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#555555"))
STYLE_H2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
STYLE_H3 = ParagraphStyle("H3", parent=styles["Heading3"], spaceBefore=8, spaceAfter=4)
STYLE_BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9.5, leading=13)
STYLE_CENTER = ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER)


def _summary_table_data(result: PackingResult):
    data = [["Caja #", "Piezas", "% piso usado", "Largo usado (ft)"]]
    for t in result.trailers:
        data.append([str(t.index), str(len(t.items)), f"{t.utilization_pct:.1f}%", f"{t.used_length_ft:.1f}"])
    return data


def _deliveries_table_for_trailer(trailer) -> Table:
    header = ["Delivery", "Modelo", "Bulto extra", "Largo orig. (ft)", "Largo efect. (ft)", "Ancho (ft)"]
    data = [header]
    for item in sorted(trailer.items, key=lambda p: p.x_ft):
        d = item.delivery
        data.append([
            str(d.delivery), d.modelo, str(d.bulto_extra or 0),
            f"{d.largo_ft:.2f}", f"{d.largo_efectivo_ft:.2f}", f"{d.ancho_ft:.2f}",
        ])
    t = Table(data, colWidths=[0.8 * inch, 1.4 * inch, 0.8 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_comparison_table(human: PackingResult, algo: PackingResult) -> Table:
    data = [
        ["Métrica", "Acomodo manual (simulado)", "Algoritmo (optimizado)", "Diferencia"],
        ["Cajas utilizadas", str(human.n_trailers), str(algo.n_trailers), str(human.n_trailers - algo.n_trailers)],
        ["Órdenes embarcadas", str(human.n_placed), str(algo.n_placed), str(algo.n_placed - human.n_placed)],
        ["Órdenes fuera de la caja", str(human.n_unplaced), str(algo.n_unplaced), str(human.n_unplaced - algo.n_unplaced)],
        ["Aprovechamiento promedio de piso", f"{human.avg_utilization_pct:.1f}%", f"{algo.avg_utilization_pct:.1f}%",
         f"{algo.avg_utilization_pct - human.avg_utilization_pct:+.1f} pp"],
    ]
    t = Table(data, colWidths=[2.3 * inch, 1.9 * inch, 1.9 * inch, 1.4 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
    ]))
    return t


def build_pdf_report(output_path: str, human: PackingResult, algo: PackingResult,
                      empresa: str = "", notas: str = "") -> str:
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    story = []

    # Portada
    story.append(Paragraph("Reporte de Optimización de Embarques", STYLE_TITLE))
    if empresa:
        story.append(Paragraph(empresa, STYLE_SUB))
    story.append(Paragraph(f"Generado el {datetime.date.today().strftime('%d/%m/%Y')}", STYLE_SUB))
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Este reporte compara el acomodo de cargadoras dentro de cajas secas de 53' obtenido "
        "de forma manual (simulando el criterio típico de una persona armando la carga en el "
        "orden de la lista de deliveries) contra el acomodo generado por el algoritmo de "
        "optimización, que evalúa distintas combinaciones de orden y ajuste para maximizar el "
        "número de órdenes embarcadas y el uso del piso de cada caja.", STYLE_BODY))
    story.append(Spacer(1, 16))
    story.append(Paragraph("Resumen comparativo", STYLE_H2))
    story.append(build_comparison_table(human, algo))
    story.append(Spacer(1, 10))

    ahorro_cajas = human.n_trailers - algo.n_trailers
    mejora_ordenes = algo.n_placed - human.n_placed
    conclusion = (
        f"El algoritmo utilizó {algo.n_trailers} caja(s) contra {human.n_trailers} del acomodo manual "
        f"({'ahorro de ' + str(ahorro_cajas) + ' caja(s)' if ahorro_cajas > 0 else 'mismo número de cajas' if ahorro_cajas == 0 else 'usó ' + str(-ahorro_cajas) + ' caja(s) más'}), "
        f"y embarcó {algo.n_placed} órdenes contra {human.n_placed} "
        f"({'+' if mejora_ordenes >= 0 else ''}{mejora_ordenes} órdenes), dejando {algo.n_unplaced} orden(es) fuera "
        f"en lugar de {human.n_unplaced}."
    )
    story.append(Paragraph(conclusion, STYLE_BODY))
    if notas:
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>Notas:</b> {notas}", STYLE_BODY))

    if human.unplaced or algo.unplaced:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Órdenes que quedaron fuera (algoritmo optimizado)", STYLE_H3))
        if algo.unplaced:
            data = [["Delivery", "Modelo", "Largo (ft)", "Ancho (ft)"]]
            for d in algo.unplaced:
                data.append([str(d.delivery), d.modelo, f"{d.largo_ft:.2f}", f"{d.ancho_ft:.2f}"])
            tbl = Table(data, colWidths=[1.2 * inch, 2.2 * inch, 1.3 * inch, 1.3 * inch])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#a94442")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            story.append(tbl)
        else:
            story.append(Paragraph("Ninguna — todas las órdenes se embarcaron.", STYLE_BODY))

    story.append(PageBreak())

    # Detalle por caja (algoritmo optimizado)
    story.append(Paragraph("Detalle de acomodo por caja — Algoritmo (optimizado)", STYLE_H2))
    for trailer in algo.trailers:
        img_bytes = matplotlib_trailer_image(trailer, show_title=False)
        img = Image(io.BytesIO(img_bytes), width=6.3 * inch, height=3.85 * inch)
        block = [
            Paragraph(f"Caja #{trailer.index} · {len(trailer.items)} piezas · "
                      f"{trailer.utilization_pct:.1f}% de piso usado · "
                      f"{trailer.used_length_ft:.1f} / {trailer.length_ft:.0f} ft de largo usados", STYLE_H3),
            img,
            Spacer(1, 4),
            _deliveries_table_for_trailer(trailer),
            Spacer(1, 14),
        ]
        story.append(KeepTogether(block))

    doc.build(story)
    return output_path
