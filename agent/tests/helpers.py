import io

from PIL import Image


def jpeg_with_exif(taken: str | None = None, lat: float | None = None, lon: float | None = None) -> bytes:
    """Small JPEG with optional DateTimeOriginal ("YYYY:MM:DD HH:MM:SS") and GPS."""
    img = Image.new("RGB", (64, 48), (180, 160, 60))
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
        exif.get_ifd(0x8769)[36881] = "+05:30"
    if lat is not None:
        def dms(v):
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = round(((v - d) * 60 - m) * 60, 2)
            return (d, m, s)
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = ("N" if lat >= 0 else "S"), dms(lat)
        gps[3], gps[4] = ("E" if lon >= 0 else "W"), dms(lon)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()
