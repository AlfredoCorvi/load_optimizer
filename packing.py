"""
Motor de empaquetado 2D para cargadoras dentro de cajas secas de 53'.

Como el producto no se puede apilar (alto no restringe el acomodo),
el problema se reduce a un "2D bin packing" sobre el piso de la caja:
  eje X -> largo de la caja (53 ft)
  eje Y -> ancho de la caja (~8.3 ft, cabe en 2 filas)

Se implementan dos métodos para poder comparar:

1. `pack_algorithm` -> heurística MaxRects (Best Area Fit) multi-contenedor,
   probando varias estrategias de orden de piezas, y luego una fase de
   CONSOLIDACIÓN que intenta vaciar las cajas menos llenas moviendo sus
   piezas a otras cajas ya abiertas (reduce el número total de cajas usadas
   más allá de lo que logra cada estrategia por sí sola). Al final se queda
   con la mejor combinación (menos cajas / menos piezas fuera / mayor
   aprovechamiento).

2. `pack_manual_assignment` -> arma el resultado a partir de la asignación de
   caja que el propio usuario definió en su Excel (columna 'Caja': 1, 2, 3...).
   Cada pieza se acomoda dentro de la caja física que se le asignó (con el
   mismo motor MaxRects, pero limitado a esa sola caja, sin mover piezas
   entre cajas); si alguna pieza no cabe físicamente en la caja que se le
   asignó, se reporta como 'fuera de caja'. Sirve como línea base real (no
   simulada) para comparar contra el algoritmo.

Ambos métodos aceptan `min_fill_pct`: el % mínimo de largo de la caja que
debe quedar ocupado para que valga la pena embarcarla. Las cajas que no
alcanzan ese mínimo no se cuentan como embarcadas: sus piezas pasan a la
lista `rezagadas` del resultado (pendientes de consolidar con el siguiente
pedido), separado de `unplaced` (piezas que ni siquiera cupieron en ninguna
caja).
"""
from __future__ import annotations
from collections import defaultdict
from typing import List, Tuple

from models import Delivery, PlacedItem, TrailerLoad, PackingResult, DEFAULT_GAP_FT, DEFAULT_WALL_MARGIN_FT


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------
# El multiplicador por "bulto extra" ya vive en Delivery.largo_efectivo_ft
# (largo_ft * bulto_extra cuando bulto_extra > 0), así que el motor de
# empaque simplemente usa esa propiedad en vez de largo_ft directo.


class FreeRect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def area(self):
        return self.w * self.h


