"""
Visualización 3D del acomodo de cargadoras dentro de la caja de 53'.
- plotly: vista interactiva dentro de Streamlit.
- matplotlib: imagen estática para insertar en el reporte PDF.
"""
from __future__ import annotations
from typing import List
import io

import plotly.graph_objects as go
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

from models import TrailerLoad

PALETTE = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
    "#8CD17D", "#F1CE63", "#D37295", "#79706E", "#BAB0AC",
]


def _box_faces(x, y, z, dx, dy, dz):
    """Regresa los 8 vértices de una caja para dibujarla en 3D."""
    verts = np.array([
        [x, y, z], [x + dx, y, z], [x + dx, y + dy, z], [x, y + dy, z],
        [x, y, z + dz], [x + dx, y, z + dz], [x + dx, y + dy, z + dz], [x, y + dy, z + dz],
    ])
    faces = [
        [verts[0], verts[1], verts[2], verts[3]],  # piso
        [verts[4], verts[5], verts[6], verts[7]],  # techo
        [verts[0], verts[1], verts[5], verts[4]],
        [verts[2], verts[3], verts[7], verts[6]],
        [verts[1], verts[2], verts[6], verts[5]],
        [verts[0], verts[3], verts[7], verts[4]],
    ]
    return faces


def plotly_trailer_figure(trailer: TrailerLoad, title: str = "") -> go.Figure:
    """Figura 3D interactiva de una caja con sus cargadoras acomodadas."""
    fig = go.Figure()

    # contorno de la caja (wireframe)
    L, W, H = trailer.length_ft, trailer.width_ft, trailer.height_ft
    edges = _box_faces(0, 0, 0, L, W, H)
    for i, (x, y, z, dx, dy, dz) in enumerate([(0, 0, 0, L, W, H)]):
        pass
    fig.add_trace(go.Mesh3d(
        x=[0, L, L, 0, 0, L, L, 0], y=[0, 0, W, W, 0, 0, W, W], z=[0, 0, 0, 0, H, H, H, H],
        i=[0, 0, 4, 4, 0, 0, 1, 1, 2, 2, 0, 0], j=[1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 3, 4],
        k=[2, 3, 6, 7, 5, 4, 6, 5, 7, 6, 7, 7],
        opacity=0.06, color="gray", name="Caja 53'", showlegend=False, hoverinfo="skip",
    ))

    for idx, item in enumerate(trailer.items):
        color = PALETTE[idx % len(PALETTE)]
        faces = _box_faces(item.x_ft, item.y_ft, 0, item.largo_ft, item.ancho_ft, item.alto_ft)
        xs, ys, zs = [], [], []
        i_idx, j_idx, k_idx = [], [], []
        for f in faces:
            base = len(xs)
            for v in f:
                xs.append(v[0]); ys.append(v[1]); zs.append(v[2])
            i_idx += [base, base]
            j_idx += [base + 1, base + 2]
            k_idx += [base + 2, base + 3]
        fig.add_trace(go.Mesh3d(
            x=xs, y=ys, z=zs, i=i_idx, j=j_idx, k=k_idx,
            color=color, opacity=1.0, flatshading=True,
            name=f"Delivery {item.delivery.delivery} ({item.delivery.modelo})",
            hovertext=(f"Delivery: {item.delivery.delivery}<br>Modelo: {item.delivery.modelo}<br>"
                       f"Largo: {item.largo_ft:.2f} ft<br>Ancho: {item.ancho_ft:.2f} ft"
                       f"{('<br>Bulto extra: ' + str(item.delivery.bulto_extra)) if item.delivery.bulto_extra else ''}"),
            hoverinfo="text", showlegend=False,
        ))

    fig.update_layout(
        title=title or f"Caja #{trailer.index} — {len(trailer.items)} piezas, {trailer.utilization_pct:.1f}% de largo usado",
        scene=dict(
            xaxis_title="Largo (ft)", yaxis_title="Ancho (ft)", zaxis_title="Alto (ft)",
            aspectmode="manual",
            aspectratio=dict(x=L / max(L, 1), y=(W / L) * 2.2, z=(H / L) * 2.2),
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        height=500,
    )
    return fig


def matplotlib_trailer_image(trailer: TrailerLoad, title: str = "", show_title: bool = True) -> bytes:
    """Genera un PNG estático de la caja en 3D para incrustar en el PDF."""
    fig = plt.figure(figsize=(7.2, 4.4))
    ax = fig.add_subplot(111, projection="3d")

    L, W, H = trailer.length_ft, trailer.width_ft, trailer.height_ft

    # contorno de la caja
    outline = _box_faces(0, 0, 0, L, W, H)
    box = Poly3DCollection(outline, facecolors=(0, 0, 0, 0.0), edgecolors="gray", linewidths=0.6)
    ax.add_collection3d(box)

    for idx, item in enumerate(trailer.items):
        color = PALETTE[idx % len(PALETTE)]
        faces = _box_faces(item.x_ft, item.y_ft, 0, item.largo_ft, item.ancho_ft, item.alto_ft)
        pc = Poly3DCollection(faces, facecolors=color, edgecolors="black", linewidths=0.3, alpha=0.95)
        ax.add_collection3d(pc)
        cx = item.x_ft + item.largo_ft / 2
        cy = item.y_ft + item.ancho_ft / 2
        ax.text(cx, cy, item.alto_ft + 0.05, str(item.delivery.delivery),
                 fontsize=5.5, ha="center", va="bottom")

    ax.set_xlim(0, L)
    ax.set_ylim(0, W)
    ax.set_zlim(0, max(H, 1))
    ax.set_xlabel("Largo (ft)", fontsize=8)
    ax.set_ylabel("Ancho (ft)", fontsize=8)
    ax.set_zlabel("Alto (ft)", fontsize=8)
    ax.set_box_aspect((L, W, max(H, 1)))
    ax.view_init(elev=28, azim=-60)
    ax.tick_params(labelsize=6)
    if show_title:
        ax.set_title(title or f"Caja #{trailer.index} — {len(trailer.items)} piezas · {trailer.utilization_pct:.1f}% de largo usado",
                     fontsize=9)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=170)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def comparison_bar_figure(labels, human_vals, algo_vals, title, ytitle) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Acomodo manual (simulado)", x=labels, y=human_vals, marker_color="#E45756"))
    fig.add_trace(go.Bar(name="Algoritmo (optimizado)", x=labels, y=algo_vals, marker_color="#54A24B"))
    fig.update_layout(title=title, yaxis_title=ytitle, barmode="group", height=380,
                       margin=dict(l=10, r=10, t=40, b=10))
    return fig
