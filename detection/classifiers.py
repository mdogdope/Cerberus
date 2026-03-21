from .cerberus_models import NSFWImageDetector, NSFWTextDetector, TextExtractor
from PIL import Image
from enum import Enum
import time, datetime

class ImageDetectionLevel(str, Enum):
	NEUTRAL = "neutral"
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
IDL = ImageDetectionLevel

class ImageClassifier:
	def __init__(
			self, image_det: NSFWImageDetector,
			detection_level: ImageDetectionLevel = IDL.NEUTRAL,
			thresholds: dict[ImageDetectionLevel, float] = {IDL.NEUTRAL:0.0,IDL.LOW:0.0,IDL.MEDIUM:0.0,IDL.HIGH:0.0},
			cell_count: int = 6):
	
		self.image_clf = image_det
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
		ret: dict = {"passed": True, "timestamp": datetime.datetime.now()}
		try:
			# Run full image
			results = self.image_clf.classify(image=image)
			ret["results"] = results
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
					cells.append({"i": i, "j": j, "cell": cell})
					results = self.image_clf.classify(image=cell)
					if has_bad(results):
						ret["passed"] = False
						ret["results"] = results
						ret["cell"] = cell
						break
			
			end_time = time.time()
			ret["cells"] = cells
			ret["duration"] = end_time - start_time
			return ret
		except RuntimeError as e:
			raise RuntimeError(f"Image detection failed.") from e
	
	def setThreshold(self, threshold: dict[ImageDetectionLevel, float]):
		self.thresholds = threshold
	
	def setDetectionLevel(self, detection_level: ImageDetectionLevel):
		self.detection_level = detection_level


class TextClassifier:
	def __init__(
				self, text_det: NSFWTextDetector, text_extractor: TextExtractor,
				detection_level: ImageDetectionLevel = IDL.NEUTRAL,
				thresholds: dict[ImageDetectionLevel, float] = {IDL.NEUTRAL:0.5,IDL.LOW:0.6,IDL.MEDIUM:0.7,IDL.HIGH:0.8},
				cell_count: int = 6):

		self.text_clf = text_det
		self.text_extractor = text_extractor
		self.detection_level = detection_level
		self.thresholds = thresholds
		self.cell_count = cell_count

	def classify(self, image: Image.Image) -> dict:
		def has_bad(scores: list) -> bool:
			nsfw_scr = 0.0
			for score in scores:
				if str(score["label"]).strip().upper() == "NSFW":
					nsfw_scr = float(score["score"])
					break
			return nsfw_scr >= self.thresholds.get(self.detection_level, 0.5)

		if image.mode != "RGB":
			image = image.convert("RGB")

		start_time = time.time()
		ret: dict = {"passed": True, "timestamp": datetime.datetime.now()}
		try:
			text = self.text_extractor.extract(image=image)
			results = self.text_clf.classify(text=text)
			ret["results"] = results
			ret["image"] = image
			ret["text"] = text
			if has_bad(results):
				ret["passed"] = False
				ret["trigger_text"] = text

			end_time = time.time()
			ret["duration"] = end_time - start_time
			return ret
		except RuntimeError as e:
			raise RuntimeError(f"Text detection failed.") from e

	def setThreshold(self, threshold: dict[ImageDetectionLevel, float]):
		self.thresholds = threshold

	def setDetectionLevel(self, detection_level: ImageDetectionLevel):
		self.detection_level = detection_level
