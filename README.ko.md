<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="MapBarber — 로봇 맵을 위한 이발소" width="560">
  </picture>
</p>

**로봇 맵을 위한 이발소.** 잡음 많은 센서가 남긴 튀는 복셀·점·픽셀은 다듬고, 비어 있는 곳은 채웁니다. OctoMap 옥트리, 포인트 클라우드, ROS 2D 점유 격자를 한 창에서 편집합니다.

[English](README.md)

![세 종류 맵 열기, 복셀 맵을 2D 격자로 변환, 언어 전환](docs/overview.gif)

파일을 열거나 끌어다 놓으면 내용을 알아서 판별해 알맞은 편집기로 넘깁니다. 옥트리는 복셀 편집기, 포인트 클라우드는 점 편집기, 2D 점유 격자는 그림판 방식 편집기로 열립니다. 세 형식 사이의 변환도 되고, 저장하기 전까지는 모든 편집을 되돌릴 수 있습니다.

## 빠른 시작

```bash
git clone https://github.com/Hyounjun-Oh/mapbarber.git
cd mapbarber
./mapbarber.sh                      # 빈 창 — 맵 파일을 끌어다 놓으세요
./mapbarber.sh examples/room.bt     # 또는 파일을 바로 열기
```

처음 실행할 때 `.venv/`에 전용 가상환경을 만들고 NumPy, SciPy, VTK, PySide6를 설치합니다(약 500 MB). 그다음부터는 바로 실행됩니다. Python 3.10 이상과 데스크톱 환경이 필요합니다. X11에서 동작하고, Wayland에서는 스크립트가 XWayland를 자동으로 선택합니다.

## 지원 형식

| 맵 종류 | 파일 | 열리는 편집기 |
|---|---|---|
| 복셀 맵 | OctoMap `.bt`, `.ot` (`OcTree`, `OcTreeStamped`, `ColorOcTree`), 복셀 `.npz` | 복셀 편집기 |
| 포인트 클라우드 | `.pcd`, `.ply` (ascii/binary), `.xyz` / `.txt` / `.csv`, `.npy`, `.npz` | 포인트 클라우드 편집기 |
| 2D 점유 격자 | map_server `.yaml` + `.pgm` / `.png` / `.bmp`, 또는 이미지만 | 격자 편집기 |

확장자를 먼저 보고, 모르면 파일 서명으로 판별합니다. 그래서 `map.bt.bak_20240101` 같은 백업 파일도 옥트리로 열립니다.

## 편집기별 기능

![복셀 편집기](docs/voxel.gif)

**복셀 맵**: 붓 크기를 정할 수 있는 선택·지우기·추가 도구가 있고, Shift+끌기로 사각형 선택을 합니다("앞쪽 층만" 옵션). 고립 덩어리 선택은 공중에 떠 있는 잡음 덩어리를 찾아 주고, 상자 도구는 수치로 지정한 범위를 선택·지우기·채우기 합니다. 표시 범위를 좁히면 천장 등을 숨기고 안쪽을 편집할 수 있습니다.

![포인트 클라우드 편집기](docs/cloud.gif)

**포인트 클라우드**: 구 모양 붓으로 선택하거나 지우고, 통계적 이상점과 드문 점을 찾는 잡음 필터가 있습니다. 다운샘플(솎아내기)과 상자 자르기도 되고, 높이·저장된 색·intensity 같은 필드로 색을 칠할 수 있습니다. 점은 지우기만 하므로 PCD/PLY로 저장할 때 모든 필드가 유지됩니다.

![2D 격자 편집기](docs/grid.gif)

**2D 점유 격자**: 펜·직선·사각형·채우기 도구로 점유·빈 공간·미지를 칠합니다(O/F/U 키). 잡티 지우기와 미지 테두리 잘라내기가 있고, 테두리를 잘라내면 원점이 따라 옮겨져 맵 위치가 바뀌지 않습니다. 해상도와 원점도 편집할 수 있으며, 저장하면 이미지와 YAML을 함께 씁니다.

**변환** 메뉴는 복셀 맵 → 2D 격자(높이 구간 투영) / 포인트 클라우드, 포인트 클라우드 → 복셀 / 2D 격자, 2D 격자 → 복셀(벽 세우기)을 지원합니다.

## 명령행

```bash
./mapbarber.sh room.bt --remove-islands 20 -o room_clean.bt
./mapbarber.sh room.bt --z-band 0.1 1.8 -o floor.yaml
./mapbarber.sh floor.yaml --clear-speckles 4 -o floor_clean.yaml
./mapbarber.sh scan.pcd --remove-outliers 16 2.0 -o scan_clean.pcd
```

## 언어

English, 한국어, 日本語, 简体中文, Deutsch, Español을 지원하며, **언어** 메뉴에서 바꿀 수 있습니다.

## 구현

공개된 파일 구조만 보고 독립적으로 작성했습니다. OctoMap, PCL, map_server의 소스 코드는 사용하지도, 파생하지도 않았습니다. 옥트리 파일은 정렬된 Morton 코드 배열(선형 옥트리)로 읽고 씁니다.

## 라이선스

[Unlicense](LICENSE)에 따른 퍼블릭 도메인입니다. 출처 표시 없이 어떤 용도로든 쓸 수 있습니다. 의존 라이브러리는 각자의 라이선스를 따릅니다(PySide6 LGPL-3.0, VTK·NumPy·SciPy BSD-3-Clause).
