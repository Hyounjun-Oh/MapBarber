<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — ロボットマップのための床屋" width="560">
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <b>日本語</b> · <a href="README.zh.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <a href="README.es.md">Español</a>
</p>

**ロボットマップのための床屋。** ノイズの多いセンサーが残したはみ出したボクセル・点・ピクセルを整え、欠けた部分を埋めます。OctoMap のオクトリー、点群、ROS の 2D 占有グリッドを 1 つのウィンドウで編集できます。

[![tests](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Unlicense%20OR%20MIT-green)

![3 種類のマップをタブで開き、ボクセルマップを 2D グリッドに変換し、言語を切り替える様子](docs/overview.gif)

ファイルを開くかドロップすると、MapBarber が中身を判別し、対応するエディタで個別のタブに開きます。オクトリーはボクセルエディタ、点群は点群エディタ、2D 占有グリッドはペイント型エディタで開きます。3 つの形式の間で変換でき、保存するまでどの編集も元に戻せます。

## クイックスタート

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                                      # 空のウィンドウ — マップをドロップ
./mapbarber.sh demo/office_octomap.bt demo/warehouse_map.yaml   # ファイルを直接開く (1 ファイル 1 タブ)
```

初回起動時に `.venv/` に専用の仮想環境を作り、NumPy、SciPy、VTK、PySide6 をインストールします (約 500 MB)。2 回目以降はすぐに起動します。Python 3.10 以上とデスクトップ環境が必要です。X11 で動作し、Wayland ではスクリプトが自動で XWayland を選びます。

pip を使う場合は `pip install .` で同じ働きをする `mapbarber` コマンドが入ります。

**実データに近いマップで試す:** [`demo/`](demo/README.md) には、センサーをシミュレートして作ったマップがあります。欠陥と実寸がわかっているマップと、手順付きのチェックリストが入っています。

## 対応形式

| マップの種類 | ファイル | 開くエディタ |
|---|---|---|
| ボクセルマップ | OctoMap `.bt` (バイナリ)、`.ot` (`OcTree`、`OcTreeStamped`、`ColorOcTree`)、ボクセル `.npz` | ボクセルエディタ |
| 点群 | `.pcd` (ascii、binary、organized)、`.ply` (ascii、binary)、`.xyz` / `.txt` / `.csv` (RGB 列は任意)、`.npy`、`.npz` | 点群エディタ |
| 2D 占有グリッド | map_server の `.yaml` + `.pgm` / `.png` / `.bmp`、または画像のみ | グリッドエディタ |

まず拡張子、次にファイルのシグネチャで判別するので、`map.bt.bak_20240101` のようなバックアップもオクトリーとして開けます。`.pgm` だけを開いても、その画像を指す `.yaml` が隣にあれば一緒に読み込みます。壊れたファイルや無関係なファイルは短い理由とともに拒否されます。

## ボクセルマップエディタ

![浮いたノイズと残像を消し、穴を埋め、ボクセルを追加する様子](docs/voxel.gif)

- **ツール:** ナビゲート `H`、選択 `V`、消去 `E`、追加 `B`、計測 `I`。ブラシは 1〜31 セルの立方体で、`[` と `]` でサイズを変えます。追加はクリックした面の外側に一層積むか、水平な作業平面にボクセルを置きます。
- **選択:** `Shift`+ドラッグで画面上の矩形内を選択します (*手前の層のみ* は隠れたボクセルを除外)。右クリックでカーソル下の選択を解除し、`Shift`+右ドラッグで矩形の選択を解除します。
- **孤立クラスタを選択** は、何にも接していないボクセルの塊、つまり深度カメラが生む空中のノイズを見つけます。選択するだけなので、確認してから `Delete` を押せます。
- **ボックス:** 3D ビューで色付きの矢印をドラッグすると x・y・z 方向に移動し、面の点をドラッグするとサイズが変わります (数値入力も可)。その後、内側を選択・消去・塗りつぶしできます。
- **スライス:** x・y・z の平面で空間を切り、片側だけを編集します。反対側は非表示になり保護されます。平面の矢印をドラッグして位置を動かし、側を反転し、終わったら *表示を復元* を押します。
- **ルーラー:** 2 つのボクセルをクリックすると距離、Δx/Δy/Δz、ボクセル数換算の長さが表示されます。`Shift` で軸方向に固定、*ボクセル中心にスナップ* で中心間の距離を測ります。
- 保存後に追加したボクセルは白、選択はピンクで表示されます。

## 点群エディタ

![外れ値を選択し、筋状のノイズを消し、intensity で色分けし、間引く様子](docs/cloud.gif)

- **ツール:** ナビゲート `H`、選択 `V`、消去 `E`、計測 `I`。クリックした点の周りの球形ブラシ (`[` / `]` で半径を変更)、矩形選択、右クリックでの選択解除が使えます。
- **ノイズフィルタ** は統計的な外れ値 (近傍までの平均距離が大きく離れた点) や、まばらな点 (半径内の近傍が少なすぎる点) を選択します。
- **間引く** は立方体セルごとに 1 点だけを残します。**ボックス** と **スライス** はボクセルエディタと同じで、ボックスの外側をすべて消すこともできます。
- **色分け** は高さ、保存された RGB、または `intensity`・`ring` などの数値フィールドから選べます。
- **ルーラー** は選んだ 2 点間の実距離を測ります。
- 点は削除されるだけなので、PCD・PLY に保存しても残った点のすべてのフィールドが保持されます。

## 2D 占有グリッドエディタ

![ゴミを消し、出入口を塞ぎ、障害物を描き、穴を埋め、余白を切り取る様子](docs/grid.gif)

- **ツール:** ナビゲート `H`、ペン `B`、直線 `L`、矩形 `R`、塗りつぶし `G`、計測 `I`。`O`、`F`、`U` で *占有*、*空き*、*未知* を塗り、`[` / `]` でペンの太さを変えます。
- **PowerPoint と同じ拘束:** `Shift` を押すと直線 (とルーラー) が 0°・45°・90° に固定され、矩形は正方形になります。`Alt` は矩形を中心から描き、ペンで `Shift`+クリックすると最後の点から直線を引きます。
- **ゴミを消す** は小さく孤立した占有の塊を空きに変えます。
- **未知の余白を切り取る** は未探索の余白を切り取り、マップ上のものが動かないよう原点を移動します。
- **マップ情報** で解像度と原点 (x、y、yaw) を編集します。赤と緑の矢印がマップ原点です。
- **ルーラー** は距離をメートルとピクセルで、Δx/Δy をマップ座標系で表示します (回転した原点にも対応)。
- 縮小しても細い壁が見えます。占有が未知より、未知が空きより優先して描かれます。
- 保存すると画像と map_server の YAML を並べて書き出します (`trinary`、`scale`、`raw` モード、`negate`)。

## 複数のマップを同時に

ファイルはそれぞれ個別のタブで開き、すでに開いているファイルを開くとそのタブに切り替わります。`Ctrl+Tab` / `Ctrl+Shift+Tab` でタブを移動し、`Ctrl+W` で閉じます (未保存の変更があれば先に確認します)。複数のファイルをまとめてドロップすることもできます。

**変換** メニューは現在のマップを別の種類に変換して新しいタブで開きます。元のマップはそのままです。

| 変換元 \ 変換先 | ボクセルマップ | 点群 | 2D グリッド |
|---|---|---|---|
| ボクセルマップ | — | ボクセル中心 | 高さの範囲を投影 |
| 点群 | 指定サイズでボクセル化 | — | ボクセル化してから投影 |
| 2D グリッド | 指定の高さで壁を立てる | — | — |

## コマンドライン

`--output` や `--info` がなければエディタが開きます。あれば画面を出さずにターミナルで処理します。

```bash
./mapbarber.sh room.bt --info
./mapbarber.sh room.bt --remove-islands 20 -o room_clean.bt
./mapbarber.sh room.bt --z-band 0.1 1.8 -o floor.yaml          # オクトリー -> ROS マップ
./mapbarber.sh floor.yaml --clear-speckles 4 -o floor_clean.yaml
./mapbarber.sh floor.yaml --wall-height 2.0 -o walls.bt        # ROS マップ -> オクトリー
./mapbarber.sh scan.pcd --remove-outliers 16 2.0 -o scan_clean.pcd
./mapbarber.sh scan.pcd -r 0.05 -o scan.bt                     # 点群 -> オクトリー
```

出力の拡張子で出力形式が決まります。

## キーボードショートカット

ショートカットは一般的なデスクトップの慣例に従います。ツールと拘束は Photoshop・Figma・PowerPoint、ファイルと編集は OS の標準です。macOS では `Ctrl` は `⌘` です。

| キー | 動作 |
|---|---|
| `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | 開く / 保存 / 名前を付けて保存・エクスポート |
| `Ctrl+N` / `Ctrl+Shift+N` | 新しいボクセルマップ / 新しい 2D グリッド |
| `Ctrl+W` / `Ctrl+Tab` / `Ctrl+Shift+Tab` | タブを閉じる / 次のタブ / 前のタブ |
| `Ctrl+Z` / `Ctrl+Shift+Z` または `Ctrl+Y` | 元に戻す / やり直す |
| `H` `V` `E` `B` `L` `R` `G` `I` | ナビゲート、選択、消去、追加・ペン、直線、矩形、塗りつぶし、計測 |
| `[` / `]` | ブラシを小さく / 大きく |
| `Delete` または `Backspace` | 選択を削除 |
| `Ctrl+A` / `Ctrl+Shift+I` / `Esc` または `Ctrl+D` | 表示中をすべて選択 / 反転 / 選択解除 |
| 左ドラッグ / 中ドラッグまたは `Space`+ドラッグ / ホイール | 回転 / 移動 / ズーム (2D: ナビゲート時は左ドラッグで移動) |
| `Shift`+ドラッグ / `Shift`+右ドラッグ / 右クリック | 矩形選択 / 矩形で選択解除 / 選択解除 |
| 描画中の `Shift` / `Alt` | 0°・45°・90° に固定または正方形 / 中心から描く |
| `1` `3` `7` / `0` または `Home` | 前、横、上 / 等角ビュー (テンキーも可) |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | 拡大 / 縮小 / ウィンドウに合わせる (2D) |
| `F11` / `F1` | 全画面表示 / 現在のエディタの操作方法 |

## 言語

画面は English、한국어、日本語、简体中文、Deutsch、Español に対応し、**言語** メニューで切り替えられます。選択は記憶されます。言語を追加するには `mapbarber/locales/en.json` をコピーして値を翻訳し、`mapbarber/i18n.py` の `LANGUAGES` にコードを追加してテストを実行してください。すべてのキーとプレースホルダーがあるかをテストが確認します。

## ファイルに関する注意

- **オクトリーとして保存** すると占有セルだけを書き出します。元のファイルにある空き空間の情報は書き戻しません。静的マップを衝突判定に使う一般的な使い方と同じです。
- **`.ot` で保存** すると、すべての占有セルに同じ log-odds 値 (3.5、p ≈ 0.97) を使います。
- **PCD / PLY** は点のすべてのフィールドを保持します。organized PCD は無効 (NaN) な点を飛ばして開き、unorganized として保存します。`.xyz`、`.csv`、`.npy` は座標だけを持ちます。ただし `.xyz` の RGB 列は PCD や PLY に保存すると保持されます。圧縮バイナリ PCD には対応していません。
- **グリッド** は map_server の規則に従います。`trinary`、`scale`、`raw` モード、`negate`、YAML に書かれた占有・空きのしきい値をそのまま使います。
- **バックアップ:** ファイルを上書きすると以前のファイルが `name.bak_YYYYmmdd_HHMMSS` として残ります。ファイルメニューでオフにできます。

## 仕組み

MapBarber は公開されているファイル構造だけを基に独自に実装したものです。OctoMap、PCL、map_server のソースコードは使用しておらず、そこから派生してもいません。

- オクトリーファイルは *線形オクトリー* として読み書きします。占有セルは Morton コードのソート済み配列で、木の各ノードはこの配列の連続区間なので二分探索で見つかります。ポインタの木は作りません。
- 編集は圧縮したセルキーのソート済み配列に対する集合演算で行い、元に戻す・やり直すも同じ方式です。
- 連結成分 (孤立クラスタ、ゴミ) と近傍探索には SciPy を、描画には Qt ウィンドウ内の VTK グリフを使います。

## 開発

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                   # コアのテスト、画面は不要
MAPBARBER_GUI_TESTS=1 .venv/bin/pytest            # 実際のウィンドウでのエンドツーエンドテストも実行
.venv/bin/python tools/make_examples.py            # examples/ を再生成
.venv/bin/python tools/make_demo.py                # demo/ を再生成 (--large で性能確認用ファイル)
.venv/bin/python tools/record_demo.py docs         # アニメーションを再録画 (ffmpeg が必要)
.venv/bin/python tools/make_logo.py                # アイコンとロゴを再生成
```

`MAPBARBER_QT` を `PySide6`、`PySide2`、`PyQt5` のいずれかにすると Qt バインディングを選べます。

## ライセンス

[Unlicense](UNLICENSE) または [MIT ライセンス](LICENSE-MIT) のどちらかを選べるデュアルライセンスです ([COPYING](COPYING) を参照)。要するに、クレジットの有無を問わず、どんな用途にも使えます。コード、翻訳、ロゴ、アイコン、サンプルとデモのマップのすべてが対象で、いずれもこのプロジェクトのために作ったものです。

依存ライブラリはそれぞれのライセンスに従います。PySide6 (LGPL-3.0)、VTK・NumPy・SciPy (BSD-3-Clause)。ソースから実行する場合や pip でインストールする場合は追加の対応は不要です。これらを同梱して再配布する場合は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。コントリビューションも同じ条件で受け付けます ([CONTRIBUTING.md](CONTRIBUTING.md))。
