# Optimizador de Embarques — Cajas Secas 53'

App en Python + Streamlit para reducir el número de cajas secas de 53' usadas
al embarcar cargadoras (en tarimas). Calcula el mejor acomodo con un
**algoritmo de optimización** (2D bin packing tipo MaxRects + consolidación,
probando varias estrategias de orden) y lo compara contra **tu acomodo
manual real** (el que subes en un Excel indicando a qué caja asignaste cada
delivery), midiendo: cajas usadas, órdenes embarcadas, órdenes rezagadas,
órdenes fuera de caja, y % del largo de la caja aprovechado.

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

1. **Datos de entrada para el algoritmo** — dos formas, ambas alimentan la
   misma tabla:
   - **Subir Excel**: usa el botón "Descargar plantilla" para bajar el
     formato exacto (Modelo, Delivery, Bulto extra, Largo (ft), Ancho (ft),
     Alto (ft) y, opcionalmente, Caja) y súbelo ya lleno. Aquí la columna
     "Caja" se ignora.
   - **Captura manual**: edita la tabla directamente en la app (agregar /
     borrar filas, pegar datos desde Excel funciona en la tabla también).

2. **Parámetros de la caja y reglas de acomodo** (barra lateral): largo /
   ancho / alto interior de la caja de 53', si se permite rotar piezas 90°,
   separación entre piezas, margen contra la pared, y el **% mínimo de
   largo ocupado** para que una caja se considere rentable de embarcar.

3. **Calcular mejor acomodo** — corre el algoritmo de optimización sobre los
   deliveries capturados y muestra sus métricas.

4. **Comparar contra tu acomodo manual** — sube un Excel (misma plantilla)
   con tus mismos deliveries, agregando la columna **Caja** con el número de
   caja (1, 2, 3...) al que asignaste cada uno. La app agrupa las piezas por
   ese número, las coloca físicamente dentro de esa caja, y si alguna no
   cabe la reporta como "fuera de caja". Con esto se arma la comparación
   completa: métricas lado a lado, gráficas, y vista 3D de cualquiera de los
   dos acomodos. Si no subes el Excel manual, solo se muestran los
   resultados del algoritmo. Si cambias cualquier parámetro de la barra
   lateral (incluido el % mínimo de llenado) después de haber subido el
   Excel manual, el resultado se recalcula solo, sin tener que volver a
   subirlo.

5. **Generar reporte PDF** — arma un PDF con la comparación (o solo el
   acomodo del algoritmo si no subiste el manual), conclusión, y una página
   por caja con su render 3D + tabla de deliveries.

## % mínimo de llenado y órdenes "rezagadas"

Para que valga la pena el gasto de usar una caja de 53', puedes configurar
en la barra lateral el **% mínimo de largo que debe quedar ocupado** para
que esa caja se cuente como embarcada (0 = sin mínimo, cualquier caja con
al menos una pieza se embarca).

Cualquier caja —del algoritmo o de tu acomodo manual— que **no alcance ese
mínimo** deja de contarse como embarcada: sus órdenes pasan a la categoría
**"rezagadas"** (pendientes de consolidar con el siguiente pedido), separada
de **"fuera de caja"** (piezas que ni siquiera cupieron físicamente en
ninguna caja). El mismo criterio se aplica a ambos métodos para que la
comparación sea justa.

## Cómo funciona el algoritmo (resumen)

Como el producto no se apila, el problema se reduce a acomodar rectángulos
(largo × ancho de cada cargadora) sobre el piso de la caja (largo × ancho de
la caja), permitiendo 2 filas a lo ancho. El algoritmo optimizado usa una
heurística **MaxRects (Best Area Fit)** multi-contenedor: mantiene los
espacios libres restantes de cada caja como rectángulos, coloca cada pieza
en el hueco donde deje menos desperdicio (probando también la orientación
rotada si está permitido), y abre una caja nueva sólo cuando ninguna caja
abierta tiene espacio.

Después de empacar, se aplica una fase de **consolidación**: se busca la
caja menos llena (por % de largo usado) y se intenta reubicar sus piezas en
las demás cajas ya abiertas (drenado parcial — mueve las que sí quepan, no
exige mover todas). Si logra vaciarla por completo, esa caja desaparece.
Esto se repite hasta que ya no se puede mejorar más. Todo esto se corre con
varios criterios de orden de las piezas (por área, por largo, por ancho, por
perímetro) y se elige automáticamente la corrida que use menos cajas, deje
menos órdenes fuera y aproveche mejor el espacio. Al final se aplica el %
mínimo de llenado configurado: las cajas que no lo alcanzan pasan a
"rezagadas" en vez de contarse como embarcadas.

El **acomodo manual** no se simula: se toma tal cual la asignación de caja
que el usuario indicó en su Excel (columna "Caja"), sin mover piezas entre
cajas (para respetar la decisión real de la persona). Dentro de cada caja,
las piezas se colocan con el mismo motor de acomodo, solo para poder
visualizarlas en 3D. Al final se aplica el mismo % mínimo de llenado que al
algoritmo.

El **% de aprovechamiento** que se reporta por caja es el **% del largo de
la caja utilizado** (largo ocupado entre los 53 ft de largo total), no el
% de área de piso.

## Estructura del proyecto

```
app.py            -> interfaz Streamlit (entrada de datos, resultados, PDF)
models.py         -> clases de datos (Delivery, TrailerLoad, PackingResult...)
packing.py        -> motor de empaquetado (algoritmo MaxRects + consolidación + acomodo manual por asignación de caja)
visualization.py  -> vistas 3D (plotly interactivo, matplotlib estático para PDF)
report.py         -> generación del reporte PDF (reportlab)
data_io.py        -> plantilla Excel, lectura/validación de datos (incluye columna Caja)
requirements.txt  -> dependencias
```

## Notas y supuestos configurables

- Dimensiones default de la caja: 53 × 8.3 × 9 ft (ajustables en la barra lateral).
- "Bulto extra" se captura con la letra 'y' repetida (y = 1, yy = 2, yyy = 3...)
  y multiplica el largo de la pieza al calcular el espacio que ocupa.
- El alto (`alto_ft`) se captura y se muestra en la vista 3D y tablas, pero
  no restringe el acomodo porque el producto no se apila.
- % mínimo de llenado por caja: 0 por defecto (desactivado). Ajustable de 0
  a 95% en pasos de 5.
- Si alguna pieza no cabe en la caja (del algoritmo, o en la caja que el
  usuario le asignó en su Excel manual), se reporta como "fuera de caja" en
  vez de detener el cálculo. Si cabe pero la caja no llega al % mínimo de
  llenado, se reporta como "rezagada".
- La plantilla de Excel es la misma para ambos flujos; la columna "Caja" es
  opcional cuando se usa para alimentar el cálculo del algoritmo, y
  obligatoria cuando se sube como acomodo manual a comparar.
