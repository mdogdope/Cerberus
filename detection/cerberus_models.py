import os
from transformers import AutoImageProcessor, AutoModelForImageClassification, AutoModelForImageTextToText, AutoProcessor, AutoTokenizer, AutoModelForSequenceClassification
import torch, gc
from typing import Optional, Any
from PIL import Image
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
import re

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_CPU_MODE_SETTINGS_APPLIED = False


def _apply_cpu_mode_settings() -> None:
	global _CPU_MODE_SETTINGS_APPLIED

	if _CPU_MODE_SETTINGS_APPLIED:
		return

	try:
		torch.set_num_threads(4)
		torch.set_num_interop_threads(2)
	except RuntimeError:
		if torch.get_num_threads() != 4 or torch.get_num_interop_threads() != 2:
			raise

	_CPU_MODE_SETTINGS_APPLIED = True

class NSFWImageDetector:
	"""Detect non‑safe‑for‑work content in images.

	The detector is a lightweight wrapper around the Hugging Face
	``Freepik/nsfw_image_detector`` model.  It lazily loads the model and
	processor on first use, allowing callers to control when heavy resources
	are downloaded or moved to GPU.
	"""
	MODEL_ID: str = "Freepik/nsfw_image_detector"
	def __init__(self, cache_dir: str = "./models/hf", cpu_mode: bool = False):
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
		self.cpu_mode = cpu_mode

		if self.cpu_mode:
			_apply_cpu_mode_settings()

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
			cache_dir=self.cache_dir,
			local_files_only=True
		)
		
		self.model = AutoModelForImageClassification.from_pretrained(
			NSFWImageDetector.MODEL_ID,
			cache_dir=self.cache_dir,
			local_files_only=True
		)
		
		self.device = torch.device("cpu" if self.cpu_mode else ("cuda:0" if torch.cuda.is_available() else "cpu"))
		self.model.to(self.device)
		self.model.eval()
		return self
	
	def unload(self) -> None:
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
	
	def is_loaded(self) -> bool:
		"""
		Returns whether the underlying model has been initialized.

		This method simply checks if the internal `model` reference
		has been populated. It does not verify device placement,
		weights validity, or runtime readiness.

		Returns:
			bool: True if a model instance is present, otherwise False.
		"""
		return self.model is not None
	
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
	
	def classify(self, image: Image.Image, top_k: Optional[int] = None, sort: bool = False, empty_cuda_cache: bool = False) -> list[dict[str, Any]]:
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


class NSFWTextDetector:
	"""Detect NSFW or SFW content in text."""
	MODEL_ID: str = "eliasalbouzidi/distilbert-nsfw-text-classifier"

	def __init__(self, cache_dir: str = "./models/hf", cpu_mode: bool = False):
		self.tokenizer = None
		self.model = None
		self.device = None
		self.cache_dir = cache_dir
		self.cpu_mode = cpu_mode

		if self.cpu_mode:
			_apply_cpu_mode_settings()

	def load(self):
		self.tokenizer = AutoTokenizer.from_pretrained(
			NSFWTextDetector.MODEL_ID,
			cache_dir=self.cache_dir,
			local_files_only=True
		)

		self.model = AutoModelForSequenceClassification.from_pretrained(
			NSFWTextDetector.MODEL_ID,
			cache_dir=self.cache_dir,
			local_files_only=True
		)

		self.device = torch.device("cpu" if self.cpu_mode else ("cuda:0" if torch.cuda.is_available() else "cpu"))
		self.model.to(self.device)
		self.model.eval()
		return self

	def unload(self) -> None:
		if self.model is None and self.tokenizer is None:
			return

		self.model = None
		self.tokenizer = None
		self.device = None

		gc.collect()

		if torch.cuda.is_available():
			torch.cuda.empty_cache()
			torch.cuda.ipc_collect()

	def is_loaded(self) -> bool:
		return self.model is not None and self.tokenizer is not None and self.device is not None

	def is_model_downloaded(self) -> bool:
		try:
			snapshot_download(
				repo_id=NSFWTextDetector.MODEL_ID,
				cache_dir=self.cache_dir,
				local_files_only=True
			)
			return True
		except LocalEntryNotFoundError:
			return False

	def download_model(self) -> None:
		snapshot_download(
			repo_id=NSFWTextDetector.MODEL_ID,
			cache_dir=self.cache_dir
		)

	def classify(self, text: str, top_k: Optional[int] = None, empty_cuda_cache: bool = False) -> list[dict[str, Any]]:
		if self.model is None or self.tokenizer is None or self.device is None:
			raise RuntimeError("Call load() before classify().")

		inputs = None
		outputs = None
		logits_cpu = None
		probs = None
		indices = None

		try:
			inputs = self.tokenizer(text, return_tensors="pt", truncation=True)
			inputs = {k: v.to(self.device, non_blocking=True) for k, v in inputs.items()}

			with torch.no_grad():
				outputs = self.model(**inputs)

			logits_cpu = outputs.logits[0].detach().float().cpu()
			probs = torch.softmax(logits_cpu, dim=-1)
			id2label = self.model.config.id2label

			def normalize_label(index: int) -> str:
				raw_label = id2label.get(index, id2label.get(str(index), f"LABEL_{index}"))
				label = str(raw_label).strip().upper()
				if label in {"SAFE FOR WORK", "SFW", "SAFE"}:
					return "SFW"
				if label in {"NOT SAFE FOR WORK", "NSFW"}:
					return "NSFW"
				return label

			num_labels = probs.numel()
			if top_k is not None and (top_k <= 0 or top_k > num_labels):
				raise ValueError(f"top_k must be in 1..{num_labels}, got {top_k}")

			if top_k is None:
				indices = torch.argsort(probs, descending=True)
			else:
				indices = torch.topk(probs, k=top_k).indices

			return [
				{"label": normalize_label(int(i)), "score": float(probs[int(i)].item())}
				for i in indices
			]
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


