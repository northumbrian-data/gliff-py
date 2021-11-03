import base64
from io import BytesIO
from PIL import Image


def base64_to_pil_image(img_base64):
    """Convert a base64-encoded image into a PIL Image object"""

    img_bytes = base64.b64decode(img_base64)
    img_file = BytesIO(img_bytes)
    return Image.open(img_file).convert("RGB")


def pil_to_base64_image(img_pil, is_thumbnail=False):
    """Convert a PIL Image object to a base64-encoded image (in bytes)"""

    img_file = BytesIO()
    img_pil.save(img_file, format="PNG")
    img_bytes = img_file.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode()
    if is_thumbnail:
        img_base64 = "data:image/png;base64,{}".format(img_base64)
    return img_base64


def get_thumbnail_from_pil_image(img_pil):
    """Get base64-encoded thumbnail (in bytes) from PIL image"""

    size = 128, 128
    img_pil.thumbnail(size, Image.ANTIALIAS)
    return pil_to_base64_image(img_pil, True)
