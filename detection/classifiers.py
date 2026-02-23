from .cerberus_models import NSFWImageDetector
from PIL import Image
from enum import Enum
import time

class ImageDetectionLevel(str, Enum):
	NEUTRAL = "neutral"
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
IDL = ImageDetectionLevel

class ImageClassifier:
	def __init__(
			self, image_clf: NSFWImageDetector,
			detection_level: ImageDetectionLevel = IDL.NEUTRAL,
			thresholds: dict[ImageDetectionLevel, float] = {IDL.NEUTRAL:0.0,IDL.LOW:0.0,IDL.MEDIUM:0.0,IDL.HIGH:0.0},
			cell_count: int = 6):
	
		self.image_clf = image_clf
		self.detection_level = detection_level
		self.thresholds = thresholds
		self.cell_count = cell_count
	
	def classify(self, image: Image.Image) -> dict:	
		def has_bad(scores: list) -> bool:
			strengths = {"neutral": 0, "low": 1, "medium": 2, "high": 3}
			high_lbl, high_scr = "neutral", 0.0
			for score in scores:
				if score["score"] > high_scr:
					high_lbl = score["label"]
					high_scr = score["score"]
			if strengths.get(high_lbl, 0) > strengths[self.detection_level]:
				return True
			return False
		
		if image.mode != "RGB":
			image = image.convert("RGB")
		
		start_time = time.time()
		ret: dict = {"passed": True}
		try:
			# Run full image
			results = self.image_clf.classify(image=image)
			ret["scores"] = results
			ret["image"] = image
			if has_bad(results):
				ret["passed"] = False
			
			
			# Run Image cells
			nx = self.cell_count
			ny = self.cell_count
			w, h = image.size
			o = 0.5
			
			if w/h >= (2*16)/9:
				nx *= int(w // 1920)
			
			if h/w >= (2*9)/16:
				ny *= int(h // 1080)
			
			cx = w / nx
			cy = h / ny
			
			bw = cx * (1 + o)
			bh = cy * (1 + o)
			
			bw = min(bw, w)
			bh = min(bh, h)
			
			if nx <= 1:
				x_positions = [(w - bw) / 2]
			else:
				step_x = (w - bw) / (nx - 1)
				x_positions = [i * step_x for i in range(nx)]
			
			if ny <= 1:
				y_positions = [(h - bh) / 2]
			else:
				step_y = (h - bh) / (ny - 1)
				y_positions = [j * step_y for j in range(ny)]
			
			cells = []
			for j in range(ny):
				y1 = y_positions[j]
				y2 = y1 + bh
				if not ret["passed"]:
					break
				for i in range(nx):
					x1 = x_positions[i]
					x2 = x1 + bw
					
					cell = image.crop((x1, y1, x2, y2))
					cells.append({"i": i, "j": j, "cell": cell}) #testing
					results = self.image_clf.classify(image=cell)
					if has_bad(results):
						ret = {"passed": False, "scores": results, "cell": cell}
						break
			
			end_time = time.time()
			ret["cells"] = cells
			ret["duration"] = end_time - start_time
			return ret
		except RuntimeError as e:
			raise RuntimeError(f"Image detection failed.") from e
	
	def setThreshold(self, threshold: dict[ImageDetectionLevel, float]):
		self.threshold = threshold
	
	def setDetectionLevel(self, detection_level: ImageDetectionLevel):
		self.detection_level = detection_level