class Bin:
    """Contenedor (caja seca) con lista de rectángulos libres estilo MaxRects."""

    def __init__(self, length_ft: float, width_ft: float, height_ft: float, gap: float, margin: float):
        self.length_ft = length_ft
        self.width_ft = width_ft
        self.height_ft = height_ft
        self.gap = gap
        self.margin = margin
        usable_l = length_ft - 2 * margin
        usable_w = width_ft - 2 * margin
        self.origin = (margin, margin)
        self.free_rects: List[FreeRect] = [FreeRect(margin, margin, usable_l, usable_w)]
        self.placed: List[PlacedItem] = []

    def _find_position(self, w: float, h: float) -> Tuple[FreeRect, bool]:
        """Best Area Fit: busca el rectángulo libre que deje menos desperdicio.
        Prueba también la pieza rotada 90° si eso mejora el ajuste."""
        best_rect, best_rotated, best_score = None, False, None
        for fr in self.free_rects:
            for rotated, (rw, rh) in ((False, (w, h)), (True, (h, w))):
                if rw <= fr.w + 1e-9 and rh <= fr.h + 1e-9:
                    leftover = fr.area - rw * rh
                    if best_score is None or leftover < best_score:
                        best_score = leftover
                        best_rect = fr
                        best_rotated = rotated
        return best_rect, best_rotated

    def try_place(self, delivery: Delivery, allow_rotation: bool) -> bool:
        w = delivery.largo_efectivo_ft + self.gap
        h = delivery.ancho_ft + self.gap

        if allow_rotation:
            fr, rotated = self._find_position(w, h)
        else:
            # solo orientación "natural": largo a lo largo de la caja
            fr, rotated = None, False
            best_score = None
            for cand in self.free_rects:
                if w <= cand.w + 1e-9 and h <= cand.h + 1e-9:
                    leftover = cand.area - w * h
                    if best_score is None or leftover < best_score:
                        best_score = leftover
                        fr = cand
            rotated = False

        if fr is None:
            return False

        place_w, place_h = (h, w) if rotated else (w, h)
        px, py = fr.x, fr.y
        self._split_free_rect(fr, place_w, place_h)

        if rotated:
            # al rotar, "largo" físico de la pieza queda en Y
            item = PlacedItem(
                delivery=delivery, x_ft=px, y_ft=py,
                largo_ft=delivery.ancho_ft, ancho_ft=delivery.largo_efectivo_ft,
                alto_ft=delivery.alto_ft, rotated=True,
            )
        else:
            item = PlacedItem(
                delivery=delivery, x_ft=px, y_ft=py,
                largo_ft=delivery.largo_efectivo_ft, ancho_ft=delivery.ancho_ft,
                alto_ft=delivery.alto_ft, rotated=False,
            )
        self.placed.append(item)
        return True

    def _split_free_rect(self, used: FreeRect, w: float, h: float):
        """Algoritmo MaxRects: remueve el rect usado, genera nuevos rects
        libres a partir de cada rect que intersecta el área ocupada, y
        poda los que quedan contenidos dentro de otro."""
        placed_rect = (used.x, used.y, w, h)
        new_free: List[FreeRect] = []
        for fr in self.free_rects:
            if not self._intersects(fr, placed_rect):
                new_free.append(fr)
                continue
            new_free.extend(self._split_against(fr, placed_rect))
        # poda de rectángulos contenidos en otros (evita explosión de rects)
        pruned: List[FreeRect] = []
        for i, a in enumerate(new_free):
            contained = False
            for j, b in enumerate(new_free):
                if i != j and self._contains(b, a):
                    contained = True
                    break
            if not contained and a.w > 1e-6 and a.h > 1e-6:
                pruned.append(a)
        self.free_rects = pruned

    @staticmethod
    def _intersects(fr: "FreeRect", rect) -> bool:
        rx, ry, rw, rh = rect
        return not (rx >= fr.x + fr.w - 1e-9 or rx + rw <= fr.x + 1e-9 or
                    ry >= fr.y + fr.h - 1e-9 or ry + rh <= fr.y + 1e-9)

    @staticmethod
    def _contains(b: "FreeRect", a: "FreeRect") -> bool:
        return (a.x >= b.x - 1e-9 and a.y >= b.y - 1e-9 and
                a.x + a.w <= b.x + b.w + 1e-9 and a.y + a.h <= b.y + b.h + 1e-9)

    @staticmethod
    def _split_against(fr: "FreeRect", rect) -> List["FreeRect"]:
        rx, ry, rw, rh = rect
        out = []
        # arriba
        if ry > fr.y + 1e-9:
            out.append(FreeRect(fr.x, fr.y, fr.w, ry - fr.y))
        # abajo
        if ry + rh < fr.y + fr.h - 1e-9:
            out.append(FreeRect(fr.x, ry + rh, fr.w, (fr.y + fr.h) - (ry + rh)))
        # izquierda
        if rx > fr.x + 1e-9:
            out.append(FreeRect(fr.x, fr.y, rx - fr.x, fr.h))
        # derecha
        if rx + rw < fr.x + fr.w - 1e-9:
            out.append(FreeRect(rx + rw, fr.y, (fr.x + fr.w) - (rx + rw), fr.h))
        return out

    def length_utilization_pct(self) -> float:
        if not self.placed or self.length_ft <= 0:
            return 0.0
        used_length = max(p.x_ft + p.largo_ft for p in self.placed)
        return 100.0 * used_length / self.length_ft


def _bin_to_trailerload(b: Bin, idx: int) -> TrailerLoad:
    return TrailerLoad(
        index=idx, length_ft=b.length_ft, width_ft=b.width_ft, height_ft=b.height_ft,
        items=list(b.placed),
    )


