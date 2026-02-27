import requests
import json
print("Testing API")
try:
    r = requests.post('http://127.0.0.1:8000/api/chat', json={'model': 'llama3.2:3b', 'messages': [{'role': 'user', 'content': 'hello'}]})
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")
except Exception as e:
    print(e)
