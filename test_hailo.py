import urllib.request
import json
import time

def test_chat(model_name):
    print(f"Testing {model_name}...")
    req = urllib.request.Request(
        'http://localhost:8000/api/chat',
        data=json.dumps({
            'model': model_name, 
            'messages': [{'role': 'user', 'content': 'What is self-hosting?'}],
            'stream': False
        }).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        start = time.time()
        response = urllib.request.urlopen(req)
        end = time.time()
        data = json.loads(response.read().decode())
        print(f"Response: {data['message']['content'][:100]}...")
        print(f"Time: {end - start:.2f} seconds")
    except Exception as e:
        print(f"Error: {e}")

test_chat('llama3.2:3b')
