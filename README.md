# Optimizador de Embarques — Cajas Secas 53'

App en Python + Streamlit para reducir el número de cajas secas de 53' usadas
al embarcar cargadoras (en tarimas). Compara un **acomodo manual simulado**
(cómo se arma normalmente la carga, en el orden de la lista) contra un
**algoritmo de optimización** (2D bin packing tipo MaxRects, probando varias
estrategias de orden), midiendo: cajas usadas, órdenes embarcadas, órdenes
que quedan fuera, y % de piso aprovechado por caja.

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecutar

```bash
streamlit run app.py
```

Se abre en el navegador (por defecto `http://localhost:8501`).

## Uso

1. **Datos de entrada** — dos formas, ambas alimentan la misma tabla:
   - **Subir Excel**: usa el botón "Descargar plantilla" para bajar el
     formato exacto (columnas: Modelo, Delivery, Bulto extra, Largo (ft),
     Ancho (ft), Alto (ft)) y súbelo ya lleno.
   - **Captura manual**: edita la tabla directamente en la app (agregar /
     borrar filas, pegar datos desde Excel funciona en la tabla también).

2. **Parámetros de la caja** (barra lateral): largo/ancho/alto interior de
   la caja de 53', espacio extra que se reserva cuando una pieza trae
   "bulto extra", si se permite rotar piezas 90°, separación entre piezas
   y margen contra la pared.

3. **Calcular mejor acomodo** — corre ambos métodos y muestra:
   - Métricas comparativas (cajas, órdenes embarcadas/fuera, % de piso usado).
   - Gráficas de barras manual vs. algoritmo.
   - Vista 3D interactiva de cada caja, con tabla de deliveries que contiene.
   - Lista de órdenes que no cupieron, si las hay.

4. **Generar reporte PDF** — arma un PDF con la comparación, conclusión y
   una página por caja con su render 3D + tabla de deliveries.

## Cómo funciona el algoritmo (resumen)

Como el producto no se apila, el problema se reduce a acomodar rectángulos
(largo × ancho de cada cargadora) sobre el piso de la caja (largo × ancho de
la caja), permitiendo 2 filas a lo ancho. El algoritmo optimizado usa una
heurística **MaxRects (Best Area Fit)** multi-contenedor: mantiene los
espacios libres restantes de cada caja como rectángulos, coloca cada pieza
en el hueco donde deje menos desperdicio (probando también la orientación
rotada si está permitido), y abre una caja nueva sólo cuando ninguna caja
abierta tiene espacio. Se corre con varios criterios de orden de las piezas
(por área, por largo, por ancho, por perímetro) y se elige automáticamente
la corrida que use menos cajas, deje menos órdenes fuera y aproveche mejor
el espacio.

La simulación "manual" imita el criterio típico de una persona: separa la
caja en 2 carriles fijos (izquierda/derecha) y va colocando las piezas en
el orden en que aparecen en la lista, sin reacomodar lo ya cargado ni
buscar huecos — por eso normalmente usa más cajas y deja más piezas fuera
que el algoritmo.

## Estructura del proyecto

```
app.py            -> interfaz Streamlit (entrada de datos, resultados, PDF)
models.py         -> clases de datos (Delivery, TrailerLoad, PackingResult...)
packing.py        -> motor de empaquetado (algoritmo MaxRects + simulación manual)
visualization.py  -> vistas 3D (plotly interactivo, matplotlib estático para PDF)
report.py         -> generación del reporte PDF (reportlab)
data_io.py        -> plantilla Excel, lectura/validación de datos
requirements.txt  -> dependencias
```

## Notas y supuestos configurables

- Dimensiones default de la caja: 53 × 8.3 × 9 ft (ajustables en la barra lateral).
- "Bulto extra" añade un largo adicional configurable (default 1 ft) al
  calcular el espacio que ocupa esa pieza.
- El alto (`alto_ft`) se captura y se muestra en la vista 3D y tablas, pero
  no restringe el acomodo porque el producto no se apila.
- Si alguna pieza no cabe en ninguna caja (por ejemplo, más ancha que la
  caja), se reporta como "fuera de caja" en vez de detener el cálculo.
