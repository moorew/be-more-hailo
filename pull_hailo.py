import urllib.request
import json

def pull_model(model_name):
    print(f"Pulling {model_name}...")
    req = urllib.request.Request(
        'http://localhost:8000/api/pull',
        data=json.dumps({'model': model_name, 'stream': False}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        response = urllib.request.urlopen(req)
        print(response.read().decode())
    except Exception as e:
        print(f"Error: {e}")

pull_model('qwen2.5-instruct:1.5b')
