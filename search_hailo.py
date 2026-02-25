import urllib.request
import urllib.parse
import re

query = "Hailo-10H LLM Python API Llama 3"
url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    snippets = re.findall(r'class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
    for s in snippets[:10]:
        print(re.sub(r'<[^>]+>', '', s).strip())
        print("---")
except Exception as e:
    print(e)
