import os
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
import threading, logging, random, time, json, socket, datetime
from pathlib import Path
from PIL import Image
from queue import LifoQueue
from portal.server import WebPortal
from detection.cerberus_models import NSFWImageDetector, NSFWTextDetector, TextExtractor
from detection.classifiers import ImageClassifier, TextClassifier
from detection.classifiers import ImageDetectionLevel
from lib.database import query_db, execute_db, db_exists, create_db
import lib.image_compare as ImageCompare
from screen_cap.vnc import VNC, VNCConnectionError
from notification.discord import DiscordWebhook

# Setup logging
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)
logger = logging.getLogger("cerberus.py")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
log_timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
file_logger = logging.FileHandler(f"logs/cerberus_{log_timestamp}.log")
file_logger.setLevel(logging.DEBUG)
file_logger.setFormatter(formatter)
console_logger = logging.StreamHandler()
console_logger.setLevel(logging.DEBUG)
console_logger.setFormatter(formatter)
logger.addHandler(file_logger)
logger.addHandler(console_logger)

CPU_MODE = False
MAX_SEC = 10
MIN_SEC = 1


vnc_ip = "127.0.0.1"
vnc_port = 5900
discord = DiscordWebhook()
backlog = LifoQueue()


def ensure_default_records():
	device_row = query_db(
		"SELECT device_id FROM devices WHERE device_name = ? LIMIT 1",
		("Child PC",),
	)
	if not device_row:
		execute_db(
			"INSERT INTO devices (device_name, device_ip) VALUES (?, ?)",
			("Child PC", vnc_ip),
		)

	settings_row = query_db(
		"SELECT setting_id FROM settings WHERE profile = ? LIMIT 1",
		("Default",),
	)
	if not settings_row:
		execute_db(
			"INSERT INTO settings (profile, backlog_count) VALUES (?, ?)",
			("Default", 0),
		)


def get_device_id(device_name: str = "Child PC", default_ip: str | None = None) -> int:
	device_row = query_db(
		"SELECT device_id FROM devices WHERE device_name = ? LIMIT 1",
		(device_name,),
	)
	if device_row:
		return int(device_row[0]["device_id"])

	execute_db(
		"INSERT INTO devices (device_name, device_ip) VALUES (?, ?)",
		(device_name, default_ip or vnc_ip),
	)
	device_row = query_db(
		"SELECT device_id FROM devices WHERE device_name = ? LIMIT 1",
		(device_name,),
	)
	if not device_row:
		raise RuntimeError(f"Failed to resolve device id for {device_name}")
	return int(device_row[0]["device_id"])


def webserver():
	portal = WebPortal()
	portal.run()

def updated_vnc():
	global vnc_ip
	vnc_info = query_db("SELECT device_ip FROM devices WHERE device_name = ?", ("Child PC",))
	if vnc_info:
		if vnc_info[0]["device_ip"] != vnc_ip:
			vnc_ip = vnc_info[0]["device_ip"]
			return False
	return True

def is_vnc_open(ip, port, timeout=10):
	try:
		with socket.create_connection((ip, port), timeout=timeout):
			return True
	except Exception:
		return False

def vnc_client():
	global backlog
	updated_vnc()
	client = VNC(ip_address=vnc_ip, port=vnc_port)
	prev_img = None
	while True:
		try:
			if updated_vnc():
				client = VNC(ip_address=vnc_ip, port=vnc_port)
				if is_vnc_open(vnc_ip, vnc_port):
					client.connect()
			if client.is_connected():
				img = client.get_screenshot()
				if prev_img:
					if not ImageCompare.is_similar(img, prev_img, threshold=0.02)[0]:
						backlog.put(img)
				prev_img = img
			else:
				if is_vnc_open(vnc_ip, vnc_port):
					client.reconnect()
			
		except VNCConnectionError as e:
			logger.error(f"vnc_client(): {e}")
		time.sleep(random.uniform(MIN_SEC, MAX_SEC))

def send_notification():
	global discord
	url = None
	try:
		url = query_db("SELECT discord_webhook FROM settings WHERE profile = ?", ("Default",))[0]["discord_webhook"]
	except:
		pass
	if url:
		discord.send(url, "Something was found on Child PC")

def create_event(result:dict):
	try:
		project_dir = Path(__file__).resolve().parent
		events_dir = project_dir / "events"
		events_dir.mkdir(exist_ok=True)
		device_id = get_device_id()
		cols = "timestamp,device"
		timestamp = timestamp = result["timestamp"].strftime("%Y%m%d_%H%M%S")
		vals = [result["timestamp"], device_id]
		if "image" in result:
			cols += ",full_image_path"
			filename = f"events/{timestamp}_full.png"
			full_path = events_dir / f"{timestamp}_full.png"
			img:Image.Image = result["image"]
			img.save(full_path)
			vals.append(filename)
		if "results" in result:
			cols += ",report"
			vals.append(json.dumps(result["results"]))
		if "cell" in result:
			cols += ",cell_image_path"
			filename = f"events/{timestamp}_cell.png"
			cell_path = events_dir / f"{timestamp}_cell.png"
			img:Image.Image = result["cell"]
			img.save(cell_path)
			vals.append(filename)
		if "text" in result:
			cols += ",text,event_type"
			vals.append(result["text"])
			vals.append(1)
		else:
			cols += ",event_type"
			vals.append(0)
		val_qs = ", " + ", ".join(["?"] * (len(vals) - 1))
		query = f"INSERT INTO events ({cols}) VALUES (?{val_qs})"
		execute_db(query=query, params=tuple(vals))
		send_notification()
	except Exception:
		logger.exception("detect(): Could not make an event.")

def detect():
	global backlog
	img_det = NSFWImageDetector(cpu_mode=CPU_MODE)
	txt_det = NSFWTextDetector(cpu_mode=CPU_MODE)
	txt_ext = TextExtractor(cpu_mode=CPU_MODE)
	img_clsf = ImageClassifier(img_det)
	txt_clsf = TextClassifier(txt_det, txt_ext)
	
	while True:
		if not backlog.empty():
			img = backlog.get()
			try:
				img_det.load()
				image_result = img_clsf.classify(img)
				if not image_result["passed"]:
					create_event(image_result)
				img_det.unload()

				txt_det.load()
				txt_ext.load()
				text_result = txt_clsf.classify(img)
				if not text_result["passed"]:
					create_event(text_result)
			except Exception:
				logger.exception("detect(): Detection loop failed for an image.")
			finally:
				img_det.unload()
				txt_det.unload()
				txt_ext.unload()
		time.sleep(0.01)


# First time setups.
if not db_exists():
	create_db()
ensure_default_records()
models = [NSFWImageDetector(), NSFWTextDetector(), TextExtractor()]
for m in models:
	if not m.is_model_downloaded():
		m.download_model()

logger.info("Starting Web Portal Thread...")
portal = threading.Thread(target=webserver, daemon=True)
portal.start()
logger.info("Starting VNC Client Thread...")
vnc = threading.Thread(target=vnc_client, daemon=True)
vnc.start()
logger.info("Starting Detection Thread...")
detector = threading.Thread(target=detect, daemon=True)
detector.start()

logger.info("Cerberus is now running")

while True:
	execute_db(
		"UPDATE settings SET backlog_count = ? WHERE profile = ?",
		(backlog.qsize(), "Default")
	)
	time.sleep(1)
