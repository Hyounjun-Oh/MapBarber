"""Make the 3 x 3 animation of the wiki home from the full animations in docs/.

    python tools/make_mosaic.py docs/        (needs ffmpeg; writes docs/home.webp and docs/home_ko.webp)

Each cell keeps the map view of one animation (not the menus and the side panel), cut to 4:3, with the name of
the feature in its corner. Every animation is played faster or slower so that it lasts exactly DURATION seconds:
all nine start and end together, then start again.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

CELLS = (("voxel.gif", "Voxel editor", "복셀 편집기"), ("cloud.gif", "Point cloud editor", "포인트 클라우드 편집기"),
         ("grid.gif", "2D grid editor", "2D 격자 편집기"), ("conversion.gif", "Conversion", "변환"),
         ("labelling.gif", "Point cloud labelling", "포인트 클라우드 라벨링"), ("smart_pick.gif", "Smart pick", "스마트 선택"),
         ("boxes.gif", "3D boxes", "3D 박스"), ("auto_labelling.webp", "Auto 3D box labelling", "자동 3D 박스 라벨링"),
         ("frames.gif", "Frame sequences", "프레임 시퀀스"))
CELL = (320, 240)
GAP = 4
FPS = 12
DURATION = 15.0
FONTS = {"en": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
         "ko": ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1)}


def to_cell(frame, crop):
    """The map view of a frame: `crop` is (left, top, right, bottom) as shares of the frame, then 4:3 and cell size."""
    width, height = frame.size
    frame = frame.crop((int(crop[0] * width), int(crop[1] * height), int(crop[2] * width), int(crop[3] * height)))
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
            cell = to_cell(image.convert("RGB"), (0, 0, 1, 1 - 45 / image.size[1]))
            frames += [cell] * max(1, int(round(image.info.get("duration", 1000 / FPS) * FPS / 1000)))
        return frames
    folder = tempfile.mkdtemp(dir=work)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"fps={FPS}", os.path.join(folder, "%05d.png")],
                   check=True)
    return [to_cell(Image.open(os.path.join(folder, name)).convert("RGB"), (0, 0.07, 0.63, 0.93))
            for name in sorted(os.listdir(folder))]


def main(docs):
    work = tempfile.mkdtemp(prefix="mosaic_")
    try:
        clips = [read_frames(os.path.join(docs, name), work) for name, _, _ in CELLS]
        length = int(round(DURATION * FPS))
        size = (3 * CELL[0] + 2 * GAP, 3 * CELL[1] + 2 * GAP)
        for language, column in (("en", 1), ("ko", 2)):
            font = ImageFont.truetype(FONTS[language][0], 17, index=FONTS[language][1])
            folder = tempfile.mkdtemp(dir=work)
            for step in range(length):
                canvas = Image.new("RGB", size, (24, 26, 31))
                draw = ImageDraw.Draw(canvas, "RGBA")
                for index, clip in enumerate(clips):
                    x, y = (index % 3) * (CELL[0] + GAP), (index // 3) * (CELL[1] + GAP)
                    canvas.paste(clip[min(len(clip) - 1, step * len(clip) // length)], (x, y))
                    box = draw.textbbox((x + 14, y + 12), CELLS[index][column], font=font)
                    draw.rounded_rectangle((box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5), 4, fill=(15, 17, 22, 215))
                    draw.text((x + 14, y + 12), CELLS[index][column], font=font, fill=(255, 255, 255))
                canvas.save(os.path.join(folder, f"{step:05d}.png"))
            target = os.path.join(docs, "home.webp" if language == "en" else f"home_{language}.webp")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", os.path.join(folder, "%05d.png"),
                            "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "60", "-compression_level", "6", "-loop", "0",
                            target], check=True)
            print(f"{target}: {length} frames ({length / FPS:.1f} s), {os.path.getsize(target) // 1024} KiB")
    finally:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