class TextExtractor:
	"""Extract text from images with GLM-OCR."""
	MODEL_ID: str = "OpenGVLab/InternVL3-1B-hf"

	def __init__(self, cache_dir: str = "./models/hf", cpu_mode: bool = False):
		self.processor = None
		self.tokenizer = None
		self.model = None
		self.device = None
		self.cache_dir = cache_dir
		self.cpu_mode = cpu_mode

		if self.cpu_mode:
			_apply_cpu_mode_settings()

	def _normalize_text(self, text: str) -> str:
		"""Return OCR text in a classifier-friendly form."""
		text = text.replace("\u00a0", " ")
		text = text.replace("\r\n", "\n").replace("\r", "\n")
		text = re.sub(r"[ \t]+", " ", text)
		text = re.sub(r"\n{3,}", "\n\n", text)
		return text.strip()

	def load(self):
		self.processor = AutoProcessor.from_pretrained(
			TextExtractor.MODEL_ID,
			cache_dir=self.cache_dir,
			local_files_only=True
		)

		self.tokenizer = AutoTokenizer.from_pretrained(
			TextExtractor.MODEL_ID,
			cache_dir=self.cache_dir,
			local_files_only=True
		)

		self.model = AutoModelForImageTextToText.from_pretrained(
			TextExtractor.MODEL_ID,
			cache_dir=self.cache_dir,
			local_files_only=True
		)

		self.device = torch.device("cpu" if self.cpu_mode else ("cuda:0" if torch.cuda.is_available() else "cpu"))
		self.model.to(self.device) # type: ignore
		self.model.eval()
		return self

	def unload(self) -> None:
		if self.model is None and self.processor is None and self.tokenizer is None:
			return

		self.processor = None
		self.tokenizer = None
		self.model = None
		self.device = None

		gc.collect()

		if torch.cuda.is_available():
			torch.cuda.empty_cache()
			torch.cuda.ipc_collect()

	def is_loaded(self) -> bool:
		return self.model is not None and self.processor is not None and self.tokenizer is not None and self.device is not None

	def is_model_downloaded(self) -> bool:
		try:
			snapshot_download(
				repo_id=TextExtractor.MODEL_ID,
				cache_dir=self.cache_dir,
				local_files_only=True
			)
			return True
		except LocalEntryNotFoundError:
			return False

	def download_model(self) -> None:
		snapshot_download(
			repo_id=TextExtractor.MODEL_ID,
			cache_dir=self.cache_dir
		)

	def extract(self, image: Image.Image, prompt: str = "Text Recognition:", max_new_tokens: int = 512, empty_cuda_cache: bool = False) -> str:
		if self.model is None or self.processor is None or self.tokenizer is None or self.device is None:
			raise RuntimeError("Call load() before extract().")

		inputs = None
		output_ids = None
		output_text = None

		try:
			if image.mode != "RGB":
				image = image.convert("RGB")

			messages = [
				{
					"role": "user",
					"content": [
						{"type": "image", "image": image},
						{"type": "text", "text": prompt},
					],
				}
			]

			inputs = self.processor.apply_chat_template(
				messages,
				tokenize=True,
				add_generation_prompt=True,
				return_dict=True,
				return_tensors="pt",
			)
			inputs = inputs.to(self.device)
			if "token_type_ids" in inputs:
				inputs.pop("token_type_ids")

			pad_token_id = self.tokenizer.eos_token_id
			if pad_token_id is None:
				pad_token_id = self.model.config.eos_token_id

			with torch.no_grad():
				if pad_token_id is not None:
					output_ids = self.model.generate(
						**inputs,
						max_new_tokens=max_new_tokens,
						pad_token_id=pad_token_id,
					)
				else:
					output_ids = self.model.generate(
						**inputs,
						max_new_tokens=max_new_tokens,
					)

			input_len = inputs["input_ids"].shape[1]
			output_text = self.processor.decode(output_ids[0][input_len:], skip_special_tokens=True)
			return self._normalize_text(output_text)
		finally:
			inputs = None
			output_ids = None
			output_text = None

			if empty_cuda_cache and torch.cuda.is_available():
				torch.cuda.empty_cache()
	
	
