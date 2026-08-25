"""
Generación del reporte PDF: portada + comparación manual vs algoritmo (si hay
acomodo manual cargado) + una página por caja con su vista 3D y la tabla de
deliveries que contiene.
"""
from __future__ import annotations
from typing import Optional
import io
import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
)

from models import PackingResult
from visualization import matplotlib_trailer_image

styles = getSampleStyleSheet()
STYLE_TITLE = ParagraphStyle("TitleBig", parent=styles["Title"], fontSize=22, spaceAfter=6)
STYLE_SUB = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#555555"))
STYLE_H2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
STYLE_H3 = ParagraphStyle("H3", parent=styles["Heading3"], spaceBefore=8, spaceAfter=4)
STYLE_BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9.5, leading=13)


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


def build_comparison_table(manual: PackingResult, algo: PackingResult) -> Table:
    data = [
        ["Métrica", "Acomodo manual (tu asignación)", "Algoritmo (optimizado)", "Diferencia"],
        ["Cajas utilizadas", str(manual.n_trailers), str(algo.n_trailers), str(manual.n_trailers - algo.n_trailers)],
        ["Órdenes embarcadas", str(manual.n_placed), str(algo.n_placed), str(algo.n_placed - manual.n_placed)],
        ["Órdenes fuera de la caja", str(manual.n_unplaced), str(algo.n_unplaced), str(manual.n_unplaced - algo.n_unplaced)],
        ["% de largo de la caja usado (prom.)", f"{manual.avg_utilization_pct:.1f}%", f"{algo.avg_utilization_pct:.1f}%",
         f"{algo.avg_utilization_pct - manual.avg_utilization_pct:+.1f} pp"],
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


def _unplaced_table(deliveries, header_color="#a94442") -> Table:
    data = [["Delivery", "Modelo", "Largo (ft)", "Ancho (ft)"]]
    for d in deliveries:
        data.append([str(d.delivery), d.modelo, f"{d.largo_ft:.2f}", f"{d.ancho_ft:.2f}"])
    tbl = Table(data, colWidths=[1.2 * inch, 2.2 * inch, 1.3 * inch, 1.3 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return tbl


def _trailer_detail_blocks(result: PackingResult, heading: str):
    blocks = [Paragraph(heading, STYLE_H2)]
    for trailer in result.trailers:
        img_bytes = matplotlib_trailer_image(trailer, show_title=False)
        img = Image(io.BytesIO(img_bytes), width=6.3 * inch, height=3.85 * inch)
        block = [
            Paragraph(f"Caja #{trailer.index} · {len(trailer.items)} piezas · "
                      f"{trailer.utilization_pct:.1f}% de largo de caja usado · "
                      f"{trailer.used_length_ft:.1f} / {trailer.length_ft:.0f} ft de largo usados", STYLE_H3),
            img,
            Spacer(1, 4),
            _deliveries_table_for_trailer(trailer),
            Spacer(1, 14),
        ]
        blocks.append(KeepTogether(block))
    return blocks


def build_pdf_report(output_path: str, manual: Optional[PackingResult], algo: PackingResult,
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

    if manual is not None:
        story.append(Paragraph(
            "Este reporte compara el acomodo de cargadoras dentro de cajas secas de 53' que el "
            "usuario armó de forma manual (según la caja que le asignó a cada delivery) contra el "
            "acomodo generado por el algoritmo de optimización, que evalúa distintas combinaciones "
            "de orden y ajuste para maximizar el número de órdenes embarcadas y el largo "
            "aprovechado de cada caja.", STYLE_BODY))
        story.append(Spacer(1, 16))
        story.append(Paragraph("Resumen comparativo", STYLE_H2))
        story.append(build_comparison_table(manual, algo))
        story.append(Spacer(1, 10))

        ahorro_cajas = manual.n_trailers - algo.n_trailers
        mejora_ordenes = algo.n_placed - manual.n_placed
        conclusion = (
            f"El algoritmo utilizó {algo.n_trailers} caja(s) contra {manual.n_trailers} del acomodo manual "
            f"({'ahorro de ' + str(ahorro_cajas) + ' caja(s)' if ahorro_cajas > 0 else 'mismo número de cajas' if ahorro_cajas == 0 else 'usó ' + str(-ahorro_cajas) + ' caja(s) más'}), "
            f"y embarcó {algo.n_placed} órdenes contra {manual.n_placed} "
            f"({'+' if mejora_ordenes >= 0 else ''}{mejora_ordenes} órdenes), dejando {algo.n_unplaced} orden(es) fuera "
            f"en lugar de {manual.n_unplaced}."
        )
        story.append(Paragraph(conclusion, STYLE_BODY))
    else:
        story.append(Paragraph(
            "Este reporte muestra el acomodo de cargadoras dentro de cajas secas de 53' generado por "
            "el algoritmo de optimización. Sube tu acomodo manual (Excel con columna 'Caja') en la app "
            "para incluir aquí la comparación contra tu asignación real.", STYLE_BODY))
        story.append(Spacer(1, 16))
        resumen = [
            ["Cajas utilizadas", str(algo.n_trailers)],
            ["Órdenes embarcadas", str(algo.n_placed)],
            ["Órdenes fuera de la caja", str(algo.n_unplaced)],
            ["% de largo de la caja usado (prom.)", f"{algo.avg_utilization_pct:.1f}%"],
        ]
        tbl = Table(resumen, colWidths=[3.0 * inch, 2.0 * inch])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tbl)

    if notas:
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>Notas:</b> {notas}", STYLE_BODY))

    any_unplaced = algo.unplaced or (manual.unplaced if manual is not None else [])
    if any_unplaced:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Órdenes que quedaron fuera (algoritmo optimizado)", STYLE_H3))
        if algo.unplaced:
            story.append(_unplaced_table(algo.unplaced))
        else:
            story.append(Paragraph("Ninguna — todas las órdenes se embarcaron.", STYLE_BODY))

        if manual is not None and manual.unplaced:
            story.append(Spacer(1, 10))
            story.append(Paragraph("Órdenes que quedaron fuera (acomodo manual)", STYLE_H3))
            story.append(_unplaced_table(manual.unplaced))

    story.append(PageBreak())

    # Detalle por caja (algoritmo optimizado)
    story.extend(_trailer_detail_blocks(algo, "Detalle de acomodo por caja — Algoritmo (optimizado)"))

    # Detalle por caja (acomodo manual), si se cargó
    if manual is not None and manual.trailers:
        story.append(PageBreak())
        story.extend(_trailer_detail_blocks(manual, "Detalle de acomodo por caja — Acomodo manual (tu asignación)"))

    doc.build(story)
    return output_path
