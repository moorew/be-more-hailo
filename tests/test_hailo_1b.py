import urllib.request
import json
import time

def test_chat(model_name):
    print(f"Testing {model_name}...")
    req = urllib.request.Request(
        'http://localhost:8000/api/chat',
        data=json.dumps({
            'model': model_name, 
            'messages': [{'role': 'user', 'content': 'What is the capital of France?'}],
            'stream': False
        }).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        start = time.time()
        response = urllib.request.urlopen(req)
        end = time.time()
        raw_data = response.read().decode()
        print(f"Raw Response: {raw_data}")
        data = json.loads(raw_data)
        if 'message' in data:
            print(f"Response: {data['message']['content'][:100]}...")
        print(f"Time: {end - start:.2f} seconds")
    except Exception as e:
        print(f"Error: {e}")

test_chat('llama3.2:1b')
