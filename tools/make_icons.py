"""Draws the LINGUA app icon (used during the build)."""
import os
from PIL import Image, ImageDraw, ImageFont

os.makedirs("assets", exist_ok=True)
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
px = grad.load()
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S)
        px[x, y] = (int(91 + (34 - 91) * t), int(140 + (195 - 140) * t), int(255 + (166 - 255) * t), 255)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
try:
    font = ImageFont.load_default(size=560)
except TypeError:
    font = ImageFont.load_default()
d.text((S / 2, S / 2 - 20), "L", font=font, fill="white", anchor="mm")
# speech bubble tail
d.polygon([(700, 800), (860, 930), (820, 760)], fill=(255, 255, 255, 230))
img.save("assets/lingua.png")
img.save("assets/lingua.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save("assets/lingua.icns")
print("icons written")
