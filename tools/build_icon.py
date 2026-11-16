"""Convert the supplied PNG into a multi-resolution Windows icon."""

from pathlib import Path
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage


def main():
    assets = Path(__file__).resolve().parents[1] / "memcard" / "assets"
    source = QImage(str(assets / "MemCardLogo.png"))
    if source.isNull():
        raise RuntimeError("Cannot read memcard/assets/MemCardLogo.png")
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode {size}px icon")
        frames.append((size, bytes(data)))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, data in frames:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    target = assets / "MemCard.ico"
    target.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries) + b"".join(data for _, data in frames))
    print(f"Created {target}")


if __name__ == "__main__":
    main()
