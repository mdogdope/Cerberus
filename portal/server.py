from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime, timedelta, timezone
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from random import choice
from typing import Optional
from pathlib import Path
from hashlib import sha256
from lib.database import create_db, query_db, execute_db, db_exists
import logging
import uvicorn, secrets, json, base64, mimetypes

logger = logging.getLogger("cerberus.portal")
if not logging.getLogger().handlers:
	logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)

class WebPortal:
	def __init__(self, host:str = "0.0.0.0", port:int = 80, session_ttl:int = 12, persistant_ttl: int = 720):
		self.host = host
		self.port = port
		self.SESSION_TTL = session_ttl
		self.PERSISTANT_TTL = persistant_ttl
		self.base_dir = Path(__file__).resolve().parent.parent
		self.app = FastAPI()
		self.device_status = {}
		self._table_columns_cache:dict[str, set[str]] = {}
		self._setup_routes()
		self.init_setup = False
	
	# ======= Page Setups =======
	def _setup_routes(self):
		self.app.mount("/static", StaticFiles(directory=str(self.base_dir / "portal/static")), name="static")
		templates = Jinja2Templates(directory=str(self.base_dir / "portal/templates"))
		legal_acceptance_path = self.base_dir / "legal_acceptance.json"

		def verify_session(request:Request, redirect:bool = True):
			token = request.cookies.get("session")	
			if not token:
				raise HTTPException(status_code=401, detail="Not logged in")
			
			user_info = query_db(
				"SELECT users.* FROM users JOIN sessions ON sessions.user_id = users.user_id WHERE sessions.token = ? AND sessions.expires_at > ?",
				(token, datetime.now(timezone.utc))
			)
			if not user_info:
				raise HTTPException(status_code=401, detail="Invalid session")
			
			return user_info
		
		def error(request:Request, error_msg:str, title = "Error", subtitle = None, email = "thecerberusproject@proton.me"):
			if subtitle == None:
				subtitles = [
					"Cerberus just experienced an unexpected runtime vibe check.",
					"Cerberus attempted to do a thing… and the thing said no.",
					"Cerberus just blue screened emotionally.",
					"Cerberus just divided by zero and is taking some time to rethink its life choices.",
					"Cerberus tried its best, but the stack trace says otherwise.",
					"Cerberus rolled a natural 1 on its skill check.",
					"Cerberus encountered a wild exception.",
					"Cerberus wandered into undefined territory.",
					"Cerberus just hit an emotional breakpoint.",
					"Cerberus unlocked the achievement: unexpected error.",
					"Cerberus attempted to debug and things got worse."
				]
				subtitle = choice(subtitles)
			return templates.TemplateResponse(
				"error.html",
				{
					"request": request,
					"title": title,
					"error_msg": error_msg,
					"support_email": email,
					"app_name": "Cerberus",
					"subtitle": subtitle,
					"home_href": "/",
					"logo_src": "/static/res/Cerberus.png",
				},
			)
		
		def hash_password(password:str):
			return sha256(password.encode()).hexdigest()

		def get_table_columns(table_name:str):
			cache = getattr(self, "_table_columns_cache", {})
			if table_name in cache:
				return cache[table_name]
			rows = query_db(f"PRAGMA table_info({table_name})", ())
			columns = {str(row.get("name", "")).strip() for row in rows if row.get("name")}
			cache[table_name] = columns
			self._table_columns_cache = cache
			return columns
		
		
		@self.app.get("/", name="root", response_class = HTMLResponse)
		async def root(request:Request):
			if not legal_acceptance_path.exists():
				self.init_setup = True
				with open(legal_acceptance_path, "w", encoding="utf-8") as f:
					json.dump({"DISCLAIMER": False, "EULA": False, "PRIVACY": False}, f)
			
			with open(legal_acceptance_path, "r", encoding="utf-8") as f:
				legal_acc:dict = json.load(f)
				for doc, status in legal_acc.items():
					if not status:
						return templates.TemplateResponse("legal_doc.html", {"request": request, "doc_path": f"/static/LEGAL/{doc}.html", "title": doc})
			if self.init_setup:
				return templates.TemplateResponse("register.html", {"request": request}, status_code=200)
			
			try:
				verify_session(request)
				return RedirectResponse("/dashboard", status_code=303)
			except HTTPException:
				return RedirectResponse("/login", status_code=303)
			
		
		@self.app.get("/login", response_class = HTMLResponse)
		async def login(request:Request, error:Optional[str] = None):
			return templates.TemplateResponse("login.html", {"request": request, "error": error}, status_code=200)
		
		@self.app.get("/dashboard", response_class = HTMLResponse)
		async def dashboard(request:Request):
			user_info = verify_session(request)
			display_name = user_info[0]["display_name"]
			device_row = query_db(
				"SELECT device_name, device_ip FROM devices ORDER BY device_id ASC LIMIT 1",
				()
			)
			device_name = device_row[0]["device_name"] if device_row else "Child PC"
			device_ip = device_row[0]["device_ip"] if device_row else "Unknown"
			return templates.TemplateResponse(
				"dashboard.html",
				{
					"request": request,
					"display_name": display_name,
					"device_name": device_name,
					"device_ip": device_ip
				},
				status_code=200
			)
		
		@self.app.get("/register", response_class = HTMLResponse)
		async def register(request:Request):
			if not self.init_setup:
				verify_session(request)
			return templates.TemplateResponse("register.html", {"request": request}, status_code=200)
		
		@self.app.get("/account", response_class = HTMLResponse)
		async def account(request:Request, error:Optional[str] = None):
			user_info = verify_session(request)
			display_name = user_info[0]["display_name"]
			return templates.TemplateResponse("account.html", {"request": request, "display_name": display_name, "error": error}, status_code=200)

		@self.app.get("/settings", response_class = HTMLResponse)
		async def settings(request:Request):
			user_info = verify_session(request)
			display_name = user_info[0]["display_name"]
			child_row = query_db("SELECT device_ip FROM devices WHERE device_name = ? LIMIT 1", ("Child PC",))
			child_ip = child_row[0]["device_ip"] if child_row else ""
			discord_row = query_db("SELECT discord_webhook FROM settings WHERE profile = ? LIMIT 1", ("Default",))
			discord_webhook = discord_row[0]["discord_webhook"] if discord_row else ""
			return templates.TemplateResponse("settings.html", {"request": request, "display_name": display_name, "child_ip": child_ip, "discord_webhook": discord_webhook}, status_code=200)
		
		@self.app.exception_handler(401)
		async def auth_err_handler(request:Request, exc:HTTPException):
			return templates.TemplateResponse("auth_error.html", {"request": request, "message": exc.detail}, status_code=401)
		
		@self.app.post("/legal_doc", response_class = RedirectResponse)
		async def legal_doc(request:Request, doc_path:str = Form(...), title:str = Form(...), agree:bool = Form(False)):
			with open(legal_acceptance_path, "r", encoding="utf-8") as f:
				legal_acc = json.load(f)
			if agree and title in legal_acc:
				legal_acc[title] = True
				with open(legal_acceptance_path, "w", encoding="utf-8") as f:
					json.dump(legal_acc, f)
			return RedirectResponse("/", status_code=303)
		
		@self.app.post("/auth/login")
		async def auth_login(request:Request, username:str = Form(...), password:str = Form(...), remember_me:bool = Form(False)):
			if remember_me:
				ttl = self.PERSISTANT_TTL
			else:
				ttl = self.SESSION_TTL
			password = hash_password(password)
			user_info = query_db("""
				SELECT * FROM users
				WHERE username = ? AND password = ?
				""",
				(username, password)
			)
			if user_info == []:
				return RedirectResponse("/login?error=1", status_code=303)
			
			execute_db(
				"DELETE FROM sessions WHERE user_id = ? AND expires_at <= ?",
				(user_info[0]["user_id"], datetime.now(timezone.utc))
			)
			
			token = secrets.token_urlsafe(32)
			expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl)
			
			execute_db("""
				INSERT INTO sessions (user_id, token, expires_at)
				VALUES (?, ?, ?)
				""",
				(user_info[0]["user_id"], token, expires_at)
			)
			
			response = RedirectResponse("/dashboard", status_code=303)
			response.set_cookie(
				key="session",
				value=token,
				httponly=True,
				samesite="lax",
				secure=False,
				max_age=ttl*60*60
			)
			
			return response
		
		@self.app.post("/auth/register", response_class = RedirectResponse)
		async def auth_register(request:Request, username:str = Form(...), display_name:str = Form(...), password:str = Form(...)):
			if not self.init_setup:
				verify_session(request)
			
			password = hash_password(password)
			try:
				execute_db("""
					INSERT INTO users (username, display_name, password)
					VALUES (?, ?, ?)
					""",
					(username, display_name, password)
				)
				self.init_setup = False
				return RedirectResponse("/", status_code=303)
			except Exception as e:
				return error(request, str(e))
		
		@self.app.post("/auth/logout")
		async def logout(request:Request):
			token = request.cookies.get("session")
			
			if token:
				execute_db("DELETE FROM sessions WHERE token = ?", (token,))
			
			response = RedirectResponse("/login", status_code=303)
			response.delete_cookie("session")
			return response
		
		@self.app.post("/api/events")
		async def api_events(request:Request, page:int, count:int):
			def parse_report(report_value):
				if report_value is None:
					return []
				if isinstance(report_value, (list, dict)):
					return report_value
				if isinstance(report_value, str):
					try:
						return json.loads(report_value)
					except Exception:
						return []
				return []

			def severity_from_report(report_payload, event_type):
				if not isinstance(report_payload, list):
					return "low"

				if str(event_type or "").lower() == "text":
					nsfw_score = 0.0
					for item in report_payload:
						label = str(item.get("label", "")).strip().upper() if isinstance(item, dict) else ""
						score = float(item.get("score", 0.0)) if isinstance(item, dict) else 0.0
						if label == "NSFW":
							nsfw_score = score
							break
					if nsfw_score >= 0.85:
						return "high"
					if nsfw_score >= 0.65:
						return "medium"
					if nsfw_score >= 0.45:
						return "low"
					return "neutral"

				order = {"neutral": 0, "low": 1, "medium": 2, "high": 3}
				best_label = "neutral"
				best_score = -1.0
				for item in report_payload:
					if not isinstance(item, dict):
						continue
					label = str(item.get("label", "")).strip().lower()
					score = float(item.get("score", 0.0))
					if score > best_score and label in order:
						best_score = score
						best_label = label
				return best_label

			page = max(page, 1)
			count = max(min(count,1000),1)
			offset = (page - 1) * count
			
			total_count = query_db("""
				SELECT COUNT(*) AS total_count
				FROM events
				""",
				()
			)[0]["total_count"]
			events = query_db("""
				SELECT
					e.event_id,
					d.device_name AS device_name,
					t.name AS event_type,
					e.report,
					e.timestamp
				FROM events e
				LEFT JOIN devices d ON e.device = d.device_id
				LEFT JOIN event_types t ON e.event_type = t.event_type_id
				ORDER BY e.event_id DESC
				LIMIT ? OFFSET ?
				""",
				(count, offset)
			)
			for event in events:
				report_payload = parse_report(event.get("report"))
				event["severity"] = severity_from_report(report_payload, event.get("event_type"))
				event["timestamp"] = event.get("timestamp")
				event.pop("report", None)
			return {"page": page, "count": count, "total_count": total_count, "events": events}
		
		# TODO: Make sure it can get events and images once everything else is setup.
		@self.app.post("/api/event")
		async def api_event(request:Request, event_id:Optional[int] = None):
			resolved_event_id = event_id
			try:
				if resolved_event_id is None:
					raw_query_id = request.query_params.get("event_id")
					if raw_query_id is not None and str(raw_query_id).strip() != "":
						try:
							resolved_event_id = int(str(raw_query_id).strip())
						except Exception:
							raise HTTPException(status_code=400, detail="Invalid event_id query parameter")
				if resolved_event_id is None:
					try:
						payload = await request.json()
					except Exception:
						payload = None
					if isinstance(payload, dict) and payload.get("event_id") is not None:
						try:
							resolved_event_id = int(payload.get("event_id"))  # type: ignore
						except Exception:
							raise HTTPException(status_code=400, detail="Invalid event_id in JSON body")
				if resolved_event_id is None:
					try:
						form = await request.form()
					except Exception:
						form = None
					if form and form.get("event_id") is not None:
						try:
							resolved_event_id = int(form.get("event_id")) # type: ignore
						except Exception:
							raise HTTPException(status_code=400, detail="Invalid event_id in form body")
				if resolved_event_id is None:
					raise HTTPException(status_code=400, detail="Missing event_id")
				if resolved_event_id <= 0:
					raise HTTPException(status_code=400, detail="event_id must be greater than 0")

				logger.info("api_event(): request event_id=%s", resolved_event_id)

				def parse_report(report_value):
					if report_value is None:
						return []
					if isinstance(report_value, (list, dict)):
						return report_value
					if isinstance(report_value, str):
						try:
							return json.loads(report_value)
						except Exception:
							return []
					return []

				def severity_from_report(report_payload, event_type):
					if not isinstance(report_payload, list):
						return "low"

					if str(event_type or "").lower() == "text":
						nsfw_score = 0.0
						for item in report_payload:
							label = str(item.get("label", "")).strip().upper() if isinstance(item, dict) else ""
							score = float(item.get("score", 0.0)) if isinstance(item, dict) else 0.0
							if label == "NSFW":
								nsfw_score = score
								break
						if nsfw_score >= 0.85:
							return "high"
						if nsfw_score >= 0.65:
							return "medium"
						if nsfw_score >= 0.45:
							return "low"
						return "neutral"

					order = {"neutral": 0, "low": 1, "medium": 2, "high": 3}
					best_label = "neutral"
					best_score = -1.0
					for item in report_payload:
						if not isinstance(item, dict):
							continue
						label = str(item.get("label", "")).strip().lower()
						score = float(item.get("score", 0.0))
						if score > best_score and label in order:
							best_score = score
							best_label = label
					return best_label

				event_columns = get_table_columns("events")
				text_select = "e.text" if "text" in event_columns else "NULL AS text"
				full_image_select = "e.full_image_path" if "full_image_path" in event_columns else "NULL AS full_image_path"
				cell_image_select = "e.cell_image_path" if "cell_image_path" in event_columns else "NULL AS cell_image_path"
				sound_select = "e.sound_path" if "sound_path" in event_columns else "NULL AS sound_path"
				report_select = "e.report" if "report" in event_columns else "NULL AS report"

				event_rows = query_db(f"""
					SELECT
						e.event_id,
						d.device_name AS device_name,
						{report_select},
						{full_image_select},
						{cell_image_select},
						{sound_select},
						t.name AS event_type,
						e.timestamp,
						{text_select}
					FROM events e
					LEFT JOIN devices d ON e.device = d.device_id
					LEFT JOIN event_types t ON e.event_type = t.event_type_id
					WHERE e.event_id = ?
					LIMIT 1
					""",
					(resolved_event_id,)
				)
				if not event_rows:
					raise HTTPException(status_code=404, detail="Event not found")

				row = event_rows[0]
				report_data = parse_report(row.get("report"))
				severity = severity_from_report(report_data, row.get("event_type"))

				def load_media(path_value:Optional[str]):
					if not path_value:
						return None, None, None
					raw_path = Path(str(path_value))
					candidates = []
					if raw_path.is_absolute():
						candidates.append(raw_path)
					else:
						# Try common roots so relative DB paths work no matter current working directory.
						candidates.append(self.base_dir / raw_path)
						candidates.append(Path.cwd() / raw_path)
						candidates.append(raw_path)
						if raw_path.name:
							candidates.append(self.base_dir / "events" / raw_path.name)

					seen = set()
					resolved_path = None
					for candidate in candidates:
						key = str(candidate)
						if key in seen:
							continue
						seen.add(key)
						if candidate.exists() and candidate.is_file():
							resolved_path = candidate
							break

					if resolved_path is None:
						return None, None, None

					mime, _ = mimetypes.guess_type(str(resolved_path))
					if not mime:
						mime = "application/octet-stream"
					data = base64.b64encode(resolved_path.read_bytes()).decode("ascii")
					return data, mime, resolved_path.name

				image_data, image_mime, image_name = load_media(row.get("full_image_path"))
				if image_data is None:
					image_data, image_mime, image_name = load_media(row.get("cell_image_path"))
				audio_data, audio_mime, audio_name = load_media(row.get("sound_path"))

				return {
					"event_id": row.get("event_id"),
					"event_type": row.get("event_type"),
					"device_name": row.get("device_name"),
					"severity": severity,
					"timestamp": row.get("timestamp"),
					"report": report_data,
					"text": row.get("text"),
					"image_data": image_data,
					"image_mime": image_mime,
					"image_name": image_name,
					"audio_data": audio_data,
					"audio_mime": audio_mime,
					"audio_name": audio_name,
				}
			except HTTPException:
				raise
			except Exception:
				# TODO: Remove the print
				print(f"api_event(): Failed to load event details for event_id={resolved_event_id}", flush=True)
				logger.exception("api_event(): Failed to load event details for event_id=%s", resolved_event_id)
				raise HTTPException(status_code=500, detail=f"Could not load event details for event_id={resolved_event_id}")

		@self.app.get("/api/device-status")
		async def api_device_status_get(request:Request):
			return {"status": self.device_status}

		@self.app.post("/api/device-status")
		async def api_device_status_post(request:Request):
			try:
				payload = await request.json()
			except Exception:
				payload = None
			if payload is None:
				raise HTTPException(status_code=400, detail="Expected JSON payload")
			if not isinstance(payload, dict):
				raise HTTPException(status_code=400, detail="Payload must be a JSON object")

			for key, value in payload.items():
				self.device_status[key] = value
			self.device_status["updated_at"] = datetime.now(timezone.utc).isoformat()
			return {"status": self.device_status}
		
		@self.app.post("/api/account")
		async def api_account(request:Request):
			user_info = verify_session(request)
			user_id = user_info[0]["user_id"]
			old_password_hash = user_info[0]["password"]
			form = dict(await request.form())
			form_type = form.get("form_type")
			
			if form_type == "display_name":
				display_name = str(form.get("display_name", "")).strip()
				if display_name:
					execute_db("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, user_id))
				return RedirectResponse("/account", status_code=303)
			elif form_type == "password":
				old_password = hash_password(str(form.get("old_password", "")))
				new_password = str(form.get("new_password", ""))
				confirm_new_password = str(form.get("confirm_new_password", ""))
				if old_password != old_password_hash:
					return RedirectResponse("/account?error=1", status_code=303)
				if not new_password or new_password != confirm_new_password:
					return RedirectResponse("/account?error=1", status_code=303)
				execute_db("UPDATE users SET password = ? WHERE user_id = ?", (hash_password(new_password), user_id))
				return RedirectResponse("/account", status_code=303)
			
			return RedirectResponse("/account", status_code=303)
		
		@self.app.post("/api/settings")
		async def api_settings(request:Request):
			form = dict(await request.form())
			form_type = form.get("form_type")
			if form_type == "child_ip":
				child_ip = str(form.get("child_ip", "")).strip()
				if child_ip:
					existing = query_db(
						"SELECT device_id FROM devices WHERE device_name = ? ORDER BY device_id LIMIT 1",
						("Child PC",),
					)
					if existing:
						execute_db(
							"UPDATE devices SET device_ip = ? WHERE device_id = ?",
							(child_ip, existing[0]["device_id"]),
						)
					else:
						execute_db(
							"INSERT INTO devices (device_name, device_ip) VALUES (?, ?)",
							("Child PC", child_ip),
						)
			elif form_type == "discord_webhook":
				discord_webhook = str(form.get("discord_webhook", "")).strip()
				if discord_webhook:
					existing = query_db(
						"SELECT setting_id FROM settings WHERE profile = ?",
						("Default",)
					)
					if existing:
						execute_db(
							"UPDATE settings SET discord_webhook = ? WHERE setting_id = ?",
							(discord_webhook, existing[0]["setting_id"])
						)
					else:
						execute_db(
							"INSERT INTO settings (profile, discord_webhook) VALUES (?, ?)",
							("Default", discord_webhook)
						)
			return RedirectResponse("/settings", status_code=303)
		
		
		@self.app.get("/test")
		async def test(request:Request):
			e = ""
			for i in range(50):
				e += secrets.token_urlsafe(64) + "\n"
			return error(request, str(e))
	
	def run(self):
		uvicorn.run(
			self.app,
			host=self.host,
			port=self.port,
			log_level="warning"
		)
