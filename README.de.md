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
| Punktwolke (weitere) | `.las` / `.laz` (nach `pip install "laspy[lazrs]"`), LiDAR-`.bin`-Scans (x y z intensity) | Punktwolken-Editor |
| Frame-Sequenz | ein **Ordner** mit Scans und Posen: KITTI odometry (`velodyne/` + `poses.txt`), KITTI raw (`velodyne_points/` + `oxts/`) oder ein beliebiger Ordner mit `.pcd` / `.ply` / `.las` / `.bin` und einer Posendatei (TUM, 3×4- oder 4×4-Matrizen, CSV mit Kopfzeile) | Punktwolken-Editor im Beschriftungsmodus |
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
- Punkte werden nur entfernt, daher bleiben beim Speichern als PCD alle Felder jedes übrigen Punkts erhalten, als PLY alle skalaren Felder.

## Beschriften

Im Punktwolken- oder Voxel-Editor den **Beschriftungsmodus** in der Werkzeugleiste einschalten (`Strg+L`). Werkzeuge und Panel wechseln zum Beschriften; Ausschalten kehrt genau so zum Bearbeiten zurück, wie es war. Alles läuft offline auf der CPU, und die ursprünglichen Punkte werden nie verschoben oder verworfen.

- **Klassen:** eine Liste mit Nummer, Name, Farbe und der Bedeutung in einer Karte (Hindernis, befahrbare Fläche, ignorieren). Vorlagen für Innenraum-Roboter, SemanticKITTI und LAS-Codes; `labels.yaml` laden oder speichern. Das Auge blendet eine Klasse aus, das Schloss friert sie ein; ein Klick auf Auge oder Schloss im Kopf gilt für alle Klassen.
- **Beschriften:** mit einem beliebigen Werkzeug auswählen und `Enter` (*Label-Mapping*) oder `Strg+1`…`Strg+9` drücken, oder mit dem Beschriftungspinsel `B` malen. `Strg`+Ziehen malt bei fester Ansicht, `Strg`+Rechtsziehen nimmt zurück.
- **Beschriftete Punkte schützen** (Schalter oben rechts in der Ansicht oder `P`): beschriftete Punkte bleiben außerhalb der Auswahl und behalten ihre Beschriftung, sodass eine weite Auswahl einer Wand oder des Bodens zuvor beschriftete Objekte überspringt.
- **Smart-Auswahl `W`:** ein Klick findet ein *zusammenhängendes Objekt*, eine *ebene Fläche* oder eine *glatte Fläche*. Ein zusammenhängendes Objekt endet am Boden (Bodenabstand) und bei dichten Daten an breiten Flächen anderer Richtung; `[` / `]` lockern oder verengen die letzte Auswahl. Der **Bodenfilter** wählt den Boden oder alles, was darauf steht.
- **Prüfen:** Fortschrittsbalken, *Nächstes Unbeschriftetes* (`N`), zweifelhafte Beschriftungen, kleine Inseln und *Lücken vorschlagen*; Vorschläge erscheinen blass, bis sie bestätigt sind.
- **Objekte und 3D-Quader:** eine Klasse wählen und *Quader für jedes Objekt …* drücken: ihre Punkte werden in einzelne Objekte geteilt, und jedes erhält einen aufrechten Quader, der sich bearbeiten, neu anpassen oder löschen lässt. *Nur Klasse behalten* macht aus Instanzen wieder einfache Klassen. Wenige falsch beschriftete Punkte verderben keinen Quader: Gruppen abseits des Objektkörpers und dünne Ausläufer hinter einer Lücke bleiben beim Anpassen außen vor, und der Quader wird an den Flächen des Objekts ausgerichtet. Die Quaderliste zeigt, wie viele Punkte ein Quader auslässt, und *Ausreißer der Boxen auswählen* wählt sie zum Ansehen oder Löschen aus (*Ausreißer aus Boxen heraushalten* ausschalten, um um alle beschrifteten Punkte anzupassen).
- **Frames:** einen Ordner mit Scans öffnen. Die Zeitleiste unter der Ansicht legt den ersten und letzten angezeigten Frame fest; die Frames werden nach ihren Posen zusammengeführt, während jede Beschriftung bei ihrem Frame bleibt. Beschriftungen lassen sich als Vorschläge auf andere Frames übertragen und Konflikte zwischen Frames auflisten. *Ansicht fest an* auf derselben Leiste legt fest, was beim Wechsel der Frames stehen bleibt: die Welt, der LiDAR oder der in der Quaderliste gewählte Quader.
- **Verfolgen:** Objekte in einem Frame mit Quadern versehen, den Frame-Bereich setzen und *Quader verfolgen*. Vorwärts wird jedes Objekt im nächsten Frame über die Quaderüberlappung (IoU) gefunden, seine Punkte werden ausgerichtet (ICP) und in einem Modell gesammelt, sodass der Quader mit wechselnder Ansicht zum ganzen Objekt wächst. Danach wird jeder Frame, auch frühere, erneut an das fertige Modell angepasst: eine Quadergröße je Objekt, und Punkte, die ein früher, unvollständiger Quader verfehlte, werden nachgeholt. Als *formverändernd* markierte Klassen (Personen) erhalten einen Quader je Frame. Niedrige Werte kommen als Vorschläge mit `?`; *Punkte außerhalb der Quader wählen* zeigt, was noch an einem Objekt hängt, und *Sie ihren Objekten geben* übernimmt es und vergrößert den Quader.
- **Voxel:** Wird eine Wolke zu Voxeln, erhält jedes Voxel die Klasse der meisten seiner Punkte. Zurück zu Punkten erhält jeder Punkt wieder seine eigene Beschriftung; nur umbeschriftete Voxel geben ihre Klasse weiter.
- **Dateien:** Beschriftungen liegen in der Datei, wo das Format es erlaubt (Felder `label` / `instance` in PCD und PLY, `classification` in LAS), als `.label`-Dateien bei `.bin`-Sequenzen oder neben der Datei (`name.labels.npz`). *In Standardformaten exportieren* schreibt eine SemanticKITTI-Sequenz, KITTI-Objektlabels und OpenPCDet-Quader.
- `Strg+Z` umfasst Beschriftungen, Klassen, Quader und Verfolgung. `Entf` löscht im Beschriftungsmodus nie Punkte: es entfernt Beschriftungen oder löscht den zuletzt angeklickten Quader bzw. das Objekt.

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
| `Strg+L` | Beschriftungsmodus an / aus |
| `B` / `W` (Beschriftungsmodus) | Beschriftungspinsel / Smart-Auswahl |
| `Enter` / `Strg+1`…`Strg+9` / `Strg+0` oder `Entf` | Auswahl mit der aktiven Klasse / der n-ten Klasse beschriften / Beschriftung entfernen |
| `P` / `N` / `Alt`+Klick | beschriftete Punkte schützen / nächster unbeschrifteter Bereich / Klasse unter dem Mauszeiger übernehmen |
| `Strg`+Rechtsziehen | mit dem Pinsel zurücknehmen (abwählen oder Beschriftung entfernen), die Ansicht bleibt stehen |
| `,` / `.`  ·  Zeitleiste anklicken, dann `←` / `→` | vorheriger / nächster Frame  ·  den Frame-Bereich um seine eigene Breite verschieben (`Umschalt`: um einen Frame) |