def _avg_bin_utilization(bins: List[Bin]) -> float:
    if not bins:
        return 0.0
    return sum(b.length_utilization_pct() for b in bins) / len(bins)


# ---------------------------------------------------------------------------
# Consolidación: intenta vaciar las cajas menos llenas hacia otras cajas ya
# abiertas, para reducir el número total de cajas usadas.
# ---------------------------------------------------------------------------

def _consolidate_bins(bins: List[Bin], allow_rotation: bool) -> List[Bin]:
    """Ordena las cajas de menor a mayor % de largo usado y, empezando por la
    menos llena, intenta reubicar sus piezas en las demás cajas ya abiertas
    (drenado parcial: mueve las que sí quepan, no exige mover todas). Si
    logra vaciarla por completo, la elimina (una caja menos). Si le quedan
    piezas sin poder mover, reconstruye esa caja de forma compacta solo con
    lo que le quedó, para que su espacio libre sea válido para la siguiente
    ronda. Repite mientras algo siga mejorando."""
    bins = list(bins)
    changed = True
    while changed and len(bins) > 1:
        changed = False
        candidate = min(bins, key=lambda b: b.length_utilization_pct())
        others = [b for b in bins if b is not candidate]

        remaining_deliveries = []
        moved_any = False
        for item in list(candidate.placed):
            moved = False
            for b in others:
                if b.try_place(item.delivery, allow_rotation):
                    moved = True
                    moved_any = True
                    break
            if not moved:
                remaining_deliveries.append(item.delivery)

        if not moved_any:
            break  # ninguna caja logra drenar más a la candidata; ya es el mejor acomodo posible

        if not remaining_deliveries:
            bins.remove(candidate)
        else:
            # reconstruye la caja candidata de forma compacta con lo que le quedó,
            # para que sus rectángulos libres queden consistentes
            rebuilt = Bin(candidate.length_ft, candidate.width_ft, candidate.height_ft,
                          candidate.gap, candidate.margin)
            for d in remaining_deliveries:
                rebuilt.try_place(d, allow_rotation)
            idx = bins.index(candidate)
            bins[idx] = rebuilt
        changed = True
    return bins


# ---------------------------------------------------------------------------
# Filtro de llenado mínimo: cajas que no alcanzan el % mínimo configurado no
# se consideran para embarcar; sus piezas quedan "rezagadas".
# ---------------------------------------------------------------------------

def _split_by_min_fill(trailers: List[TrailerLoad], min_fill_pct: float) -> Tuple[List[TrailerLoad], List[Delivery]]:
    if not min_fill_pct or min_fill_pct <= 0:
        return trailers, []

    shipped: List[TrailerLoad] = []
    rezagadas: List[Delivery] = []
    for t in trailers:
        if t.utilization_pct + 1e-9 >= min_fill_pct:
            shipped.append(t)
        else:
            rezagadas.extend(item.delivery for item in t.items)

    reindexed = [
        TrailerLoad(index=i + 1, length_ft=t.length_ft, width_ft=t.width_ft, height_ft=t.height_ft, items=t.items)
        for i, t in enumerate(shipped)
    ]
    return reindexed, rezagadas


# ---------------------------------------------------------------------------
# Método 1: algoritmo optimizado (MaxRects + varias estrategias + consolidación)
# ---------------------------------------------------------------------------

def _pack_once(order: List[Delivery], length_ft, width_ft, height_ft, gap, margin,
                allow_rotation: bool) -> Tuple[List[Bin], List[Delivery]]:
    bins: List[Bin] = []
    unplaced: List[Delivery] = []
    for d in order:
        placed = False
        for b in bins:
            if b.try_place(d, allow_rotation):
                placed = True
                break
        if not placed:
            nb = Bin(length_ft, width_ft, height_ft, gap, margin)
            if nb.try_place(d, allow_rotation):
                bins.append(nb)
                placed = True
        if not placed:
            unplaced.append(d)
    return bins, unplaced


