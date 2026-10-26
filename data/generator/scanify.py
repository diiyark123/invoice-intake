"""Make a clean PDF look like a scan or phone photo: rotate, add noise, blur, save as JPEG."""

import io
import random

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageFilter

SCAN_DPI = 200  # D4: same DPI the pipeline renders at


def render_first_page(pdf_path: str, dpi: int = SCAN_DPI) -> Image.Image:
    with fitz.open(pdf_path) as doc:
        pix = doc[0].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def scanify(
    pdf_path: str,
    out_path: str,
    rng: random.Random,
    max_rotation: float = 3.0,
    noise_sigma: float = 12.0,
    max_blur: float = 1.2,
) -> None:
    img = render_first_page(pdf_path)

    # Slight paper tint and uneven brightness
    tint = rng.randint(225, 250)
    background = Image.new("RGB", img.size, (tint, tint, tint - rng.randint(0, 12)))
    img = Image.blend(img, background, 0.08)

    angle = rng.uniform(-max_rotation, max_rotation)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(tint, tint, tint))

    arr = np.asarray(img).astype(np.float32)
    np_rng = np.random.default_rng(rng.randint(0, 2**32 - 1))
    arr += np_rng.normal(0, noise_sigma, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, max_blur)))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.randint(60, 85))
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())
