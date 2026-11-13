"""Make the 2 x 3 feature animation of the README and the wiki home from the full animations in docs/media/.

    python tools/make_mosaic.py docs/media/        (needs ffmpeg; writes home.webp and home_ko.webp there)

Each cell keeps the map view of one animation (no menus, side panel or captions), cut to 4:3, with rounded
corners and the name of the feature on a shaded band at its foot. Every animation is played faster or slower so
that it lasts exactly DURATION seconds: all six start and end together, then start again.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

EDITING, LABELING = (79, 156, 247), (76, 194, 106)
CELLS = (("voxel.gif", "Voxel editor", "복셀 편집기", EDITING),
         ("cloud.gif", "Point cloud editor", "포인트 클라우드 편집기", EDITING),
         ("grid.gif", "2D grid editor", "2D 격자 편집기", EDITING),
         ("labeling.gif", "Point cloud labeling", "포인트 클라우드 라벨링", LABELING),
         ("boxes.gif", "3D object labeling", "3D 물체 라벨링", LABELING),
         ("auto_labeling.webp", "Auto 3D box labeling", "자동 3D 박스 라벨링", LABELING))
COLUMNS = 3
CELL = (360, 270)
GAP = 8
RADIUS = 12
BAND = 58
FPS = 12
DURATION = 15.0
BACKGROUND = (22, 24, 29)
FONTS = {"en": ("/usr/share/fonts/truetype/noto/NotoSansDisplay-SemiBold.ttf", 0, 21),
         "ko": ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1, 20)}
WINDOW_VIEW = (0.0, 0.20, 0.60, 0.84)
CROPPED_VIEW = (0.0, 0.15, 1.0, 0.80)


def to_cell(frame, view):
    """The map view of a frame: `view` is (left, top, right, bottom) as shares of the frame, then 4:3 and cell size."""
    width, height = frame.size
    frame = frame.crop((int(view[0] * width), int(view[1] * height), int(view[2] * width), int(view[3] * height)))
    width, height = frame.size
    if width / height > CELL[0] / CELL[1]:
        keep = int(round(height * CELL[0] / CELL[1]))
        frame = frame.crop(((width - keep) // 2, 0, (width - keep) // 2 + keep, height))
    else:
        keep = int(round(width * CELL[1] / CELL[0]))
        frame = frame.crop((0, (height - keep) // 2, width, (height - keep) // 2 + keep))
    return frame.resize(CELL, Image.LANCZOS)


def read_frames(path, work):
    """The frames of an animation at FPS, as cell-sized images."""
    if path.endswith(".webp"):
        image, frames = Image.open(path), []
        for index in range(image.n_frames):
            image.seek(index)
            cell = to_cell(image.convert("RGB"), CROPPED_VIEW)
            frames += [cell] * max(1, int(round(image.info.get("duration", 1000 / FPS) * FPS / 1000)))
        return frames
    folder = tempfile.mkdtemp(dir=work)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"fps={FPS}", os.path.join(folder, "%05d.png")],
                   check=True)
    return [to_cell(Image.open(os.path.join(folder, name)).convert("RGB"), WINDOW_VIEW)
            for name in sorted(os.listdir(folder))]


def overlay(label, colour, font):
    """The shaded band with the feature's name, as an RGBA layer the size of a cell."""
    layer = Image.new("RGBA", CELL, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for row in range(BAND):
        alpha = int(225 * (row / BAND) ** 1.4)
        draw.line([(0, CELL[1] - BAND + row), (CELL[0], CELL[1] - BAND + row)], fill=(10, 12, 16, alpha))
    middle = CELL[1] - 22
    draw.rounded_rectangle((16, middle - 10, 20, middle + 10), 2, fill=colour + (255,))
    box = draw.textbbox((0, 0), label, font=font)
    draw.text((30, middle - (box[1] + box[3]) / 2), label, font=font, fill=(255, 255, 255, 255))
    return layer


def main(docs):
    work = tempfile.mkdtemp(prefix="mosaic_")
    try:
        clips = [read_frames(os.path.join(docs, cell[0]), work) for cell in CELLS]
        length = int(round(DURATION * FPS))
        rows = -(-len(CELLS) // COLUMNS)
        size = (COLUMNS * CELL[0] + (COLUMNS + 1) * GAP, rows * CELL[1] + (rows + 1) * GAP)
        mask = Image.new("L", CELL, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, CELL[0] - 1, CELL[1] - 1), RADIUS, fill=255)
        for language, column in (("en", 1), ("ko", 2)):
            path, index, points = FONTS[language]
            font = ImageFont.truetype(path, points, index=index)
            layers = [overlay(cell[column], cell[3], font) for cell in CELLS]
            folder = tempfile.mkdtemp(dir=work)
            for step in range(length):
                canvas = Image.new("RGB", size, BACKGROUND)
                for number, clip in enumerate(clips):
                    x = GAP + (number % COLUMNS) * (CELL[0] + GAP)
                    y = GAP + (number // COLUMNS) * (CELL[1] + GAP)
                    cell = clip[min(len(clip) - 1, step * len(clip) // length)].convert("RGBA")
                    cell.alpha_composite(layers[number])
                    canvas.paste(cell.convert("RGB"), (x, y), mask)
                canvas.save(os.path.join(folder, f"{step:05d}.png"))
            target = os.path.join(docs, "home.webp" if language == "en" else f"home_{language}.webp")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", os.path.join(folder, "%05d.png"),
                            "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "62", "-compression_level", "6", "-loop", "0",
                            target], check=True)
            print(f"{target}: {length} frames ({length / FPS:.1f} s), {os.path.getsize(target) // 1024} KiB")
    finally:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
