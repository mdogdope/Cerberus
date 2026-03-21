import requests

class DiscordWebhook:
	def __init__(self,) -> None:
		pass
	def send(self, url, msg):
		data = {"content": msg}
		try:
			response = requests.post(url, json=data, timeout=10)
			return response
		except Exception as e:
			raise e