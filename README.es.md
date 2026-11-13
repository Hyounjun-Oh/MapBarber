<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — una barbería para mapas de robots" width="560">
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <a href="README.zh.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <b>Español</b>
</p>

**Una barbería para mapas de robots.** Limpia y edita mapas de vóxeles OctoMap, nubes de puntos y rejillas de ocupación 2D de ROS — y, desde la 1.1, etiqueta nubes de puntos LiDAR y secuencias de escaneos. Todo funciona sin conexión, en una sola ventana.

[![tests](https://github.com/Hyounjun-Oh/MapBarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/MapBarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-1.1.0-orange)

![Editor de vóxeles, editor de nubes de puntos, editor de rejillas 2D, conversión, etiquetado de nubes de puntos, selección inteligente, cajas 3D, etiquetado automático de cajas 3D y secuencias](docs/home.webp)

<sub>Animaciones de etiquetado: [KITTI raw dataset](https://www.cvlibs.net/datasets/kitti/raw_data.php), trayecto 2011_09_26_0005 (Geiger et al., CC BY-NC-SA 3.0), fotograma 0 etiquetado a mano.</sub>

El uso detallado, todos los atajos y las notas sobre archivos están en la **[wiki](https://github.com/Hyounjun-Oh/MapBarber/wiki)**.

## Funciones

- **Editor de vóxeles** — OctoMap `.bt` / `.ot`: borrar, añadir, islas flotantes, caja, corte, regla; 35 millones de vóxeles siguen fluidos.
- **Editor de nubes de puntos** — PCD, PLY, LAS/LAZ, texto, `.bin`: filtros de ruido, aclarado, color por cualquier campo; al guardar se conserva cada campo.
- **Editor de rejillas 2D** — mapas de map_server de ROS: lápiz, línea, rectángulo, relleno, motas, recorte del borde, origen.
- **Conversión** — mapa de vóxeles ↔ nube de puntos ↔ rejilla 2D, ida y vuelta sin pérdidas.
- **Etiquetado LiDAR** — clases, selección inteligente, cajas 3D y etiquetado automático de cajas 3D en secuencias de escaneos; exportación a SemanticKITTI, KITTI y OpenPCDet.
- **Línea de comandos** — limpieza y conversión por lotes sin ventana.

| Mapas de vóxeles | Nubes de puntos | Rejillas de ocupación 2D |
|---|---|---|
| ![Mapas de vóxeles](docs/voxel.gif) | ![Nubes de puntos](docs/cloud.gif) | ![Rejillas de ocupación 2D](docs/grid.gif) |

Los mapas se convierten entre los tres tipos sin pérdidas, y toda edición se puede deshacer hasta guardar.

## Inicio rápido

```bash
git clone https://github.com/Hyounjun-Oh/MapBarber.git
cd MapBarber
./mapbarber.sh                                  # ventana vacía — suelta mapas en ella
./mapbarber.sh demo/office_octomap.bt           # o abre archivos, una pestaña cada uno
```

La primera ejecución instala NumPy, SciPy, VTK y PySide6 en `.venv/` (unos 500 MB); hace falta Python 3.10+ y una sesión de escritorio. También funciona `pip install .` (`pip install ".[las]"` añade LAS/LAZ). [`demo/`](demo/README.md) tiene mapas realistas con defectos conocidos y una lista de comprobación.

## Novedad en 1.1: etiquetado LiDAR

### Etiquetado de nubes de puntos
Clases, pincel de etiquetas, protección de puntos etiquetados, herramientas de revisión, objetos y exportación a SemanticKITTI, KITTI y OpenPCDet.

![Etiquetado de nubes de puntos](docs/labelling.gif)

### Selección inteligente
Un clic toma un coche, un peatón o un poste entero sin el suelo de debajo — o un plano entero.

![Selección inteligente](docs/smart_pick.gif)

### Cajas 3D
Divide una clase en objetos y pon una caja a cada uno; unos pocos puntos mal etiquetados no estiran la caja.

![Cajas 3D](docs/boxes.gif)

### Etiquetado automático de cajas 3D
Las cajas y las etiquetas de puntos se llevan hacia delante o hacia atrás en el tiempo a lo largo de todo un trayecto. Aquí: desde un fotograma etiquetado a mano por los 154 escaneos.

![Etiquetado automático de cajas 3D](docs/auto_labelling.webp)

<sub>Animaciones de etiquetado: [KITTI raw dataset](https://www.cvlibs.net/datasets/kitti/raw_data.php), trayecto 2011_09_26_0005 (Geiger et al., CC BY-NC-SA 3.0), fotograma 0 etiquetado a mano.</sub>

## Documentación

La guía completa está en la **[wiki](https://github.com/Hyounjun-Oh/MapBarber/wiki)** (inglés, coreano): [Primeros pasos](https://github.com/Hyounjun-Oh/MapBarber/wiki/Getting-Started) · [Etiquetado](https://github.com/Hyounjun-Oh/MapBarber/wiki/Labelling) · [Selección inteligente](https://github.com/Hyounjun-Oh/MapBarber/wiki/Smart-Pick) · [Cajas 3D](https://github.com/Hyounjun-Oh/MapBarber/wiki/3D-Boxes) · [Etiquetado de cajas 3D](https://github.com/Hyounjun-Oh/MapBarber/wiki/Auto-3D-Box-Labelling) · [Secuencias](https://github.com/Hyounjun-Oh/MapBarber/wiki/Frame-Sequences) · [Atajos de teclado](https://github.com/Hyounjun-Oh/MapBarber/wiki/Keyboard-Shortcuts) · [Archivos y formatos](https://github.com/Hyounjun-Oh/MapBarber/wiki/Files-and-Formats) · [Línea de comandos](https://github.com/Hyounjun-Oh/MapBarber/wiki/Command-Line) · [FAQ](https://github.com/Hyounjun-Oh/MapBarber/wiki/FAQ)

## Licencia

[MIT](LICENSE) — libre de usar, modificar y redistribuir, también comercialmente. Las dependencias mantienen sus propias licencias (PySide6 LGPL-3.0; VTK, NumPy, SciPy BSD-3-Clause); consulta [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), que cubre también los datos de KITTI de las animaciones de etiquetado. [Cambios](CHANGELOG.md) · [Contribuir](CONTRIBUTING.md) · [Seguridad](SECURITY.md)
