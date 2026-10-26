"""Image cleanup before OCR: grayscale, deskew, denoise, contrast, plus a blur score (D6)."""

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

# D6, tuned on data/dev (M5): at 100 it flagged 4 scans that were read perfectly and caught no
# failure that low confidence missed. Revisit when real phone photos are added.
BLUR_THRESHOLD = 40.0
MAX_DESKEW_DEGREES = 10.0


@dataclass
class Preprocessed:
    gray: np.ndarray  # cleaned image for OCR
    rotated: Image.Image  # RGB page after deskew (bounding boxes refer to this image)
    angle: float
    blur_score: float


def blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian: low means blurry."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def estimate_skew(gray: np.ndarray) -> float:
    """Angle in degrees (counter-clockwise positive, PIL convention) to make text lines level."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Join characters into line-shaped blobs, then take the median angle of long blobs.
    blobs = cv2.dilate(binary, cv2.getStructuringElement(cv2.MORPH_RECT, (30, 3)))
    contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles = []
    for c in contours:
        (_, _), (w, h), a = cv2.minAreaRect(c)
        if w < h:
            w, h, a = h, w, a - 90
        if w > 100 and w > 4 * h:
            angles.append(a)
    if not angles:
        return 0.0
    angle = -float(np.median(angles))
    return angle if abs(angle) <= MAX_DESKEW_DEGREES else 0.0


def preprocess(image: Image.Image) -> Preprocessed:
    gray_raw = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    score = blur_score(gray_raw)
    angle = estimate_skew(gray_raw)
    rotated = image
    if abs(angle) >= 0.3:
        rotated = image.rotate(-angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
    gray = cv2.cvtColor(np.asarray(rotated), cv2.COLOR_RGB2GRAY)
    gray = cv2.medianBlur(gray, 3)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return Preprocessed(gray=gray, rotated=rotated, angle=angle, blur_score=score)