## Sprachen

Die Oberfläche spricht English, 한국어, 日本語, 简体中文, Deutsch und Español, umschaltbar im Menü **Sprache**; die Wahl wird gespeichert. Für eine neue Sprache `mapbarber/locales/en.json` kopieren, die Werte übersetzen, den Code in `LANGUAGES` in `mapbarber/i18n.py` eintragen und die Tests ausführen – sie prüfen, dass jeder Schlüssel und jeder Platzhalter vorhanden ist.

## Hinweise zu Dateien

- **Octree-Dateien behalten, was sie enthielten.** Freiraum aus einer `.bt`- oder `.ot`-Datei wird wieder geschrieben und nur dort aufgeteilt, wo Sie Voxel hinzufügen; eine `.ot`-Datei behält außerdem den Belegungswert jeder Zelle und bei einem `ColorOcTree` die Farbe. Hinzugefügte Voxel erhalten Log-Odds 3.5 (p ≈ 0,97) und Weiß; gelöschte Voxel werden *unbekannt*, nicht frei.
- **Was ein Format nicht speichern kann, sagt MapBarber vor dem Schreiben.** Eine `.ot`-Karte als `.bt` zu speichern reduziert die Werte auf belegt/frei und verwirft Farben; ein Octree als Punkte verliert den Freiraum. Der Dialog nennt genau, was wegfiele (die Kommandozeile schreibt es nach stderr), und nichts wird geschrieben, bevor Sie zustimmen.
- **PCD** behält alle Punktfelder, den `VIEWPOINT` und das organisierte `WIDTH`/`HEIGHT`, solange kein Punkt entfernt wurde. **PLY** behält alle skalaren Felder; Vektorfelder und 64-Bit-Ganzzahlen lassen sich nicht speichern und werden gemeldet, ebenso Flächen oder andere Nicht-Vertex-Elemente der Quelldatei. `.xyz`/`.csv` enthalten Koordinaten (sechs Nachkommastellen) und RGB, falls vorhanden, `.npy` nur Koordinaten. Komprimiertes binäres PCD wird nicht unterstützt. *Ausdünnen* behält pro Zelle den zuerst gelesenen Punkt.
- **Raster** folgen den map_server-Regeln: die Modi `trinary`, `scale` und `raw`, `negate` sowie die Schwellwerte aus der YAML-Datei. Der Editor arbeitet mit drei Zuständen, aber unberührte Zellen werden mit ihrem ursprünglichen Pixelwert gespeichert, sodass abgestufte `scale`/`raw`-Karten eine Bearbeitung an anderer Stelle überstehen.
- **Sicherungen:** Beim Überschreiben bleibt die vorherige Datei als `name.bak_YYYYmmdd_HHMMSS` erhalten. Das lässt sich im Menü Datei abschalten.

