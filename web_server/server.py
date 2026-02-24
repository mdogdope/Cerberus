from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
from pathlib import Path
import uvicorn, sqlite3

class WebPortal:
	def __init__(self, db_path: str, host: str = "127.0.0.1", port: int = 80):
		self.host = host
		self.port = port
		self.base_dir = Path(__file__).resolve().parent
		self.db_path = self.base_dir / db_path
		self.app = FastAPI()
		self._setup_routes()
	
	def query_db(self, query: str, params, one: bool = False):
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
		return con
	
	def _setup_routes(self):
		self.app.mount(
			"/static",
			StaticFiles(directory=str(self.base_dir / "static")),
			name="static",
		)
		
		templates = Jinja2Templates(directory=str(self.base_dir / "templates"))
		
		@self.app.get("/", response_class=HTMLResponse)
		async def root(request: Request):
			return templates.TemplateResponse("login.html", {"request": request})
		
		@self.app.get("/dashboard", response_class=HTMLResponse)
		async def dashboard(request: Request):
			return templates.TemplateResponse("dashboard.html", {"request": request})
		
		@self.app.get("/register", response_class=HTMLResponse)
		async def register(request: Request):
			return templates.TemplateResponse("register.html", {"request": request})
	
	def run(self):
		uvicorn.run(self.app, host=self.host, port=self.port)


