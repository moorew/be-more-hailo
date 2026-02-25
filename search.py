import urllib.request, urllib.parse, re
url = 'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote('hailo_model_zoo_genai llama 3 hef')
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
html = urllib.request.urlopen(req).read().decode('utf-8')
links = re.findall(r'class=\"result__url\" href=\"([^\"]+)\"', html)
for link in links:
    if 'uddg=' in link:
        print(urllib.parse.unquote(link.split('uddg=')[1].split('&')[0]))
