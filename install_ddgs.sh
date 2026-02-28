#!/bin/bash
cd ~/be-more-agent
source venv/bin/activate
pip install ddgs -q
pip install --upgrade duckduckgo_search -q
python3 -c "try:
    from ddgs import DDGS
    print('ddgs OK')
except ImportError:
    print('ddgs import failed, using duckduckgo_search')
    from duckduckgo_search import DDGS
    print('duckduckgo_search OK')"
