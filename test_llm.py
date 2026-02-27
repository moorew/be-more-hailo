import logging
import sys
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
from core.llm import Brain
print("Initialized Memory...")
b = Brain()
print("Thinking...")
out = list(b.stream_think('hello'))
print(f"Stream result: {out}")
print("Done")
