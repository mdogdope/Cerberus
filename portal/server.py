from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime, timedelta, timezone
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from random import choice
from typing import Optional
from pathlib import Path
from hashlib import sha256
from lib.database import create_db, query_db, execute_db, db_exists, wr_tx
import uvicorn, secrets, json

class WebPortal:
	def __init__(self, host:str = "0.0.0.0", port:int = 80, session_ttl:int = 24, persistant_ttl: int = 720):
		self.host = host
		self.port = port
		self.SESSION_TTL = session_ttl
		self.PERSISTANT_TTL = persistant_ttl
		self.base_dir = Path(__file__).resolve().parent.parent
		self.app = FastAPI()
		self._setup_routes()
		self.init_setup = False
	
	# ======= Page Setups =======
	def _setup_routes(self):
		self.app.mount("/static", StaticFiles(directory=str(self.base_dir / "portal/static")), name="static")
		templates = Jinja2Templates(directory=str(self.base_dir / "portal/templates"))
		
		def error(request: Request, error_msg:str, title = "Error", subtitle = None, email = "thecerberusproject@proton.me"):
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
		
		@self.app.get("/", name="root", response_class=HTMLResponse)
		async def root(request: Request):
			if not (self.base_dir / "legal_acceptance.json").exists():
				with open("legal_acceptance.json", "w") as f:
					json.dump({"DISCLAIMER": False, "EULA": False, "PRIVACY": False}, f)
					f.close()
			
			with open("legal_acceptance.json", "r") as f:
				legal_acc:dict = json.load(f)
				for doc, status in legal_acc.items():
					if not status:
						return templates.TemplateResponse("legal_doc.html", {"request": request, "doc_path": f"/static/LEGAL/{doc}.html", "title": doc})
			if not (self.base_dir / "cerberus.db").exists():
				create_db()
				self.init_setup = True
				return templates.TemplateResponse("register.html", {"request": request}, status_code=303)
			return templates.TemplateResponse("login.html", {"request": request}, status_code=303)
		
		@self.app.get("/login", response_class=HTMLResponse)
		async def login(request: Request, error: Optional[str] = None):
			return templates.TemplateResponse("login.html", {"request": request, "error": error}, status_code=303)
		
		@self.app.get("/dashboard", response_class=HTMLResponse)
		async def dashboard(request: Request):
			return templates.TemplateResponse("dashboard.html", {"request": request}, status_code=303)
		
		@self.app.get("/register", response_class=HTMLResponse)
		async def register(request: Request):
			return templates.TemplateResponse("register.html", {"request": request}, status_code=303)
		
		@self.app.exception_handler(401)
		async def auth_err_handler(request: Request, exc: HTTPException):
			return templates.TemplateResponse("auth_error.html", {"request": request, "message": exc.detail}, status_code=401)
		
		@self.app.post("/legal_doc", response_class=RedirectResponse)
		async def legal_doc(request: Request, doc_path:str = Form(...), title:str = Form(...), agree: bool = Form(False)):
			with open("legal_acceptance.json", "r") as f:
				legal_acc = json.load(f)
			if agree:
				legal_acc[title] = True
				with open("legal_acceptance.json", "w") as f:
					json.dump(legal_acc, f)
			return RedirectResponse("/", status_code=303)
		
		@self.app.post("/auth/login")
		async def auth_login(request: Request, username:str = Form(...), password:str = Form(...), remember_me: bool = Form(False)):
			# response = RedirectResponse("/dashboard", status_code=303)
			# return response
			if remember_me:
				ttl = self.PERSISTANT_TTL
			else:
				ttl = self.SESSION_TTL
			password = sha256(password.encode()).hexdigest()
			user_info = query_db("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
			if not user_info:
				return RedirectResponse("/login?err=1", status_code=401)
			
			token = secrets.token_urlsafe(32)
			expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl)
			
			execute_db("INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)", (user_info[0]["user_id"], token, expires_at))
			
			response = RedirectResponse("/dashboard", status_code=303)
			response.set_cookie(
				key="session",
				value=token,
				httponly=True,
				samesite="lax",
				secure=False,
				max_age=ttl
			)
			
			return response
		
		@self.app.post("/auth/register", response_class=RedirectResponse)
		async def auth_register(request: Request, username:str = Form(...), display_name:str = Form(...), password:str = Form(...)):
			if not self.init_setup:
				token = request.cookies.get("session")
				
				if not token:
					raise HTTPException(status_code=401, detail="Not logged in")
				
				user_info = query_db("SELECT users.* FROM users JOIN sessions ON sessions.user_id = users.user_id WHERE sessions.token = ?", (token,))
				
				if not user_info:
					raise HTTPException(status_code=401, detail="Invalid session")
			
			password = sha256(password.encode()).hexdigest()
			try:
				execute_db("INSERT INTO users (username, display_name, password) VALUES (?, ?, ?)", (username, display_name, password))
				self.init_setup = False
				return RedirectResponse("/", status_code=303)
			except Exception as e:
				return error(request, str(e))
		
		@self.app.post("/auth/logout")
		async def logout(request: Request):
			token = request.cookies.get("session")
			
			if token:
				# TODO: Make SQL query to remove token
				pass
			
			response = RedirectResponse("/login", status_code=303)
			response.delete_cookie("session")
			return response
		
		@self.app.get("/test", response_class=HTMLResponse)
		async def test(request: Request):
			e = ""
			for i in range(50):
				e += secrets.token_urlsafe(64) + "\n"
			return error(request, str(e))
	
	def run(self):
		uvicorn.run(self.app, host=self.host, port=self.port)
