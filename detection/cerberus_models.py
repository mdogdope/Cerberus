from transformers import AutoImageProcessor, AutoModelForImageClassification
import torch, gc
from typing import Optional
from PIL import Image
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError

class NSFWImageDetector:
	"""Detect non‑safe‑for‑work content in images.

	The detector is a lightweight wrapper around the Hugging Face
	``Freepik/nsfw_image_detector`` model.  It lazily loads the model and
	processor on first use, allowing callers to control when heavy resources
	are downloaded or moved to GPU.
	"""
	MODEL_ID: str = "Freepik/nsfw_image_detector"
	def __init__(self, cache_dir: str = "./models/hf"):
		"""Create an uninitialised detector.
	
		The :pyattr:`processor`, :pyattr:`model` and :pyattr:`device`
		attributes are set to ``None`` until :meth:`load` is called.  This
		keeps the initial import lightweight and defers GPU allocation
		until required.
		"""
		self.processor = None
		self.model = None
		self.device = None
		self.cache_dir = cache_dir
		pass

	def load(self):
		"""Load the Hugging Face model and processor.
	
		The method downloads (or loads from cache) the ``Freepik/nsfw_image_detector``
		model and its associated image processor.  The model is moved to the
		appropriate device and set to evaluation mode.  It returns ``self`` so
		calls can be chained.
	
		Returns
		-------
		NSFWImageDetector
			The instance with loaded resources.
		"""
		self.processor = AutoImageProcessor.from_pretrained(
			NSFWImageDetector.MODEL_ID,
			cache_dir=self.cache_dir",
			local_files_only=True
		)
		
		self.model = AutoModelForImageClassification.from_pretrained(
			NSFWImageDetector.MODEL_ID,
			cache_dir=self.cache_dir",
			local_files_only=True
		)
		
		self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
		self.model.to(self.device)
		self.model.eval()
		return self
	
	def classify(self, image: Image.Image, top_k: Optional[int] = None, sort: bool = False, empty_cuda_cache: bool = False):
		"""Classify an image for NSFW content.
	
		Parameters
		----------
		image : PIL.Image.Image
			The input image to classify.
		top_k : Optional[int]
			If provided, return only the top *k* predictions.  Must be in
			``1..num_labels``; otherwise a :class:`ValueError` is raised.
		sort : bool
			When ``True`` results are reordered to match the label priority
			order ``["high", "medium", "low", "neutral"]``.  The default keeps
			the natural descending‑score order.
		empty_cuda_cache : bool
			If ``True`` and CUDA is available, clears the GPU cache after
			inference to free memory.
	
		Returns
		-------
		List[Dict[str, float]]
			A list of dictionaries each containing ``label`` and ``score``.
	
		Raises
		------
		RuntimeError
			If :meth:`load` has not been called.
		ValueError
			If ``top_k`` is out of bounds.
		"""
		if self.model is None or self.processor is None or self.device is None:
			raise RuntimeError("Call load() before classify().")
		
		inputs = None
		outputs = None
		logits_cpu = None
		probs = None
		indices = None
		
		try:
			inputs = self.processor(images=image, return_tensors="pt")
			inputs = {k: v.to(self.device, non_blocking=True) for k, v in inputs.items()}
			
			with torch.no_grad():
				outputs = self.model(**inputs)
			
			logits_cpu = outputs.logits[0].detach().float().cpu()
			
			probs = torch.softmax(logits_cpu, dim=-1)
			id2label = self.model.config.id2label
			
			num_labels = probs.numel()
			if top_k is not None and (top_k <= 0 or top_k > num_labels):
				raise ValueError(f"top_k must be in 1..{num_labels}, got {top_k}")
			
			if top_k is None:
				indices = torch.argsort(probs, descending=True)
			else:
				indices = torch.topk(probs, k=top_k).indices
			
			results = [
				{"label": id2label[int(i)], "score": float(probs[int(i)].item())}
				for i in indices
			]
			
			if not sort:
				return results
			
			label_order = ["high", "medium", "low", "neutral"]
			result_by_label = {r["label"]: r for r in results}
			ordered_results = [
				result_by_label[label]
				for label in label_order
				if label in result_by_label
			]
			return ordered_results
		
		finally:
			if inputs is not None:
				for k in list(inputs.keys()):
					inputs[k] = None
			inputs = None
			outputs = None
			logits_cpu = None
			probs = None
			indices = None
			
			if empty_cuda_cache and torch.cuda.is_available():
				torch.cuda.empty_cache()
	
	def unload(self):
		"""Unload the model and free resources.
	
		The method clears references to the processor, model and device and
		invokes Python's garbage collector.  If CUDA is available it also
		empties the GPU cache and performs IPC collection to ensure that no
		memory remains allocated.
		"""
		if self.model is None and self.processor is None:
			return
		
		self.model = None
		self.processor = None
		self.device = None
		
		gc.collect()
		
		if torch.cuda.is_available():
			torch.cuda.empty_cache()
			torch.cuda.ipc_collect()
	
	def is_model_downloaded(self) -> bool:
		"""
		Check if the model files are present in the cache directory.
		
		Returns
		-------
		bool
			``True`` when the ``./models/hf`` directory exists and contains at least one file, otherwise ``False``.
		"""
		try:
			snapshot_download(
				repo_id=NSFWImageDetector.MODEL_ID,
				revision=None,
				cache_dir=self.cache_dir,
				local_files_only=True
			)
			return True
		except LocalEntryNotFoundError:
			return False
	
	def download_model(self) -> None:
		snapshot_download(
			repo_id=NSFWImageDetector.MODEL_ID,
			revision=None,
			cache_dir=self.cache_dir
		)

