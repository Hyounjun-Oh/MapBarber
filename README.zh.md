<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — 机器人地图的理发店" width="560">
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.ko.md">한국어</a> · <a href="README.ja.md">日本語</a> · <b>简体中文</b> · <a href="README.de.md">Deutsch</a> · <a href="README.es.md">Español</a>
</p>

**机器人地图的理发店。** 修剪噪声传感器留下的多余体素、点和像素，并补上缺失的部分。在一个窗口中编辑 OctoMap 八叉树、点云和 ROS 二维占据栅格。

[![tests](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml/badge.svg)](https://github.com/Hyounjun-Oh/mapbarber/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![在标签页中打开三种地图、把体素地图转换为二维栅格并切换语言](docs/overview.gif)

打开或拖入文件后，MapBarber 会识别每个文件的内容，并用对应的编辑器在单独的标签页中打开：八叉树用体素编辑器，点云用点云编辑器，二维占据栅格用绘图式编辑器。三种格式之间可以互相转换，保存之前的每一步编辑都可以撤销。

## 快速开始

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                                      # 空窗口 — 把地图拖进来
./mapbarber.sh demo/office_octomap.bt demo/warehouse_map.yaml   # 或直接打开文件 (每个文件一个标签页)
```

首次运行时会在 `.venv/` 中创建专用虚拟环境并安装 NumPy、SciPy、VTK 和 PySide6 (约 500 MB)，之后会立即启动。需要 Python 3.10 或更高版本以及桌面环境。支持 X11；在 Wayland 下脚本会自动选择 XWayland。

更喜欢 pip？`pip install .` 会安装功能相同的 `mapbarber` 命令。

**用逼真的数据试一试：** [`demo/`](demo/README.md) 中有通过模拟传感器生成的地图，缺陷和真实尺寸都是已知的，还附有分步检查清单。

## 支持的格式

| 地图类型 | 文件 | 打开方式 |
|---|---|---|
| 体素地图 | OctoMap `.bt` (二进制)、`.ot` (`OcTree`、`OcTreeStamped`、`ColorOcTree`)、体素 `.npz` | 体素编辑器 |
| 点云 | `.pcd` (ascii、binary、有序)、`.ply` (ascii、binary)、`.xyz` / `.txt` / `.csv` (可带 RGB 列)、`.npy`、`.npz` | 点云编辑器 |
| 二维占据栅格 | map_server 的 `.yaml` + `.pgm` / `.png` / `.bmp`，或仅图像 | 栅格编辑器 |

先看扩展名，再看文件签名，所以像 `map.bt.bak_20240101` 这样的备份也能作为八叉树打开。只打开 `.pgm` 时，如果旁边有指向该图像的 `.yaml`，也会一并读取。损坏或无关的文件会被拒绝，并给出简短原因。

## 体素地图编辑器

![删除漂浮噪点和残影、补洞并添加体素](docs/voxel.gif)

- **工具：** 浏览 `H`、选择 `V`、擦除 `E`、添加 `B`、测量 `I`。画笔是 1–31 格的立方体，用 `[` 和 `]` 调整大小。添加会在点击的面外侧增加一层，或把体素放在水平工作平面上。
- **选择：** `Shift`+拖动选择屏幕矩形内的内容 (*仅最前一层* 会跳过被遮挡的体素)。右键单击取消选择光标下的内容，`Shift`+右键拖动按矩形取消选择。
- **选择孤立块** 会找出不与其他体素相连的小块，也就是深度相机产生的漂浮噪点。它只做选择，确认后再按 `Delete`。
- **方框：** 在三维视图中拖动彩色箭头可沿 x、y、z 移动，拖动面上的圆点可调整大小 (也可以输入数值)。然后可以选择、擦除或填充内部。
- **切片：** 用 x、y 或 z 方向的平面切开空间，只编辑一侧；另一侧会被隐藏并受到保护。拖动平面上的箭头移动位置，可切换到另一侧，完成后点击 *恢复视图*。
- **标尺：** 点击两个体素即可读出距离、Δx/Δy/Δz 以及以体素计的长度。按住 `Shift` 锁定到坐标轴，勾选 *吸附到体素中心* 可测量中心间距离。
- 上次保存后添加的体素显示为白色，已选内容显示为粉色。

## 点云编辑器

![选择离群点、擦除条纹噪声、按 intensity 着色并抽稀](docs/cloud.gif)

- **工具：** 浏览 `H`、选择 `V`、擦除 `E`、测量 `I`。以点击点为中心的球形画笔 (`[` / `]` 调整半径)、矩形选择和右键取消选择。
- **噪声过滤** 可选择统计离群点 (到邻居的平均距离明显偏大) 或稀疏点 (半径内邻居过少)。
- **抽稀** 在每个立方格只保留一个点。**方框** 和 **切片** 与体素编辑器相同，方框还可以擦除外部的所有点。
- **着色依据** 可选高度、存储的 RGB，或 `intensity`、`ring` 等任意数值字段。
- **标尺** 测量两个选中点之间的实际距离。
- 点只会被删除，因此保存为 PCD 时保留下来的点的所有字段都不会丢失，保存为 PLY 时所有标量字段都不会丢失。

## 二维占据栅格编辑器

![清除噪点、封住门口、绘制障碍物、补洞并裁剪边框](docs/grid.gif)

- **工具：** 浏览 `H`、画笔 `B`、直线 `L`、矩形 `R`、填充 `G`、测量 `I`。用 `O`、`F`、`U` 绘制 *占据*、*空闲*、*未知*，用 `[` / `]` 调整画笔粗细。
- **与 PowerPoint 相同的约束：** 按住 `Shift` 可把直线 (和标尺) 锁定为 0°、45° 或 90°，并把矩形变为正方形；`Alt` 从中心绘制矩形；画笔下 `Shift`+点击会从上一个点画直线。
- **清除噪点** 把孤立的小块占据区域变为空闲。
- **裁掉未知边框** 裁掉未探索的边距，并移动原点使地图上的内容位置不变。
- **地图信息** 可编辑分辨率和原点 (x、y、yaw)。红色和绿色箭头表示地图原点。
- **标尺** 以米和像素显示距离，并以地图坐标系给出 Δx/Δy (包括旋转的原点)。
- 缩小时细墙依然可见：占据优先于未知，未知优先于空闲。
- 保存时会并排写出图像和 map_server YAML (`trinary`、`scale`、`raw` 模式及 `negate`)。

## 同时编辑多张地图

每个文件在单独的标签页中打开，再次打开已打开的文件会切换到它的标签页。`Ctrl+Tab` / `Ctrl+Shift+Tab` 切换标签页，`Ctrl+W` 关闭 (有未保存的更改时会先询问)。也可以一次拖入多个文件。

**转换** 菜单会把当前地图转换为另一种类型并在新标签页中打开，原地图保持不变：

| 源 \ 目标 | 体素地图 | 点云 | 二维栅格 |
|---|---|---|---|
| 体素地图 | — | 体素中心 | 投影一个高度范围 |
| 点云 | 按指定尺寸体素化 | — | 体素化后投影 |
| 二维栅格 | 按高度拉伸墙体 | — | — |

## 命令行

不带 `--output` 或 `--info` 时会打开编辑器。带上它们时不显示窗口，直接在终端中处理：

```bash
./mapbarber.sh room.bt --info
./mapbarber.sh room.bt --remove-islands 20 -o room_clean.bt
./mapbarber.sh room.bt --z-band 0.1 1.8 -o floor.yaml          # 八叉树 -> ROS 地图
./mapbarber.sh floor.yaml --clear-speckles 4 -o floor_clean.yaml
./mapbarber.sh floor.yaml --wall-height 2.0 -o walls.bt        # ROS 地图 -> 八叉树
./mapbarber.sh scan.pcd --remove-outliers 16 2.0 -o scan_clean.pcd
./mapbarber.sh scan.pcd -r 0.05 -o scan.bt                     # 点云 -> 八叉树
```

输出文件的扩展名决定输出类型。

## 键盘快捷键

快捷键遵循常见的桌面惯例：工具和约束参照 Photoshop、Figma 和 PowerPoint，文件和编辑参照操作系统标准。在 macOS 上 `Ctrl` 为 `⌘`。

| 按键 | 操作 |
|---|---|
| `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | 打开 / 保存 / 另存为或导出 |
| `Ctrl+N` / `Ctrl+Shift+N` | 新建体素地图 / 新建二维栅格 |
| `Ctrl+W` / `Ctrl+Tab` / `Ctrl+Shift+Tab` | 关闭标签页 / 下一个 / 上一个标签页 |
| `Ctrl+Z` / `Ctrl+Shift+Z` 或 `Ctrl+Y` | 撤销 / 重做 |
| `H` `V` `E` `B` `L` `R` `G` `I` | 浏览、选择、擦除、添加·画笔、直线、矩形、填充、测量 |
| `[` / `]` | 缩小 / 放大画笔 |
| `Delete` / `Backspace` | 删除所选 / 撤销上一步选择 |
| `Ctrl+A` / `Ctrl+Shift+I` / `Esc` 或 `Ctrl+D` | 选择全部可见项 / 反选 / 取消选择 |
| 左键拖动 / 中键拖动或 `Space`+拖动 / 滚轮 | 旋转 / 平移 / 缩放 (二维：浏览工具下左键拖动平移) |
| `Shift`+拖动 / `Shift`+右键拖动 / 右键单击 | 矩形选择 / 矩形取消选择 / 取消选择 |
| `Ctrl`+拖动 | 视图不动，用画笔连续涂抹 (选择或擦除) |
| 绘制时按 `Shift` / `Alt` | 锁定 0°·45°·90° 或正方形 / 从中心绘制 |
| `1` `3` `7` / `0` 或 `Home` | 前视、侧视、俯视 / 等轴测视图 (小键盘也可) |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | 放大 / 缩小 / 适应窗口 (二维) |
| `F11` / `F1` | 全屏 / 当前编辑器的操作说明 |

## 语言

界面支持 English、한국어、日本語、简体中文、Deutsch 和 Español，可在 **语言** 菜单中切换，选择会被记住。如需添加语言，复制 `mapbarber/locales/en.json` 并翻译其中的值，在 `mapbarber/i18n.py` 的 `LANGUAGES` 中加入语言代码，然后运行测试——测试会检查每个键和占位符是否齐全。

## 文件说明

- **八叉树文件保留原有信息。** 从 `.bt`、`.ot` 读入的空闲空间会原样写回，只在添加体素的位置被切开。`.ot` 还保留每个单元的占用概率值以及 `ColorOcTree` 的颜色。新添加的体素取 log-odds 3.5 (p ≈ 0.97) 和白色，擦除的体素变为 *未知* 而不是空闲。
- **格式存不下的信息会在写入前说明。** 把 `.ot` 地图存为 `.bt` 时，数值只剩占用/空闲且颜色丢失；把八叉树存为点云时空闲空间丢失。对话框会准确列出将被舍弃的内容（命令行输出到 stderr），在你同意之前不会写入任何内容。
- **PCD** 保留每个点的全部字段、`VIEWPOINT`，并且在没有删除点时保留有序的 `WIDTH`/`HEIGHT`。**PLY** 保留所有标量字段；向量字段和 64 位整数无法存储并会提示，源文件中的 face 等非顶点元素同样会提示。`.xyz`/`.csv` 保存坐标（六位小数）以及 RGB（如有），`.npy` 只保存坐标。不支持压缩二进制 PCD。*抽稀* 保留每个格子中最先读入的点。
- **栅格** 遵循 map_server 规则：`trinary`、`scale`、`raw` 模式，`negate`，以及 YAML 中的占用/空闲阈值。编辑器使用三种状态，但未改动的单元按原像素值保存，因此带灰度的 `scale`/`raw` 地图在编辑其他位置后保持不变。
- **备份：** 覆盖文件时会把原文件保留为 `name.bak_YYYYmmdd_HHMMSS`。可在文件菜单中关闭。

## 实现原理

MapBarber 是根据公开的文件结构独立编写的实现，没有使用 OctoMap、PCL 或 map_server 的源代码，也不是由它们派生而来。

- 八叉树文件以 *线性八叉树* 的方式读写。占据的格子组成一个已排序的 Morton 码数组，树的每个节点都是该数组中的一段连续区间，通过二分查找定位，不构建指针树。
- 编辑在已排序的压缩格子键数组上通过集合运算完成，撤销和重做也采用同样的方式。
- 连通分量 (孤立块、噪点) 和邻域查询使用 SciPy，渲染使用 Qt 窗口中的 VTK 字形。

## 开发

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                   # 核心测试，无需显示器
MAPBARBER_GUI_TESTS=1 .venv/bin/pytest            # 另外在真实窗口中运行端到端测试
.venv/bin/python tools/make_examples.py            # 重新生成 examples/
.venv/bin/python tools/make_demo.py                # 重新生成 demo/ (加 --large 生成性能测试文件)
.venv/bin/python tools/record_demo.py docs         # 重新录制动画 (需要 ffmpeg)
.venv/bin/python tools/make_logo.py                # 重新生成图标和标志
```

把 `MAPBARBER_QT` 设为 `PySide6`、`PySide2` 或 `PyQt5` 可选择 Qt 绑定。

## 许可证

采用 [MIT](LICENSE) 许可证。可以自由使用、修改和再分发 (包括商业用途)，只需在副本中保留版权声明和许可证全文。代码、翻译、标志、图标以及示例和演示地图均在此范围内，且全部为本项目原创。

所依赖的库遵循各自的许可证：PySide6 (LGPL-3.0)、VTK、NumPy 和 SciPy (BSD-3-Clause)。从源码运行或用 pip 安装时无需额外处理；如果要再分发包含这些库的打包版本，请参阅 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。贡献内容按相同许可证接受 ([CONTRIBUTING.md](CONTRIBUTING.md))。
