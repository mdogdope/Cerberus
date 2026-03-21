from vncdotool import api

class VNCConnectionError(Exception):
	pass

class VNC:
	def __init__(self, ip_address, port, password = None) -> None:
		self.ip_address = ip_address
		self.port = port
		self.password = password
		self.client = None
	
	def connect(self):
		try:
			if self.password:
				self.client = api.connect(f"{self.ip_address}::{self.port}", timeout=10, password=self.password)
			else:
				self.client = api.connect(f"{self.ip_address}::{self.port}", timeout=10)
		except Exception as e:
			self.client = None
			raise VNCConnectionError("Could not connect to VNC server") from e
	
	def get_screenshot(self):
		if self.client is None:
			raise VNCConnectionError("Not connected to VNC server")
		
		try:
			self.client.refreshScreen()
			img = self.client.screen
			if img is None:
				raise VNCConnectionError("No Image returned")
			return img
		except Exception as e:
			self.client = None
			raise VNCConnectionError("Failed to get screen") from e
	
	def get_ip(self):
		return self.ip_address
	
	def is_connected(self):
		try:
			self.client.refreshScreen()
			return True
		except Exception:
			return False
	def reconnect(self):
		self.client = None
		self.connect()