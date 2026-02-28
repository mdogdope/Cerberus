from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime, timedelta, timezone
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
from pathlib import Path
from hashlib import sha256
import uvicorn, sqlite3, secrets

class WebPortal:
	def __init__(self, db_path:str, host:str = "127.0.0.1", port:int = 80, session_timeout:int = 1440):
		self.host = host
		self.port = port
		self.SESSION_TTL_HOURS = session_timeout
		self.base_dir = Path(__file__).resolve().parent
		self.db_path = self.base_dir / db_path
		self.app = FastAPI()
		self._setup_routes()
	
	# ======= Page Setups =======
	def _setup_routes(self):
		self.app.mount("/static", StaticFiles(directory=str(self.base_dir / "static")), name="static")
		templates = Jinja2Templates(directory=str(self.base_dir / "templates"))
		
		@self.app.get("/", name="root", response_class=HTMLResponse)
		async def root(request: Request, error: Optional[str] = None):
			return templates.TemplateResponse("login.html", {"request": request, "error": error})
		
		@self.app.get("/dashboard", response_class=HTMLResponse)
		async def dashboard(request: Request):
			return templates.TemplateResponse("dashboard.html", {"request": request})
		
		@self.app.get("/register", response_class=HTMLResponse)
		async def register(request: Request):
			return templates.TemplateResponse("register.html", {"request": request})
		
		@self.app.exception_handler(401)
		async def auth_err_handler(request: Request, exc: HTTPException):
			return templates.TemplateResponse("auth_error.html", {"request": request, "message": exc.detail}, status_code=401)
		
		@self.app.post("/auth/login")
		async def login(request: Request, username:str = Form(...), password:str = Form(...)):
			# response = RedirectResponse("/dashboard", status_code=303)
			# return response
			password = sha256(password.encode()).hexdigest()
			display_name = self.query_db("SELECT display_name FROM users WHERE username = ? AND password = ?", (username, password), True)
			if not display_name:
				return RedirectResponse("/?err=1", status_code=401)
			
			token = secrets.token_urlsafe(32)
			expires_at = datetime.now(timezone.utc) + timedelta(hours=self.SESSION_TTL_HOURS)
			
			#TODO: Make SQL query to add token, username, and expires_at to DB
			
			response = RedirectResponse("/dashboard", status_code=303)
			response.set_cookie(
				key="session",
				value=token,
				httponly=True,
				samesite="lax",
				secure=False
			)
			
			return response
		
		@self.app.post("/auth/register")
		async def register_form(request: Request, username:str = Form(...), display_name:str = Form(...), password:str = Form(...)):
			token = request.cookies.get("session")
			
			if not token:
				raise HTTPException(status_code=401, detail="Not logged in")
			
			cur_dn = self.query_db("SELECT users.display_name FROM users JOIN sessions ON sessions.user_id = users.user_id WHERE sessions.token = ?", (token,), one=True)
			
			if not cur_dn:
				raise HTTPException(status_code=401, detail="Invalid session")
		
		@self.app.post("/auth/logout")
		async def logout(request: Request):
			token = request.cookies.get("session")
			
			if token:
				# TODO: Make SQL query to remove token
				pass
			
			response = RedirectResponse("/", status_code=303)
			response.delete_cookie("session")
			return response
	
	def run(self):
		uvicorn.run(self.app, host=self.host, port=self.port)
	
	def query_db(self, query:str, params, one:bool = False):
		con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5)
		con.row_factory = sqlite3.Row
		try:
			cur = con.execute(query, params)
			if one:
				row = cur.fetchone()
				return dict(row) if row else None
			else:
				rows = cur.fetchall()
				return [dict(row) for row in rows]
		finally:
			con.close()