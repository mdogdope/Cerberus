from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime, timedelta, timezone
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from random import choice
from typing import Optional
from pathlib import Path
from hashlib import sha256
from lib.database import create_db, query_db, execute_db, ensure_device_name_unique
import uvicorn, secrets, json, base64, mimetypes

class WebPortal:
	def __init__(self, host:str = "0.0.0.0", port:int = 80, session_ttl:int = 12, persistant_ttl: int = 720):
		self.host = host
		self.port = port
		self.SESSION_TTL = session_ttl
		self.PERSISTANT_TTL = persistant_ttl
		self.base_dir = Path(__file__).resolve().parent.parent
		self.app = FastAPI()
		self.device_status = {}
		self._setup_routes()
		self.init_setup = False
	
	# ======= Page Setups =======
	def _setup_routes(self):
		self.app.mount("/static", StaticFiles(directory=str(self.base_dir / "portal/static")), name="static")
		templates = Jinja2Templates(directory=str(self.base_dir / "portal/templates"))
		legal_acceptance_path = self.base_dir / "legal_acceptance.json"

		@self.app.on_event("startup")
		async def _startup():
			if (self.base_dir / "cerberus.db").exists():
				ensure_device_name_unique()
		
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
		
		
		@self.app.get("/", name="root", response_class = HTMLResponse)
		async def root(request:Request):
			if not legal_acceptance_path.exists():
				with open(legal_acceptance_path, "w", encoding="utf-8") as f:
					json.dump({"DISCLAIMER": False, "EULA": False, "PRIVACY": False}, f)
			
			with open(legal_acceptance_path, "r", encoding="utf-8") as f:
				legal_acc:dict = json.load(f)
				for doc, status in legal_acc.items():
					if not status:
						return templates.TemplateResponse("legal_doc.html", {"request": request, "doc_path": f"/static/LEGAL/{doc}.html", "title": doc})
			if not (self.base_dir / "cerberus.db").exists():
				create_db()
				self.init_setup = True
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
			discord_row = query_db("SELECT discord_webhook FROM settings WHERE profile = ? LIMIT 1", ("discord_webhook",))
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
					json_extract(e.report, '$.severity') AS severity,
					json_extract(e.report, '$.timestamp') AS timestamp
				FROM events e
				LEFT JOIN devices d ON e.device = d.device_id
				LEFT JOIN event_types t ON e.event_type = t.event_type_id
				ORDER BY e.event_id DESC
				LIMIT ? OFFSET ?
				""",
				(count, offset)
			)
			return {"page": page, "count": count, "total_count": total_count, "events": events}
		
		# TODO: Make sure it can get events and images once everything else is setup.
		@self.app.post("/api/event")
		async def api_event(request:Request, event_id:int):
			event_rows = query_db("""
				SELECT
					e.event_id,
					d.device_name AS device_name,
					e.report,
					e.full_image_path,
					e.cell_image_path,
					e.sound_path,
					t.name AS event_type
				FROM events e
				LEFT JOIN devices d ON e.device = d.device_id
				LEFT JOIN event_types t ON e.event_type = t.event_type_id
				WHERE e.event_id = ?
				LIMIT 1
				""",
				(event_id,)
			)
			if not event_rows:
				raise HTTPException(status_code=404, detail="Event not found")

			row = event_rows[0]
			report_data = {}
			if row.get("report"):
				try:
					report_data = json.loads(row["report"])
				except Exception:
					report_data = {}

			def load_media(path_value:Optional[str]):
				if not path_value:
					return None, None, None
				path = Path(path_value)
				if not path.exists() or not path.is_file():
					return None, None, None
				mime, _ = mimetypes.guess_type(str(path))
				if not mime:
					mime = "application/octet-stream"
				data = base64.b64encode(path.read_bytes()).decode("ascii")
				return data, mime, path.name

			image_path = row.get("full_image_path") or row.get("cell_image_path")
			image_data, image_mime, image_name = load_media(image_path)
			audio_data, audio_mime, audio_name = load_media(row.get("sound_path"))

			return {
				"event_id": row.get("event_id"),
				"event_type": row.get("event_type"),
				"device_name": row.get("device_name"),
				"severity": report_data.get("severity"),
				"timestamp": report_data.get("timestamp"),
				"image_data": image_data,
				"image_mime": image_mime,
				"image_name": image_name,
				"audio_data": audio_data,
				"audio_mime": audio_mime,
				"audio_name": audio_name,
			}

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
					execute_db("DELETE FROM settings WHERE profile = ?", ("discord_webhook",))
					execute_db("INSERT INTO settings (profile, discord_webhook) VALUES (?, ?)", ("discord_webhook", discord_webhook))
			return RedirectResponse("/settings", status_code=303)
		
		
		@self.app.get("/test")
		async def test(request:Request):
			e = ""
			for i in range(50):
				e += secrets.token_urlsafe(64) + "\n"
			return error(request, str(e))
	
	def run(self):
		uvicorn.run(self.app, host=self.host, port=self.port)
