<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — una barbería para mapas de robots" width="560">
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <a href="README.zh.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <b>Español</b>
</p>

**Una barbería para mapas de robots.** Recorta los vóxeles, puntos y píxeles sueltos que dejan los sensores ruidosos y rellena las calvas, en octrees de OctoMap, nubes de puntos y rejillas de ocupación 2D de ROS, todo desde una sola ventana.

[![tests](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![Abrir tres tipos de mapa en pestañas, convertir un mapa de vóxeles en una rejilla 2D y cambiar de idioma](docs/overview.gif)

Abre o suelta archivos y MapBarber reconoce qué contiene cada uno y lo abre en su propia pestaña con el editor adecuado: un editor de vóxeles para octrees, un editor de puntos para nubes y un editor de pintura para rejillas de ocupación 2D. Los mapas se pueden convertir entre los tres tipos, y cada cambio se puede deshacer hasta que guardes.

## Inicio rápido

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                                      # ventana vacía: suelta mapas en ella
./mapbarber.sh demo/office_octomap.bt demo/warehouse_map.yaml   # o abre archivos, una pestaña por archivo
```

La primera ejecución crea un entorno virtual propio en `.venv/` e instala NumPy, SciPy, VTK y PySide6 (unos 500 MB). Las siguientes arrancan al instante. Necesitas Python 3.10 o posterior y una sesión de escritorio (X11, o Wayland mediante XWayland, que el script elige por ti).

¿Prefieres pip? `pip install .` instala un comando `mapbarber` que hace lo mismo.

**Pruébalo con datos realistas:** [`demo/`](demo/README.md) contiene mapas generados con sensores simulados, cada uno con defectos y dimensiones reales conocidos, y una lista de comprobación paso a paso.

## Qué abre

| Tipo de mapa | Archivos | Se abre en |
|---|---|---|
| Mapa de vóxeles | OctoMap `.bt` (binario), `.ot` (`OcTree`, `OcTreeStamped`, `ColorOcTree`), archivos `.npz` de vóxeles | editor de vóxeles |
| Nube de puntos | `.pcd` (ascii, binary, organizada), `.ply` (ascii, binary), `.xyz` / `.txt` / `.csv` (columnas RGB opcionales), `.npy`, `.npz` | editor de nubes de puntos |
| Nube de puntos (más) | `.las` / `.laz` (tras `pip install "laspy[lazrs]"`), barridos LiDAR `.bin` (x y z intensity) | editor de nubes de puntos |
| Secuencia de fotogramas | una **carpeta** de barridos con poses: KITTI odometry (`velodyne/` + `poses.txt`), KITTI raw (`velodyne_points/` + `oxts/`) o cualquier carpeta de `.pcd` / `.ply` / `.las` / `.bin` con un archivo de poses (TUM, matrices 3×4 o 4×4, o CSV con cabecera) | editor de nubes de puntos en modo de etiquetado |
| Rejilla de ocupación 2D | `.yaml` de map_server con `.pgm` / `.png` / `.bmp`, o solo la imagen | editor de rejillas |

La detección mira primero la extensión y después la firma del archivo, así que una copia como `map.bt.bak_20240101` también se abre como octree. Al abrir solo un `.pgm` se lee también el `.yaml` contiguo si apunta a esa imagen. Los archivos dañados o ajenos se rechazan con una breve explicación.

## Editor de mapas de vóxeles

![Quitar motas flotantes y un bloque fantasma, rellenar un hueco y añadir vóxeles](docs/voxel.gif)

- **Herramientas:** Navegar `H`, Seleccionar `V`, Borrar `E`, Añadir `B`, Medir `I`. El pincel es un cubo de 1 a 31 celdas; `[` y `]` cambian su tamaño. Añadir crea una capa hacia fuera desde la cara pulsada o coloca vóxeles sobre un plano de trabajo horizontal.
- **Selección:** `Mayús`+arrastrar selecciona dentro de un rectángulo de pantalla (*Solo la capa frontal* omite los vóxeles ocultos). El clic derecho deselecciona bajo el cursor; `Mayús`+arrastrar con el botón derecho deselecciona un rectángulo.
- **Seleccionar islas** encuentra grupos de vóxeles que no tocan nada más: las motas flotantes que producen las cámaras de profundidad. Solo selecciona, así que puedes revisar antes de pulsar `Supr`.
- **Caja:** en la vista 3D, arrastra las flechas de colores para moverla en x, y o z, y los puntos de sus caras para cambiar su tamaño (o escribe los límites). Después selecciona, borra o rellena su interior.
- **Corte:** corta el espacio con un plano en x, y o z y trabaja en un lado; el otro queda oculto y protegido. Arrastra la flecha del plano, cambia de lado y, al terminar, pulsa *Restaurar vista*.
- **Regla:** haz clic en dos vóxeles para leer la distancia, Δx/Δy/Δz y la longitud en vóxeles. Mantén `Mayús` para fijar la medida a un eje; activa *Ajustar a los centros de vóxel* para medir de centro a centro.
- Los vóxeles añadidos desde el último guardado se ven en blanco; la selección, en rosa.

## Editor de nubes de puntos

![Seleccionar atípicos, borrar una estela, colorear por intensidad y aclarar](docs/cloud.gif)

- **Herramientas:** Navegar `H`, Seleccionar `V`, Borrar `E`, Medir `I`, con un pincel esférico alrededor del punto pulsado (`[` / `]` cambian el radio), selección rectangular y deselección con clic derecho.
- **Filtros de ruido** seleccionan atípicos estadísticos (distancia media a los vecinos muy superior a la normal) o puntos dispersos (muy pocos vecinos dentro de un radio).
- **Aclarar** conserva un punto por celda cúbica. **Caja** y **Corte** funcionan como en el editor de vóxeles, y la caja además puede borrar todo lo exterior.
- **Colorear por** altura, RGB guardado o cualquier campo numérico como `intensity` o `ring`.
- **Regla** mide la distancia real entre dos puntos elegidos.
- Los puntos solo se eliminan, así que al guardar en PCD se conservan todos los campos de cada punto restante, y en PLY todos los campos escalares.

## Etiquetado

Activa el **Modo de etiquetado** en la barra de herramientas (`Ctrl+L`) en el editor de nubes de puntos o de vóxeles. Las herramientas y el panel cambian al etiquetado; al desactivarlo vuelves a la edición tal como estaba. Todo funciona sin conexión en la CPU, y los puntos originales nunca se mueven ni se descartan.

- **Clases:** una lista con número, nombre, color y lo que la clase significa en un mapa (obstáculo, superficie transitable, ignorar). Hay preajustes para robots de interior, SemanticKITTI y códigos LAS; carga o guarda `labels.yaml`. El ojo oculta una clase y el candado la bloquea; un clic en el ojo o el candado de la cabecera se aplica a todas las clases.
- **Etiquetar:** selecciona con cualquier herramienta y pulsa `Enter` (*Mapeo de etiquetas*) o `Ctrl+1`…`Ctrl+9`, o pinta con el pincel de etiqueta `B`. `Ctrl`+arrastrar pinta con la vista fija, `Ctrl`+arrastrar con el botón derecho deshace.
- **Proteger puntos etiquetados** (el interruptor de la esquina superior derecha de la vista, o `P`): los puntos ya etiquetados quedan fuera de la selección y conservan su etiqueta, así una selección amplia de una pared o del suelo salta los objetos etiquetados antes.
- **Selección inteligente `W`:** un clic encuentra un *objeto conectado*, una *superficie plana* o una *superficie suave*. Un objeto conectado se detiene en el suelo (separación) y, con datos densos, en superficies amplias con otra orientación; `[` / `]` aflojan o ajustan la última selección. El **filtro de suelo** selecciona el suelo o todo lo que hay encima.
- **Revisión:** barra de progreso, *Siguiente sin etiqueta* (`N`), etiquetas dudosas, islas pequeñas y *Sugerir para los huecos*; las sugerencias se muestran pálidas hasta confirmarlas.
- **Objetos y cajas 3D:** elige una clase y pulsa *Caja para cada objeto de …*: sus puntos se dividen en objetos separados y cada uno recibe una caja vertical que puedes editar, reajustar o borrar. *Dejar solo la clase* convierte las instancias de nuevo en clases simples.
- **Fotogramas:** abre una carpeta de barridos. La línea de tiempo bajo la vista fija el primer y el último fotograma mostrados; los fotogramas se combinan según sus poses mientras cada etiqueta permanece en su fotograma. Las etiquetas pueden llevarse a otros fotogramas como sugerencias y pueden listarse los conflictos entre fotogramas. *Vista fija en*, en la misma franja, elige qué permanece quieto al cambiar de fotograma: el mundo, el LiDAR o la caja elegida en la lista de cajas.
- **Seguimiento:** pon cajas a los objetos de un fotograma, fija el rango y pulsa *Seguir las cajas*. Hacia delante, cada objeto se busca en el fotograma siguiente por solapamiento de cajas (IoU) y sus puntos se alinean (ICP) y se reúnen en un modelo, así la caja crece hasta el objeto entero al cambiar la vista. Después cada fotograma, también los anteriores, se ajusta de nuevo al modelo terminado: un tamaño de caja por objeto, y los puntos que una caja inicial incompleta dejó fuera se recogen. Las clases marcadas como *cambia de forma* (personas) reciben una caja por fotograma. Las puntuaciones bajas llegan como sugerencias marcadas con `?`; *Seleccionar puntos fuera de las cajas* muestra lo que aún cuelga de un objeto y *Darlos a sus objetos* lo incorpora y ensancha la caja.
- **Vóxeles:** al convertir una nube en vóxeles, cada vóxel toma la clase de la mayoría de sus puntos. Al volver a puntos, cada punto recupera su propia etiqueta; solo los vóxeles que reetiquetaste transmiten su clase.
- **Archivos:** las etiquetas se guardan dentro del archivo cuando el formato lo permite (campos `label` / `instance` en PCD y PLY, `classification` en LAS), como archivos `.label` para secuencias `.bin`, o junto al archivo (`name.labels.npz`). *Exportar en formatos estándar* escribe una secuencia SemanticKITTI, etiquetas de objetos KITTI y cajas OpenPCDet.
- `Ctrl+Z` abarca etiquetas, clases, cajas y seguimiento. `Supr` nunca borra puntos en modo de etiquetado: quita etiquetas o borra la caja u objeto en que se hizo clic por último.

## Editor de rejillas de ocupación 2D

![Quitar motas, cerrar una puerta, dibujar obstáculos, rellenar un hueco y recortar el borde](docs/grid.gif)

- **Herramientas:** Navegar `H`, Lápiz `B`, Línea `L`, Rectángulo `R`, Rellenar `G`, Medir `I`. Pinta *ocupado*, *libre* o *desconocido* con `O`, `F`, `U`; `[` / `]` cambian el grosor del lápiz.
- **Restricciones como en PowerPoint:** con `Mayús`, la línea (o la regla) se fija a 0°, 45° o 90° y el rectángulo se vuelve cuadrado; `Alt` dibuja el rectángulo desde su centro; `Mayús`+clic con el lápiz traza una recta desde el último punto.
- **Quitar motas** libera las manchas ocupadas pequeñas y aisladas.
- **Recortar el borde desconocido** elimina el margen sin explorar y mueve el origen para que nada del mapa se desplace.
- **Información del mapa** edita la resolución y el origen (x, y, guiñada). Las flechas roja y verde marcan el origen del mapa.
- **Regla** da la distancia en metros y en píxeles, y Δx/Δy en el marco del mapa (incluidos orígenes girados).
- Al alejar la vista, las paredes finas siguen visibles: ocupado prevalece sobre desconocido, y desconocido sobre libre.
- Al guardar se escriben la imagen y un YAML de map_server lado a lado (modos `trinary`, `scale` y `raw`, `negate`).

## Varios mapas a la vez

Cada archivo se abre en su propia pestaña, y abrir uno que ya está abierto cambia a su pestaña. `Ctrl+Tab` / `Ctrl+Mayús+Tab` cambian de pestaña, `Ctrl+W` cierra una (preguntando antes si tiene cambios sin guardar) y puedes soltar varios archivos a la vez.

El menú **Convertir** transforma el mapa actual en otro tipo en una pestaña nueva, sin tocar el original:

| De \ A | Mapa de vóxeles | Nube de puntos | Rejilla 2D |
|---|---|---|---|
| Mapa de vóxeles | — | centros de vóxel | proyectar una franja de altura |
| Nube de puntos | voxelizar con el tamaño elegido | — | voxelizar y luego proyectar |
| Rejilla 2D | levantar paredes hasta una altura | — | — |

## Línea de comandos

Sin `--output` ni `--info` se abre el editor. Con ellos no se muestra nada y el trabajo se hace en la terminal:

```bash
./mapbarber.sh room.bt --info
./mapbarber.sh room.bt --remove-islands 20 -o room_clean.bt
./mapbarber.sh room.bt --z-band 0.1 1.8 -o floor.yaml          # octree -> mapa de ROS
./mapbarber.sh floor.yaml --clear-speckles 4 -o floor_clean.yaml
./mapbarber.sh floor.yaml --wall-height 2.0 -o walls.bt        # mapa de ROS -> octree
./mapbarber.sh scan.pcd --remove-outliers 16 2.0 -o scan_clean.pcd
./mapbarber.sh scan.pcd -r 0.05 -o scan.bt                     # nube -> octree
```

La extensión de salida decide el tipo de salida.

## Atajos de teclado

Los atajos siguen las convenciones habituales de escritorio: Photoshop, Figma y PowerPoint para herramientas y restricciones, y el sistema operativo para archivos y edición. En macOS, `Ctrl` es `⌘`.

| Teclas | Acción |
|---|---|
| `Ctrl+O` / `Ctrl+S` / `Ctrl+Mayús+S` | abrir / guardar / guardar como o exportar |
| `Ctrl+N` / `Ctrl+Mayús+N` | nuevo mapa de vóxeles / nueva rejilla 2D |
| `Ctrl+W` / `Ctrl+Tab` / `Ctrl+Mayús+Tab` | cerrar pestaña / pestaña siguiente / anterior |
| `Ctrl+Z` / `Ctrl+Mayús+Z` o `Ctrl+Y` | deshacer / rehacer |
| `H` `V` `E` `B` `L` `R` `G` `I` | navegar, seleccionar, borrar, añadir·lápiz, línea, rectángulo, rellenar, medir |
| `[` / `]` | pincel más pequeño / más grande |
| `Supr` / `Retroceso` | eliminar selección / deshacer el último paso de selección |
| `Ctrl+A` / `Ctrl+Mayús+I` / `Esc` o `Ctrl+D` | seleccionar todo lo visible / invertir / deseleccionar |
| arrastrar izquierdo / arrastrar central o `Espacio`+arrastrar / rueda | rotar / desplazar / zoom (2D: con Navegar, arrastrar izquierdo desplaza) |
| `Mayús`+arrastrar / `Mayús`+arrastrar derecho / clic derecho | selección rectangular / deselección rectangular / deseleccionar |
| `Ctrl`+arrastrar | pintar con el pincel (seleccionar o borrar) sin mover la vista |
| `Mayús` / `Alt` al dibujar | fijar a 0°·45°·90° o cuadrado / dibujar desde el centro |
| `1` `3` `7` / `0` o `Inicio` | vista frontal, lateral, superior / isométrica (también teclado numérico) |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | acercar / alejar / ajustar a la ventana (2D) |
| `F11` / `F1` | pantalla completa / controles del editor actual |
| `Ctrl+L` | activar / desactivar el modo de etiquetado |
| `B` / `W` (modo de etiquetado) | pincel de etiqueta / selección inteligente |
| `Enter` / `Ctrl+1`…`Ctrl+9` / `Ctrl+0` o `Supr` | etiquetar la selección con la clase activa / la clase n / quitar la etiqueta |
| `P` / `N` / `Alt`+clic | proteger puntos etiquetados / siguiente zona sin etiqueta / tomar la clase bajo el cursor |
| `Ctrl`+arrastrar con el botón derecho | deshacer con el pincel (deseleccionar o quitar etiquetas) con la vista fija |
| `,` / `.`  ·  clic en la línea de tiempo y `←` / `→` | fotograma anterior / siguiente  ·  desplazar el rango su propio ancho (`Mayús`: un fotograma) |

## Idiomas

La interfaz está en English, 한국어, 日本語, 简体中文, Deutsch y Español, y se cambia desde el menú **Idioma**; la elección se recuerda. Para añadir un idioma, copia `mapbarber/locales/en.json`, traduce los valores, añade el código a `LANGUAGES` en `mapbarber/i18n.py` y ejecuta las pruebas: comprueban que estén todas las claves y marcadores.

## Notas sobre archivos

- **Los archivos octree conservan lo que contenían.** El espacio libre leído de un `.bt` o `.ot` se vuelve a escribir, dividido solo donde añades vóxeles; un `.ot` conserva además el valor de ocupación de cada celda y, en un `ColorOcTree`, su color. Los vóxeles añadidos reciben log-odds 3.5 (p ≈ 0,97) y blanco; los borrados pasan a *desconocido*, no a libre.
- **Si un formato no puede guardar algo, MapBarber lo dice antes de escribir.** Guardar un mapa `.ot` como `.bt` reduce los valores a ocupado/libre y descarta los colores; guardar un octree como puntos descarta el espacio libre. El diálogo enumera exactamente lo que se omitiría (la línea de comandos lo imprime en stderr) y no se escribe nada hasta que aceptas.
- **PCD** conserva todos los campos por punto, el `VIEWPOINT` y el `WIDTH`/`HEIGHT` organizado mientras no se elimine ningún punto. **PLY** conserva todos los campos escalares; los campos vectoriales y los enteros de 64 bits no pueden guardarse y se avisa de ello, igual que de las caras u otros elementos que no sean vértices. `.xyz`/`.csv` contienen coordenadas (seis decimales) y RGB si existe, `.npy` solo coordenadas. No se admite PCD binario comprimido. *Reducir* conserva el primer punto leído de cada celda.
- **Las cuadrículas** siguen las reglas de map_server: modos `trinary`, `scale` y `raw`, `negate` y los umbrales guardados en el YAML. El editor trabaja con tres estados, pero las celdas que no tocas se guardan con su valor de píxel original, de modo que los mapas graduados `scale`/`raw` sobreviven a una edición en otra parte.
- **Copias de seguridad:** al sobrescribir un archivo se conserva el anterior como `name.bak_YYYYmmdd_HHMMSS`. Se puede desactivar en el menú Archivo.

## Cómo funciona

MapBarber es una implementación independiente escrita a partir de los formatos de archivo publicados. No usa ni deriva del código fuente de OctoMap, PCL o map_server.

- Los archivos octree se leen y escriben como un *octree lineal*. Las celdas ocupadas forman un array ordenado de códigos Morton, de modo que cada nodo del árbol es un tramo contiguo de ese array y se localiza por búsqueda binaria. No se construye ningún árbol de punteros.
- La edición trabaja sobre un array ordenado de claves de celda empaquetadas mediante operaciones de conjuntos; deshacer y rehacer funcionan igual.
- Las componentes conexas (islas, motas) y las consultas de vecinos usan SciPy; la visualización usa glifos de VTK dentro de una ventana Qt.

## Licencia

[MIT](LICENSE). Puedes usarlo, modificarlo y redistribuirlo libremente, también con fines comerciales; basta con conservar el aviso de copyright y el texto de la licencia en cada copia. Esto incluye el código, las traducciones, el logotipo, los iconos y los mapas de ejemplo y de demostración, todos creados para este proyecto.

Las bibliotecas de las que depende mantienen sus propias licencias: PySide6 (LGPL-3.0), VTK, NumPy y SciPy (BSD-3-Clause). Para ejecutarlo desde el código fuente o instalarlo con pip no hace falta nada más; si redistribuyes un paquete que las incluya, consulta [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Las contribuciones se aceptan bajo la misma licencia ([CONTRIBUTING.md](CONTRIBUTING.md)).
