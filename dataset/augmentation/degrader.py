"""DocumentDegrader: bbox-preserving realistic degradation. All probs from config."""
from __future__ import annotations
import random, io
import numpy as np
import cv2
from PIL import Image

class DocumentDegrader:
    def __init__(self, cfg: dict | None = None, seed: int = 0):
        d = cfg or {}
        self.cfg = {
            "rotation_max": d.get("rotation_max", 5),
            "perspective_p": d.get("perspective_p", 0.35),
            "blur_p": d.get("blur_p", 0.25),
            "noise_p": d.get("noise_p", 0.30),
            "jpeg_p": d.get("jpeg_p", 0.30),
            "lighting_p": d.get("lighting_p", 0.25),
            "target_dpi": d.get("target_dpi", None),
        }
        self.rng = random.Random(seed)
        self.applied: dict = {}

    def _rot(self, img, boxes):
        r = self.rng.random()
        # 80% ±0-2, 15% ±2-4, 5% ±4-7
        u = self.rng.random()
        mx = 2 if u < 0.8 else 4 if u < 0.95 else min(7, self.cfg["rotation_max"])
        ang = self.rng.uniform(-mx, mx)
        if abs(ang) < 0.2:
            return img, boxes
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        out = cv2.warpAffine(img, M, (w, h), borderValue=(255, 255, 255))
        nb = []
        for x1, y1, x2, y2 in boxes:
            t = (M @ np.array([[x1, y1, 1], [x2, y1, 1], [x2, y2, 1], [x1, y2, 1]]).T).T
            nb.append([int(t[:, 0].min()), int(t[:, 1].min()), int(t[:, 0].max()), int(t[:, 1].max())])
        nb = [[max(0, a), max(0, b), min(w, c), min(h, d_)] for a, b, c, d_ in nb]
        self.applied["rotation"] = round(ang, 2)
        return out, nb

    def _persp(self, img, boxes):
        if self.rng.random() > self.cfg["perspective_p"]:
            return img, boxes
        h, w = img.shape[:2]
        s = 0.03
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = src + np.float32([[self.rng.uniform(-s, s) * w, self.rng.uniform(-s, s) * h] for _ in range(4)])
        M = cv2.getPerspectiveTransform(src, dst)
        out = cv2.warpPerspective(img, M, (w, h), borderValue=(255, 255, 255))
        nb = []
        for x1, y1, x2, y2 in boxes:
            pts = np.float32([[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]])
            t = cv2.perspectiveTransform(pts, M)[:, 0, :]
            nb.append([int(t[:, 0].min()), int(t[:, 1].min()), int(t[:, 0].max()), int(t[:, 1].max())])
        nb = [[max(0, a), max(0, b), min(w, c), min(h, d_)] for a, b, c, d_ in nb]
        self.applied["perspective"] = True
        return out, nb

    def _blur(self, img):
        if self.rng.random() > self.cfg["blur_p"]:
            return img
        k = self.rng.choice([3, 3, 5])
        self.applied["blur"] = k
        return cv2.GaussianBlur(img, (k, k), 0)

    def _noise(self, img):
        if self.rng.random() > self.cfg["noise_p"]:
            return img
        amp = self.rng.uniform(3, 12)
        n = np.random.default_rng(self.rng.randint(0, 999999)).normal(0, amp, img.shape)
        self.applied["noise"] = round(amp, 1)
        return np.clip(img.astype(float) + n, 0, 255).astype(np.uint8)

    def _light(self, img):
        if self.rng.random() > self.cfg["lighting_p"]:
            return img
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        cx, cy = self.rng.uniform(0.3, 0.7) * w, self.rng.uniform(0.3, 0.7) * h
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(h, w)
        gain = 1.0 - 0.25 * dist * self.rng.uniform(0.5, 1.0)
        self.applied["lighting"] = True
        return np.clip(img.astype(float) * gain[:, :, None], 0, 255).astype(np.uint8)

    def _jpeg(self, img):
        if self.rng.random() > self.cfg["jpeg_p"]:
            return img
        q = self.rng.randint(50, 95)
        self.applied["jpeg_quality"] = q
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img

    def __call__(self, img_bgr, boxes):
        self.applied = {}
        img, boxes = self._rot(img_bgr, boxes)
        img, boxes = self._persp(img, boxes)
        img = self._blur(img)
        img = self._noise(img)
        img = self._light(img)
        img = self._jpeg(img)
        if self.cfg.get("target_dpi"):
            h, w = img.shape[:2]
            s = self.cfg["target_dpi"] / 300
            if s < 1.0:
                img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
                boxes = [[int(a * s), int(b * s), int(c * s), int(d_ * s)] for a, b, c, d_ in boxes]
                img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)
            self.applied["dpi"] = self.cfg["target_dpi"]
        return img, boxes, dict(self.applied)
