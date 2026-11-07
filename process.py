import cv2
import numpy as np
from PIL import Image

SRC = '640.gif'
OUT = '640_clean_blue.gif'
REF = 30
N = 60

frames = []
for i in range(N):
    im = Image.open(SRC)
    im.seek(i)
    frames.append(np.array(im.convert('RGBA')))

ref = frames[REF]
ref_gray = cv2.cvtColor(ref[..., :3], cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0

mask = (ref[..., 3] > 10).astype(np.uint8) * 255
mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
exclude = np.zeros((450, 450), np.uint8)
cv2.ellipse(exclude, (225, 198), (108, 64), 0, 0, 360, 255, -1)
exclude[270:390, 150:330] = 255
mask[exclude > 0] = 0

warps = []
aligned = []
for i in range(N):
    gray = cv2.cvtColor(frames[i][..., :3], cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    warp = np.eye(2, 3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 400, 1e-7)
    cc, warp = cv2.findTransformECC(ref_gray, gray, warp, cv2.MOTION_EUCLIDEAN, crit, mask, 5)
    warps.append(warp)
    aligned.append(cv2.warpAffine(frames[i], warp, (450, 450), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)))

stack = np.stack(aligned).astype(np.float32)
alpha = stack[..., 3:4] / 255.0
med_premult = np.median(stack[..., :3] * alpha, axis=0)
med_alpha = np.median(alpha, axis=0)
median_canon = np.dstack([np.clip(med_premult / np.maximum(med_alpha, 1e-6), 0, 255),
                          med_alpha[..., 0] * 255]).astype(np.uint8)
median_canon[median_canon[..., 3] < 40, :3] = 0

# Per-pixel pick the frame least whitened by the canvas-fixed watermark.
blue = stack[..., 2].copy()
blue[stack[..., 3] < 250] = 255
pick = np.argmin(blue, axis=0)
minb_canon = np.take_along_axis(stack, pick[None, :, :, None], axis=0)[0].astype(np.uint8)
minb_canon[minb_canon[..., 3] < 40, :3] = 0

# Head from temporal median (stable), body from per-pixel clean pick.
yy = np.arange(450, dtype=np.float32)[:, None, None]
blend = np.clip((yy - 236.0) / 22.0, 0, 1)
canon_f = median_canon.astype(np.float32) * (1 - blend) + minb_canon.astype(np.float32) * blend
canon = canon_f.astype(np.uint8)

# Recolor the yellow hat + bow to blue.
rgb = canon[..., :3].astype(np.float32) / 255.0
hsv = cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
H, S, V = hsv[..., 0], hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
yy2 = np.arange(450)[:, None]
spatial = np.clip((142 - yy2) / 14.0, 0, 1)
hue_w = np.clip((H - 14) / 6.0, 0, 1) * np.clip((52 - H) / 8.0, 0, 1)
sat_w = np.clip((S - 0.04) / 0.13, 0, 1)
w = hue_w * sat_w * spatial
hsv2 = hsv.copy()
hsv2[..., 0] = np.mod(103 + (H - 31) * 0.45, 180)
hsv2[..., 1] = np.clip(S * 0.82, 0, 1) * 255
blue_rgb = cv2.cvtColor(hsv2.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32) / 255.0
canon[..., :3] = (np.clip(rgb * (1 - w[..., None]) + blue_rgb * w[..., None], 0, 1) * 255).astype(np.uint8)
canon[..., :3] = cv2.medianBlur(canon[..., :3], 3)

# Keep each frame's own blinking / mouth.
face = np.zeros((450, 450), np.uint8)
cv2.ellipse(face, (225, 199), (106, 63), 0, 0, 360, 255, -1)
face = cv2.GaussianBlur(face, (0, 0), 7).astype(np.float32) / 255.0

out_frames = []
for i, warp in enumerate(warps):
    canon_i = cv2.warpAffine(canon, warp, (450, 450), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    m = cv2.warpAffine(face, warp, (450, 450), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=0)[..., None]
    orig = frames[i].astype(np.float32)
    ci = canon_i.astype(np.float32)
    out = np.dstack([orig[..., :3] * m + ci[..., :3] * (1 - m),
                     orig[..., 3:4] * m + ci[..., 3:4] * (1 - m)]).astype(np.uint8)
    out_frames.append(out)
    if i in (0, 15, 30, 45, 59):
        Image.fromarray(out, 'RGBA').save(f'preview_{i:02d}.png')

Image.fromarray(canon, 'RGBA').save('canonical_clean_blue.png')

samples = []
for f in out_frames:
    px = f[f[..., 3] > 127][:, :3]
    samples.append(px[::6])
samples = np.concatenate(samples, axis=0)
tongue = np.array([[238, 153, 153]] * 3000 + [[238, 170, 154]] * 1500, dtype=np.uint8)
samples = np.concatenate([samples, tongue], axis=0)
pal_img = Image.fromarray(samples.reshape(-1, 1, 3), 'RGB').quantize(colors=255, method=Image.Quantize.MEDIANCUT)
full_pal = [0, 0, 0] + pal_img.getpalette()[:255 * 3]

encoded = []
for f in out_frames:
    p = Image.fromarray(f[..., :3], 'RGB').quantize(palette=pal_img, dither=Image.Dither.NONE)
    idx = np.array(p).astype(np.uint16) + 1
    idx[f[..., 3] <= 127] = 0
    pi = Image.fromarray(idx.astype(np.uint8), 'P')
    pi.putpalette(full_pal)
    encoded.append(pi)

encoded[0].save(OUT, save_all=True, append_images=encoded[1:], duration=40, loop=0,
                transparency=0, disposal=2, optimize=True)
print('saved', OUT)
