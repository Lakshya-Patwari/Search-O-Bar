import os
import requests
from dotenv import load_dotenv
from serpapi import GoogleSearch

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

def web_search(query, count=6):
    """
    Performs a Google search using SerpApi.
    If no API key is set, returns mock results.
    """
    if not SERPAPI_API_KEY:
        return [
            {"title": "Mock Result 1", "url": "https://example.com/1", "snippet": "Mock snippet from mock search results."},
            {"title": "Mock Result 2", "url": "https://example.com/2", "snippet": "Another mock snippet from mock search results."}
        ]

    try:
        params = {
            "api_key": SERPAPI_API_KEY,
            "engine": "google",
            "q": query,
            "num": count,
            "gl": "us",
            "hl": "en"
        }
        
        # Use the corrected SerpApi Client to perform the search
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            print(f"SerpApi Error: {results['error']}")
            return []

        extracted_results = []
        for item in results.get("organic_results", []):
            extracted_results.append({
                "title": item.get("title"),
                "url": item.get("link"),
                "snippet": item.get("snippet")
            })
            
        return extracted_results

    except Exception as e:
        print(f"An error occurred during the SerpApi search: {e}")
        return []