## Funktionsweise

MapBarber ist eine eigenständige Implementierung auf Grundlage der veröffentlichten Dateiformate. Sie verwendet keinen Quellcode von OctoMap, PCL oder map_server und ist nicht davon abgeleitet.

- Octree-Dateien werden als *linearer Octree* gelesen und geschrieben. Belegte Zellen bilden ein sortiertes Array von Morton-Codes, sodass jeder Baumknoten ein zusammenhängender Abschnitt dieses Arrays ist und per Binärsuche gefunden wird. Ein Zeigerbaum wird nicht aufgebaut.
- Bearbeitet wird auf einem sortierten Array gepackter Zellschlüssel mit Mengenoperationen; Rückgängig und Wiederholen arbeiten ebenso.
- Zusammenhangskomponenten (Inseln, Sprenkel) und Nachbarschaftsabfragen nutzen SciPy, die Darstellung VTK-Glyphen in einem Qt-Fenster.

## Lizenz

[MIT](LICENSE). Frei nutzbar, veränderbar und weiterzugeben, auch kommerziell; es genügt, den Urheberrechtshinweis und den Lizenztext jeder Kopie beizulegen. Das gilt für Code, Übersetzungen, Logo, Symbole sowie die Beispiel- und Demokarten, die alle für dieses Projekt erstellt wurden.

Die verwendeten Bibliotheken behalten ihre eigenen Lizenzen: PySide6 (LGPL-3.0), VTK, NumPy und SciPy (BSD-3-Clause). Beim Start aus dem Quellcode oder bei der Installation mit pip ist nichts weiter nötig; wer ein Paket weitergibt, das sie enthält, findet die Pflichten in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Beiträge werden unter derselben Lizenz angenommen ([CONTRIBUTING.md](CONTRIBUTING.md)).
