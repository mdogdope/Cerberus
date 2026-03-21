import threading, logging, random, time, datetime, json
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

logging.basicConfig(
	filename="cerberus.log",
	level=logging.DEBUG,
	format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)



CPU_MODE = False



vnc_ip = "127.0.0.1"
vnc_port = 5900
discord = DiscordWebhook()
backlog = LifoQueue()


def webserver():
	portal = WebPortal()
	portal.run()

def check_vnc():
	global vnc_ip
	vnc_info = query_db("SELECT device_ip FROM devices WHERE device_name = ?", ("Child PC",))
	if vnc_info:
		if vnc_info[0]["device_ip"] != vnc_ip:
			vnc_ip = vnc_info[0]["device_ip"]
			return False
	return True

def vnc_client():
	global backlog
	logger = logging.getLogger("VNC_Thread")
	check_vnc()
	client = VNC(ip_address=vnc_ip, port=vnc_port)
	prev_img = None
	while True:
		try:
			if not check_vnc():
				client = VNC(ip_address=vnc_ip, port=vnc_port)
				client.connect()
			if client.is_connected():
				img = client.get_screenshot()
				if prev_img:
					if not ImageCompare.is_similar(img, prev_img, threshold=0.02)[0]:
						backlog.put(img)
				prev_img = img
			else:
				client.reconnect()
			
		except VNCConnectionError as e:
			logger.error(f"{e}")
		time.sleep(random.randint(1, 10))

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
	# Not multi pc safe
	try:
		events_dir = Path("events")
		events_dir.mkdir(exist_ok=True)
		cols = "timestamp,device"
		timestamp = timestamp = result["timestamp"].strftime("%Y%m%d_%H%M%S")
		vals = [result["timestamp"], 0]
		if "image" in result:
			cols += ",full_image_path"
			filename = f"events/{timestamp}_full.png"
			img:Image.Image = result["image"]
			img.save(filename)
			vals.append(filename)
		if "results" in result:
			cols += ",report"
			vals.append(json.dumps(result["results"]))
		if "cell" in result:
			cols += ",cell_image_path"
			filename = f"events/{timestamp}_cell.png"
			img:Image.Image = result["cell"]
			img.save(filename)
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
		logger = logging.getLogger("Detect_Thread")
		logger.exception("Could not make an event.")

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
				logger = logging.getLogger("Detect_Thread")
				logger.exception("Detection loop failed for an image.")
			finally:
				img_det.unload()
				txt_det.unload()
				txt_ext.unload()
		time.sleep(0.01)


if not db_exists():
	create_db()

portal = threading.Thread(target=webserver, daemon=True)
portal.start()
vnc = threading.Thread(target=vnc_client, daemon=True)
vnc.start()
detector = threading.Thread(target=detect, daemon=True)
detector.start()

while True:
	execute_db(
		"UPDATE settings SET backlog_count = ? WHERE profile = ?",
		(backlog.qsize(), "Default")
	)
	time.sleep(1)
