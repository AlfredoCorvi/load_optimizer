"""
Modelos de datos para el optimizador de embarques.
"""
from dataclasses import dataclass, field
from typing import Optional


# Dimensiones internas típicas de una caja seca (dry van) de 53 ft.
# Se dejan como constantes configurables desde la UI.
TRAILER_LENGTH_FT_DEFAULT = 53.0   # largo interior
TRAILER_WIDTH_FT_DEFAULT = 8.3     # ancho interior (~99-100 in)
TRAILER_HEIGHT_FT_DEFAULT = 9.0    # alto interior (no restringe apilado aquí)

# Espacio de maniobra / separación entre cargadoras y contra la pared,
# para que el acomodo sea realista y no "perfecto de laboratorio".
DEFAULT_GAP_FT = 0.05  # ~0.6 in entre piezas
DEFAULT_WALL_MARGIN_FT = 0.05


@dataclass
class Delivery:
    """Una orden / cargadora a embarcar.

    `bulto_extra` es un entero (cantidad de bultos extra), vacío/0 por
    defecto. Se captura escribiendo la letra 'y' repetida tantas veces como
    bultos extra tenga la pieza ('y' = 1, 'yy' = 2, 'yyy' = 3, ...), y esa
    cantidad se usa para multiplicar el largo al calcular el espacio que
    ocupa la pieza dentro de la caja.
    """
    modelo: str
    delivery: int
    bulto_extra: int
    largo_ft: float
    ancho_ft: float
    alto_ft: float

    @property
    def largo_efectivo_ft(self) -> float:
        if self.bulto_extra and self.bulto_extra > 0:
            return self.largo_ft * self.bulto_extra
        return self.largo_ft

    @property
    def area_ft2(self) -> float:
        return self.largo_efectivo_ft * self.ancho_ft


@dataclass
class PlacedItem:
    """Una cargadora ya colocada dentro de una caja, con su posición."""
    delivery: Delivery
    x_ft: float   # posición a lo largo de la caja (0 = puerta o frente, según convención)
    y_ft: float   # posición a lo ancho de la caja
    largo_ft: float
    ancho_ft: float
    alto_ft: float
    rotated: bool = False


@dataclass
class TrailerLoad:
    """Una caja seca de 53' con las piezas que se le asignaron."""
    index: int
    length_ft: float
    width_ft: float
    height_ft: float
    items: list = field(default_factory=list)  # list[PlacedItem]

    @property
    def used_area_ft2(self) -> float:
        return sum(p.largo_ft * p.ancho_ft for p in self.items)

    @property
    def total_area_ft2(self) -> float:
        return self.length_ft * self.width_ft

    @property
    def utilization_pct(self) -> float:
        """% del LARGO de la caja que se usa (antes era % de piso/área).
        Se calcula como el largo ocupado entre el largo nominal de la caja,
        que es la referencia que más le importa a operaciones: qué tanto
        de los 53 ft se aprovechó."""
        if self.length_ft <= 0:
            return 0.0
        return 100.0 * self.used_length_ft / self.length_ft

    @property
    def used_length_ft(self) -> float:
        if not self.items:
            return 0.0
        return max(p.x_ft + p.largo_ft for p in self.items)


@dataclass
class PackingResult:
    """Resultado completo de una corrida de empaque (un método)."""
    method_name: str
    trailers: list  # list[TrailerLoad] -> cajas que SÍ se van a embarcar
    unplaced: list  # list[Delivery] -> no cupieron físicamente en ninguna caja
    rezagadas: list = field(default_factory=list)
    # list[Delivery] -> sí cupieron en una caja, pero esa caja no alcanzó el
    # % mínimo de llenado configurado, así que no se considera rentable
    # embarcarla; quedan pendientes para consolidar con el siguiente pedido.

    @property
    def n_trailers(self) -> int:
        return len(self.trailers)

    @property
    def n_placed(self) -> int:
        return sum(len(t.items) for t in self.trailers)

    @property
    def n_unplaced(self) -> int:
        return len(self.unplaced)

    @property
    def n_rezagadas(self) -> int:
        return len(self.rezagadas)

    @property
    def avg_utilization_pct(self) -> float:
        if not self.trailers:
            return 0.0
        return sum(t.utilization_pct for t in self.trailers) / len(self.trailers)
