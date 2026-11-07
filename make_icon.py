"""Generate the app icon (multi-size .ico) matching the app's blue->green mark."""
from PIL import Image, ImageDraw, ImageFont
import math

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# rounded-square gradient background (blue -> green, like the in-app logo)
radius = int(S * 0.22)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=255)

grad = Image.new("RGB", (S, S))
gd = ImageDraw.Draw(grad)
c1 = (57, 135, 229)    # #3987e5
c2 = (25, 158, 112)    # #199e70
for i in range(S):
    t = i / (S - 1)
    gd.line([(0, i), (S, i)], fill=(
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    ))
img.paste(grad, (0, 0), mask)

# subtle inner sheen
sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
sd = ImageDraw.Draw(sheen)
sd.rounded_rectangle([int(S*0.06), int(S*0.06), int(S*0.94), int(S*0.5)],
                     radius=int(S*0.17), fill=(255, 255, 255, 26))
img = Image.alpha_composite(img, sheen)
d = ImageDraw.Draw(img)

# white "P"
font = None
for path in [
    r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf",
]:
    try:
        font = ImageFont.truetype(path, int(S * 0.62))
        break
    except Exception:
        continue

text = "P"
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((S - tw) / 2 - bbox[0], (S - th) / 2 - bbox[1] - int(S*0.02)),
       text, font=font, fill=(255, 255, 255, 255))

# small rotation arc under the P
arc_box = [int(S*0.30), int(S*0.66), int(S*0.70), int(S*0.86)]
d.arc(arc_box, start=200, end=340, fill=(255, 255, 255, 230), width=int(S*0.035))
# arrow head
ax, ay = int(S*0.665), int(S*0.715)
d.polygon([(ax, ay - int(S*0.032)), (ax + int(S*0.045), ay + int(S*0.004)),
           (ax, ay + int(S*0.032))], fill=(255, 255, 255, 230))

sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img.save(r"C:\Users\josmo\proxy-rotator\proxyrotator.ico", format="ICO", sizes=sizes)
img.resize((256, 256), Image.LANCZOS).save(r"C:\Users\josmo\proxy-rotator\proxyrotator.png")
print("icon written")
