from PIL import Image, ImageChops, ImageStat

def is_similar(
	img1: Image.Image,
	img2: Image.Image,
	size: tuple[int, int] = (64, 36),
	threshold: float = 0.02
) -> tuple[bool, float]:
	if img1.size != img2.size:
		raise ValueError("Images must be the same size")
	
	a = img1.convert("L").resize(size)
	b = img2.convert("L").resize(size)
	
	diff_img = ImageChops.difference(a, b)
	diff = ImageStat.Stat(diff_img).mean[0] / 255.0
	
	return diff < threshold, diff