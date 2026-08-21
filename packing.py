"""
Motor de empaquetado 2D para cargadoras dentro de cajas secas de 53'.

Como el producto no se puede apilar (alto no restringe el acomodo),
el problema se reduce a un "2D bin packing" sobre el piso de la caja:
  eje X -> largo de la caja (53 ft)
  eje Y -> ancho de la caja (~8.3 ft, cabe en 2 filas)

Se implementan dos métodos para poder comparar:

1. `pack_algorithm` -> heurística MaxRects (Best Area Fit) multi-contenedor,
   probando varias estrategias de orden de piezas y quedándose con la mejor
   (menos cajas / menos piezas fuera / mayor aprovechamiento). Esto imita
   "cómo lo haría el programa pensando en todas las combinaciones razonables".

2. `pack_human_like` -> heurística simple de "dos carriles" (izquierda/derecha
   de la caja), colocando piezas en el orden en que llegan (como normalmente
   arma la carga una persona con la lista de deliveries), sin recombinar.
   Sirve como línea base para comparar contra el algoritmo.
"""
from __future__ import annotations
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

        placed_largo = (place_w - self.gap)
        placed_ancho = (place_h - self.gap)
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


def _bin_to_trailerload(b: Bin, idx: int) -> TrailerLoad:
    return TrailerLoad(
        index=idx, length_ft=b.length_ft, width_ft=b.width_ft, height_ft=b.height_ft,
        items=list(b.placed),
    )


# ---------------------------------------------------------------------------
# Método 1: algoritmo optimizado (MaxRects + varias estrategias de orden)
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
                    gap: float = DEFAULT_GAP_FT,
                    margin: float = DEFAULT_WALL_MARGIN_FT, allow_rotation: bool = True) -> PackingResult:
    """Empaca probando varias estrategias de orden y se queda con la mejor
    combinación (menos cajas, luego menos piezas sin embarcar, luego mayor
    aprovechamiento). Esto es lo más cercano a 'probar varias combinaciones'
    manteniendo tiempos de ejecución razonables con ~100+ piezas."""
    items = list(deliveries)
    if not items:
        return PackingResult(method_name="Algoritmo (optimizado)", trailers=[], unplaced=[])

    strategies = {
        "area_desc": sorted(items, key=lambda d: d.area_ft2, reverse=True),
        "largo_desc": sorted(items, key=lambda d: d.largo_efectivo_ft, reverse=True),
        "ancho_desc_largo_desc": sorted(items, key=lambda d: (d.ancho_ft, d.largo_efectivo_ft), reverse=True),
        "perimetro_desc": sorted(items, key=lambda d: 2 * (d.largo_efectivo_ft + d.ancho_ft), reverse=True),
    }

    best = None
    for name, order in strategies.items():
        bins, unplaced = _pack_once(order, length_ft, width_ft, height_ft, gap, margin, allow_rotation)
        score = (len(bins), len(unplaced), -sum(b.placed and _bin_to_trailerload(b, 0).utilization_pct or 0 for b in bins))
        if best is None or score < best[0]:
            best = (score, name, bins, unplaced)

    _, best_name, bins, unplaced = best
    trailers = [_bin_to_trailerload(b, i + 1) for i, b in enumerate(bins)]
    return PackingResult(method_name=f"Algoritmo (optimizado · estrategia: {best_name})",
                          trailers=trailers, unplaced=unplaced)


# ---------------------------------------------------------------------------
# Método 2: simulación "estilo humano" (dos carriles, orden de llegada)
# ---------------------------------------------------------------------------

def pack_human_like(deliveries: List[Delivery], length_ft: float, width_ft: float, height_ft: float,
                     gap: float = DEFAULT_GAP_FT,
                     margin: float = DEFAULT_WALL_MARGIN_FT) -> PackingResult:
    """Simula cómo suele armar la carga una persona con la lista tal cual
    llega: separa la caja en 2 carriles (izquierda/derecha a lo ancho) y va
    llenando cada carril de frente hacia el fondo en el orden de la lista,
    sin reacomodar ni buscar huecos. Es una línea base representativa del
    acomodo manual típico, para poder comparar contra el algoritmo."""
    items = list(deliveries)
    if not items:
        return PackingResult(method_name="Acomodo manual (simulado)", trailers=[], unplaced=[])

    usable_l = length_ft - 2 * margin
    usable_w = width_ft - 2 * margin
    lane_w = usable_w / 2.0

    trailers: List[TrailerLoad] = []
    unplaced: List[Delivery] = []

    def new_trailer(idx):
        return TrailerLoad(index=idx, length_ft=length_ft, width_ft=width_ft, height_ft=height_ft, items=[])

    trailer = new_trailer(1)
    lane_cursor = [margin, margin]  # posición x disponible en carril 0 (arriba) y carril 1 (abajo)
    trailers.append(trailer)

    for d in items:
        w = d.largo_efectivo_ft + gap
        h = d.ancho_ft + gap
        if h > lane_w + 1e-9:
            # no cabe en un solo carril (pieza muy ancha) -> intenta usar la caja completa como un carril
            if h > usable_w + 1e-9 or w > (usable_l - (max(lane_cursor) - margin)) + 1e-9:
                unplaced.append(d)
                continue

        placed_here = False
        # intenta en el carril con más espacio restante primero (más parecido a cómo
        # decide una persona: "en este lado todavía cabe")
        lane_order = sorted(range(2), key=lambda i: lane_cursor[i])
        for lane in lane_order:
            remaining = (margin + usable_l) - lane_cursor[lane]
            if w <= remaining + 1e-9 and h <= lane_w + 1e-9:
                x = lane_cursor[lane]
                y = margin + lane * lane_w
                item = PlacedItem(delivery=d, x_ft=x, y_ft=y,
                                   largo_ft=d.largo_efectivo_ft, ancho_ft=d.ancho_ft,
                                   alto_ft=d.alto_ft, rotated=False)
                trailer.items.append(item)
                lane_cursor[lane] += w
                placed_here = True
                break

        if not placed_here:
            # abre una caja nueva (una persona típicamente no reacomoda lo ya cargado)
            trailer = new_trailer(len(trailers) + 1)
            trailers.append(trailer)
            lane_cursor = [margin, margin]
            x = lane_cursor[0]
            y = margin
            item = PlacedItem(delivery=d, x_ft=x, y_ft=y,
                               largo_ft=d.largo_efectivo_ft, ancho_ft=d.ancho_ft,
                               alto_ft=d.alto_ft, rotated=False)
            trailer.items.append(item)
            lane_cursor[0] += w

    trailers = [t for t in trailers if t.items]
    return PackingResult(method_name="Acomodo manual (simulado)", trailers=trailers, unplaced=unplaced)