def pack_algorithm(deliveries: List[Delivery], length_ft: float, width_ft: float, height_ft: float,
                    gap: float = DEFAULT_GAP_FT, margin: float = DEFAULT_WALL_MARGIN_FT,
                    allow_rotation: bool = True, min_fill_pct: float = 0.0) -> PackingResult:
    """Empaca probando varias estrategias de orden, consolida cada resultado
    (vacía las cajas menos llenas hacia las demás) y se queda con la mejor
    combinación (menos cajas, luego menos piezas sin embarcar, luego mayor
    aprovechamiento). Al final aplica el % mínimo de llenado: las cajas que
    no lo alcanzan pasan a 'rezagadas' en vez de contarse como embarcadas."""
    items = list(deliveries)
    if not items:
        return PackingResult(method_name="Algoritmo (optimizado)", trailers=[], unplaced=[], rezagadas=[])

    strategies = {
        "area_desc": sorted(items, key=lambda d: d.area_ft2, reverse=True),
        "largo_desc": sorted(items, key=lambda d: d.largo_efectivo_ft, reverse=True),
        "ancho_desc_largo_desc": sorted(items, key=lambda d: (d.ancho_ft, d.largo_efectivo_ft), reverse=True),
        "perimetro_desc": sorted(items, key=lambda d: 2 * (d.largo_efectivo_ft + d.ancho_ft), reverse=True),
    }

    best = None
    for name, order in strategies.items():
        bins, unplaced = _pack_once(order, length_ft, width_ft, height_ft, gap, margin, allow_rotation)
        bins = _consolidate_bins(bins, allow_rotation)
        score = (len(bins), len(unplaced), -_avg_bin_utilization(bins))
        if best is None or score < best[0]:
            best = (score, name, bins, unplaced)

    _, best_name, bins, unplaced = best
    trailers_all = [_bin_to_trailerload(b, i + 1) for i, b in enumerate(bins)]
    shipped, rezagadas = _split_by_min_fill(trailers_all, min_fill_pct)

    return PackingResult(method_name=f"Algoritmo (optimizado · estrategia: {best_name})",
                          trailers=shipped, unplaced=unplaced, rezagadas=rezagadas)


# ---------------------------------------------------------------------------
# Método 2: acomodo manual real, según la asignación de caja del usuario
# ---------------------------------------------------------------------------

def pack_manual_assignment(deliveries_with_caja: List[Tuple[Delivery, int]],
                            length_ft: float, width_ft: float, height_ft: float,
                            gap: float = DEFAULT_GAP_FT, margin: float = DEFAULT_WALL_MARGIN_FT,
                            allow_rotation: bool = True, min_fill_pct: float = 0.0) -> PackingResult:
    """Arma el resultado 'manual' a partir de la asignación de caja que el
    usuario definió en su propio excel (columna 'Caja': 1, 2, 3...). Agrupa
    las piezas por número de caja y las coloca dentro de esa caja física, en
    el orden en que vienen en el archivo (sin mover piezas entre cajas, para
    respetar tal cual la decisión del usuario). Si alguna pieza no cabe en
    la caja que se le asignó, se reporta como 'fuera de caja'. Al final
    aplica el mismo % mínimo de llenado que el algoritmo, para que la
    comparación sea justa: cajas manuales que no alcanzan el mínimo también
    pasan a 'rezagadas'."""
    groups: dict = defaultdict(list)
    for d, caja_num in deliveries_with_caja:
        groups[caja_num].append(d)

    trailers_all: List[TrailerLoad] = []
    unplaced: List[Delivery] = []

    for caja_num in sorted(groups.keys()):
        b = Bin(length_ft, width_ft, height_ft, gap, margin)
        for d in groups[caja_num]:
            if not b.try_place(d, allow_rotation):
                unplaced.append(d)
        trailer = _bin_to_trailerload(b, caja_num)
        if trailer.items:
            trailers_all.append(trailer)

    shipped, rezagadas = _split_by_min_fill(trailers_all, min_fill_pct)

    return PackingResult(method_name="Acomodo manual (tu asignación por caja)",
                          trailers=shipped, unplaced=unplaced, rezagadas=rezagadas)
