<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — ein Friseursalon für Roboterkarten" width="560">
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <a href="README.zh.md">简体中文</a> · <b>Deutsch</b> · <a href="README.es.md">Español</a>
</p>

**Ein Friseursalon für Roboterkarten.** Stutzt die verirrten Voxel, Punkte und Pixel, die verrauschte Sensoren hinterlassen, und füllt kahle Stellen – in OctoMap-Octrees, Punktwolken und 2D-Belegungsrastern aus ROS, alles in einem Fenster.

[![tests](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![Drei Kartenarten in Tabs öffnen, eine Voxelkarte in ein 2D-Raster umwandeln und die Sprache wechseln](docs/overview.gif)

Dateien öffnen oder hineinziehen: MapBarber erkennt, was jede Datei enthält, und öffnet sie in einem eigenen Tab mit dem passenden Editor – einem Voxel-Editor für Octrees, einem Punkt-Editor für Wolken und einem Mal-Editor für 2D-Belegungsraster. Die drei Arten lassen sich ineinander umwandeln, und jede Bearbeitung ist bis zum Speichern rückgängig zu machen.

## Schnellstart

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                                      # leeres Fenster – Karten hineinziehen
./mapbarber.sh demo/office_octomap.bt demo/warehouse_map.yaml   # oder Dateien direkt öffnen, je ein Tab
```

Beim ersten Start wird in `.venv/` eine eigene virtuelle Umgebung angelegt und NumPy, SciPy, VTK und PySide6 werden installiert (etwa 500 MB). Danach startet das Programm sofort. Benötigt werden Python 3.10 oder neuer und eine Desktop-Sitzung (X11 oder Wayland über XWayland, das das Skript automatisch wählt).

Lieber pip? `pip install .` installiert einen Befehl `mapbarber`, der dasselbe tut.

**Mit realistischen Daten ausprobieren:** [`demo/`](demo/README.md) enthält Karten aus simulierten Sensoren mit bekannten Fehlern und bekannten wahren Maßen sowie eine Checkliste Schritt für Schritt.

## Unterstützte Formate

| Kartenart | Dateien | Öffnet im |
|---|---|---|
| Voxelkarte | OctoMap `.bt` (binär), `.ot` (`OcTree`, `OcTreeStamped`, `ColorOcTree`), Voxel-`.npz` | Voxel-Editor |
| Punktwolke | `.pcd` (ascii, binary, organisiert), `.ply` (ascii, binary), `.xyz` / `.txt` / `.csv` (optional mit RGB-Spalten), `.npy`, `.npz` | Punktwolken-Editor |
| 2D-Belegungsraster | map_server-`.yaml` mit `.pgm` / `.png` / `.bmp` oder nur das Bild | Raster-Editor |

Erkannt wird zuerst an der Dateiendung, dann an der Dateisignatur, daher öffnet sich auch eine Sicherung wie `map.bt.bak_20240101` als Octree. Wird nur ein `.pgm` geöffnet, wird die danebenliegende `.yaml` mitgelesen, wenn sie auf dieses Bild verweist. Beschädigte oder fremde Dateien werden mit einer kurzen Begründung abgelehnt.

## Voxel-Editor

![Schwebende Störungen und einen Geisterblock entfernen, ein Loch füllen und Voxel hinzufügen](docs/voxel.gif)

- **Werkzeuge:** Navigieren `H`, Auswählen `V`, Radieren `E`, Hinzufügen `B`, Messen `I`. Der Pinsel ist ein Würfel von 1–31 Zellen; `[` und `]` ändern seine Größe. Hinzufügen ergänzt eine Lage nach außen an der angeklickten Fläche oder setzt Voxel auf eine waagerechte Arbeitsebene.
- **Auswahl:** `Umschalt`+Ziehen wählt alles in einem Bildschirmrechteck (*Nur vorderste Lage* überspringt verdeckte Voxel). Rechtsklick hebt die Auswahl unter dem Zeiger auf, `Umschalt`+rechts ziehen hebt sie in einem Rechteck auf.
- **Inseln auswählen** findet Voxelgruppen, die nichts anderes berühren – die schwebenden Störungen von Tiefenkameras. Es wird nur ausgewählt; nach dem Prüfen `Entf` drücken.
- **Quader:** Im 3D-Fenster verschieben die farbigen Pfeile den Quader entlang x, y oder z, die Punkte auf seinen Flächen ändern seine Größe (oder die Grenzen eintippen). Danach den Inhalt auswählen, radieren oder füllen.
- **Schnitt:** Den Raum mit einer Ebene auf x, y oder z teilen und nur eine Seite bearbeiten; die andere ist ausgeblendet und geschützt. Den Pfeil der Ebene ziehen, die Seite wechseln und zum Schluss *Ansicht wiederherstellen*.
- **Lineal:** Zwei Voxel anklicken, um Abstand, Δx/Δy/Δz und die Länge in Voxeln abzulesen. Mit `Umschalt` wird die Messung an eine Achse gebunden; *An Voxelmitten einrasten* misst von Mitte zu Mitte.
- Seit dem letzten Speichern hinzugefügte Voxel sind weiß, die Auswahl ist pink.

## Punktwolken-Editor

![Ausreißer auswählen, einen Streifen radieren, nach Intensität färben und ausdünnen](docs/cloud.gif)

- **Werkzeuge:** Navigieren `H`, Auswählen `V`, Radieren `E`, Messen `I`, mit einem kugelförmigen Pinsel um den angeklickten Punkt (`[` / `]` ändern den Radius), Rechteckauswahl und Abwählen per Rechtsklick.
- **Rauschfilter** wählen statistische Ausreißer (mittlerer Nachbarabstand deutlich über dem Üblichen) oder vereinzelte Punkte (zu wenige Nachbarn im Radius).
- **Ausdünnen** behält einen Punkt pro Würfelzelle. **Quader** und **Schnitt** funktionieren wie im Voxel-Editor; der Quader kann zusätzlich alles außerhalb radieren.
- **Färben nach** Höhe, gespeicherter RGB-Farbe oder einem beliebigen Zahlenfeld wie `intensity` oder `ring`.
- **Lineal** misst den tatsächlichen Abstand zwischen zwei gewählten Punkten.
- Punkte werden nur entfernt, daher bleiben beim Speichern als PCD oder PLY alle Felder jedes übrigen Punkts erhalten.

## Raster-Editor

![Sprenkel entfernen, einen Durchgang schließen, Hindernisse zeichnen, ein Loch füllen und den Rand abschneiden](docs/grid.gif)

- **Werkzeuge:** Navigieren `H`, Stift `B`, Linie `L`, Rechteck `R`, Füllen `G`, Messen `I`. Mit `O`, `F`, `U` *belegt*, *frei* oder *unbekannt* malen; `[` / `]` ändern die Stiftbreite.
- **Einschränkungen wie in PowerPoint:** Mit `Umschalt` rastet eine Linie (oder das Lineal) auf 0°, 45° oder 90° ein und ein Rechteck wird zum Quadrat; `Alt` zeichnet ein Rechteck von der Mitte aus; `Umschalt`+Klick mit dem Stift zieht eine gerade Linie vom letzten Punkt.
- **Sprenkel entfernen** macht kleine, isolierte belegte Flecken frei.
- **Unbekannten Rand abschneiden** entfernt den unerforschten Rand und verschiebt den Ursprung, sodass nichts auf der Karte verrutscht.
- **Karteninfo** bearbeitet Auflösung und Ursprung (x, y, Gier). Roter und grüner Pfeil markieren den Kartenursprung.
- **Lineal** zeigt den Abstand in Metern und Pixeln sowie Δx/Δy im Kartensystem (auch bei gedrehtem Ursprung).
- Herausgezoomt bleiben dünne Wände sichtbar: belegt hat Vorrang vor unbekannt, unbekannt vor frei.
- Beim Speichern werden Bild und map_server-YAML nebeneinander geschrieben (Modi `trinary`, `scale` und `raw`, `negate`).

## Mehrere Karten gleichzeitig

Jede Datei öffnet sich in einem eigenen Tab; eine bereits geöffnete Datei erneut zu öffnen, wechselt zu ihrem Tab. `Strg+Tab` / `Strg+Umschalt+Tab` wechseln zwischen Tabs, `Strg+W` schließt einen (bei ungespeicherten Änderungen wird vorher gefragt). Mehrere Dateien lassen sich auf einmal hineinziehen.

Das Menü **Umwandeln** macht aus der aktuellen Karte eine andere Art in einem neuen Tab; das Original bleibt unverändert:

| Von \ Nach | Voxelkarte | Punktwolke | 2D-Raster |
|---|---|---|---|
| Voxelkarte | — | Voxelmitten | Höhenbereich projizieren |
| Punktwolke | mit gewählter Größe voxelisieren | — | voxelisieren, dann projizieren |
| 2D-Raster | Wände auf eine Höhe hochziehen | — | — |

## Kommandozeile

Ohne `--output` oder `--info` öffnet sich der Editor. Mit ihnen wird nichts angezeigt und die Arbeit im Terminal erledigt:

```bash
./mapbarber.sh room.bt --info
./mapbarber.sh room.bt --remove-islands 20 -o room_clean.bt
./mapbarber.sh room.bt --z-band 0.1 1.8 -o floor.yaml          # Octree -> ROS-Karte
./mapbarber.sh floor.yaml --clear-speckles 4 -o floor_clean.yaml
./mapbarber.sh floor.yaml --wall-height 2.0 -o walls.bt        # ROS-Karte -> Octree
./mapbarber.sh scan.pcd --remove-outliers 16 2.0 -o scan_clean.pcd
./mapbarber.sh scan.pcd -r 0.05 -o scan.bt                     # Wolke -> Octree
```

Die Endung der Ausgabedatei bestimmt das Ausgabeformat.

## Tastenkürzel

Die Kürzel folgen verbreiteten Desktop-Konventionen: Photoshop, Figma und PowerPoint für Werkzeuge und Einschränkungen, das Betriebssystem für Dateien und Bearbeiten. Unter macOS ist `Strg` die Taste `⌘`.

| Tasten | Aktion |
|---|---|
| `Strg+O` / `Strg+S` / `Strg+Umschalt+S` | öffnen / speichern / speichern unter oder exportieren |
| `Strg+N` / `Strg+Umschalt+N` | neue Voxelkarte / neues 2D-Raster |
| `Strg+W` / `Strg+Tab` / `Strg+Umschalt+Tab` | Tab schließen / nächster / vorheriger Tab |
| `Strg+Z` / `Strg+Umschalt+Z` oder `Strg+Y` | rückgängig / wiederholen |
| `H` `V` `E` `B` `L` `R` `G` `I` | navigieren, auswählen, radieren, hinzufügen·Stift, Linie, Rechteck, füllen, messen |
| `[` / `]` | kleinerer / größerer Pinsel |
| `Entf` / `Rücktaste` | Auswahl löschen / letzten Auswahlschritt zurücknehmen |
| `Strg+A` / `Strg+Umschalt+I` / `Esc` oder `Strg+D` | alles Sichtbare auswählen / umkehren / abwählen |
| links ziehen / Mitte ziehen oder `Leertaste`+ziehen / Rad | drehen / verschieben / zoomen (2D: mit Navigieren verschiebt links ziehen) |
| `Umschalt`+ziehen / `Umschalt`+rechts ziehen / Rechtsklick | Rechteckauswahl / Rechteck abwählen / abwählen |
| `Strg`+ziehen | bei stehender Ansicht fortlaufend mit dem Pinsel malen (auswählen oder radieren) |
| `Umschalt` / `Alt` beim Zeichnen | auf 0°·45°·90° einrasten bzw. Quadrat / von der Mitte aus |
| `1` `3` `7` / `0` oder `Pos1` | Ansicht vorne, Seite, oben / isometrisch (auch Ziffernblock) |
| `Strg+=` / `Strg+-` / `Strg+0` | vergrößern / verkleinern / an Fenster anpassen (2D) |
| `F11` / `F1` | Vollbild / Bedienung des aktuellen Editors |

## Sprachen

Die Oberfläche spricht English, 한국어, 日本語, 简体中文, Deutsch und Español, umschaltbar im Menü **Sprache**; die Wahl wird gespeichert. Für eine neue Sprache `mapbarber/locales/en.json` kopieren, die Werte übersetzen, den Code in `LANGUAGES` in `mapbarber/i18n.py` eintragen und die Tests ausführen – sie prüfen, dass jeder Schlüssel und jeder Platzhalter vorhanden ist.

## Hinweise zu Dateien

- **Als Octree gespeichert** werden nur belegte Zellen. Freiraum-Information aus der Quelldatei wird nicht zurückgeschrieben; das entspricht der üblichen Nutzung statischer Karten für die Kollisionsprüfung.
- **Als `.ot` gespeichert** erhält jede belegte Zelle denselben Log-Odds-Wert (3,5, p ≈ 0,97).
- **PCD / PLY** behalten alle Felder pro Punkt. Organisierte PCDs werden ohne ungültige (NaN-)Punkte geöffnet und unorganisiert gespeichert. `.xyz`, `.csv` und `.npy` enthalten nur Koordinaten; RGB-Spalten aus `.xyz` bleiben jedoch beim Speichern als PCD oder PLY erhalten. Komprimiertes binäres PCD wird nicht unterstützt.
- **Raster** folgen den map_server-Regeln: Modi `trinary`, `scale` und `raw`, `negate` und die in der YAML hinterlegten Schwellwerte für belegt und frei.
- **Sicherungen:** Beim Überschreiben bleibt die vorherige Datei als `name.bak_YYYYmmdd_HHMMSS` erhalten. Das lässt sich im Menü Datei abschalten.

## Funktionsweise

MapBarber ist eine eigenständige Implementierung auf Grundlage der veröffentlichten Dateiformate. Sie verwendet keinen Quellcode von OctoMap, PCL oder map_server und ist nicht davon abgeleitet.

- Octree-Dateien werden als *linearer Octree* gelesen und geschrieben. Belegte Zellen bilden ein sortiertes Array von Morton-Codes, sodass jeder Baumknoten ein zusammenhängender Abschnitt dieses Arrays ist und per Binärsuche gefunden wird. Ein Zeigerbaum wird nicht aufgebaut.
- Bearbeitet wird auf einem sortierten Array gepackter Zellschlüssel mit Mengenoperationen; Rückgängig und Wiederholen arbeiten ebenso.
- Zusammenhangskomponenten (Inseln, Sprenkel) und Nachbarschaftsabfragen nutzen SciPy, die Darstellung VTK-Glyphen in einem Qt-Fenster.

## Entwicklung

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                   # Kerntests, kein Bildschirm nötig
MAPBARBER_GUI_TESTS=1 .venv/bin/pytest            # zusätzlich End-to-End-Tests in einem echten Fenster
.venv/bin/python tools/make_examples.py            # examples/ neu erzeugen
.venv/bin/python tools/make_demo.py                # demo/ neu erzeugen (--large für Leistungsdateien)
.venv/bin/python tools/record_demo.py docs         # Animationen neu aufnehmen (benötigt ffmpeg)
.venv/bin/python tools/make_logo.py                # Symbol und Logos neu erzeugen
```

Mit `MAPBARBER_QT` = `PySide6`, `PySide2` oder `PyQt5` lässt sich die Qt-Anbindung wählen.

## Lizenz

[MIT](LICENSE). Frei nutzbar, veränderbar und weiterzugeben, auch kommerziell; es genügt, den Urheberrechtshinweis und den Lizenztext jeder Kopie beizulegen. Das gilt für Code, Übersetzungen, Logo, Symbole sowie die Beispiel- und Demokarten, die alle für dieses Projekt erstellt wurden.

Die verwendeten Bibliotheken behalten ihre eigenen Lizenzen: PySide6 (LGPL-3.0), VTK, NumPy und SciPy (BSD-3-Clause). Beim Start aus dem Quellcode oder bei der Installation mit pip ist nichts weiter nötig; wer ein Paket weitergibt, das sie enthält, findet die Pflichten in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Beiträge werden unter derselben Lizenz angenommen ([CONTRIBUTING.md](CONTRIBUTING.md)).
