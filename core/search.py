import logging
from ddgs import DDGS

logger = logging.getLogger(__name__)

def search_web(query: str) -> str:
    """
    Searches DuckDuckGo for the given query and returns a summary of the top result.
    """
    logger.info(f"Searching web for: {query}")
    try:
        with DDGS() as ddgs:
            results = []
            
            # 1. Try News search first
            try:
                results = list(ddgs.news(query, region='us-en', max_results=1))
                if results:
                    logger.info(f"Found News: {results[0].get('title')}")
            except Exception as e:
                logger.warning(f"News Search Error: {e}")
            
            # 2. Fallback to Text search
            if not results:
                logger.info("No news found, trying text search...")
                try:
                    results = list(ddgs.text(query, region='us-en', max_results=1))
                    if results:
                        logger.info(f"Found Text: {results[0].get('title')}")
                except Exception as e:
                    logger.warning(f"Text Search Error: {e}")

            if results:
                r = results[0]
                title = r.get('title', 'No Title')
                body = r.get('body', r.get('snippet', 'No Body'))
                return f"SEARCH RESULTS for '{query}':\nTitle: {title}\nSnippet: {body[:500]}"
            else:
                logger.info("Search returned 0 results.")
                return "SEARCH_EMPTY"
                
    except Exception as e:
        logger.error(f"Connection/Library Error during search: {e}")
        return "SEARCH_ERROR"
