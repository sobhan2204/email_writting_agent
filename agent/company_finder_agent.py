from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import os
import json
import asyncio
import httpx

# Initialize MCP server
mcp = FastMCP("websearch-mcp-server")

# Load environment variables
load_dotenv()

tavily_api_key = os.getenv("TAVILY_API_KEY")
if not tavily_api_key:
    raise ValueError("TAVILY_API_KEY is missing from .env")


@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> dict:
    """
    Search the web for the query and return results with links
    
    Args:
        query: Search query in English
        max_results: Maximum number of results to return (default: 5)
    
    Returns:
        dict: Contains 'results' list with title, url, and content for each result
    """
    print(f"Searching the web for: {query}")
    try:
        # Direct API call to Tavily
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_answer": False,
                    "include_images": False,
                    "include_raw_content": False
                },
                timeout=30.0
            )
            response.raise_for_status()
            search_results = response.json()
        
        formatted_results = {
            "query": query,
            "results": []
        }
        
        for result in search_results.get("results", []):
            formatted_results["results"].append({
                "title": result.get("title", "No title"),
                "url": result.get('url', 'No url'),
                "content": result.get('content', 'No content'),
                "score": result.get('score', 0)
            })
        
        print(f"Found {len(formatted_results['results'])} results")
        return formatted_results
        
    except Exception as e:
        print(f"Failed web search due to: {str(e)}")
        return {
            "query": query,
            "results": [],
            "error": str(e)
        }


@mcp.tool()
async def search_web_links_only(query: str, max_results: int = 5) -> list:
    """
    Search the web and return only the URLs
    
    Args:
        query: Search query in English
        max_results: Maximum number of results to return
    
    Returns:
        list: List of URLs
    """
    print(f"Searching for links: {query}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic"
                },
                timeout=30.0
            )
            response.raise_for_status()
            search_results = response.json()
        
        urls = [result.get('url') for result in search_results.get('results', [])]
        
        print(f"Found {len(urls)} links")
        return urls
        
    except Exception as e:
        print(f"Error during web search: {str(e)}")
        return []


async def scrape_companies_from_url(url: str) -> dict:
    """
    Scrape a blog/article URL to extract company names and their websites
    
    Args:
        url: URL of the blog/article to scrape
    
    Returns:
        dict: Contains company names, URLs, and metadata
    """
    print(f"\nScraping companies from: {url}")
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            html_content = response.text
        
        from bs4 import BeautifulSoup
        import re
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text content
        text = soup.get_text()
        
        # Find all links in the page
        all_links = soup.find_all('a', href=True)
        
        companies = {}
        
        # Pattern to identify company-like links
        company_patterns = [
            r'https?://(?:www\.)?([a-zA-Z0-9-]+)\.(com|ai|io|co|net|app)',
        ]
        
        # Exclude common non-company domains
        exclude_domains = [
            'twitter.com', 'x.com', 'facebook.com', 'linkedin.com', 'instagram.com',
            'youtube.com', 'github.com', 'medium.com', 'google.com', 'apple.com',
            'microsoft.com', 'amazon.com', 'techcrunch.com', 'crunchbase.com',
            'bloomberg.com', 'forbes.com', 'reuters.com', 'wsj.com'
        ]
        
        for link in all_links:
            href = link.get('href', '')
            link_text = link.get_text(strip=True)
            
            # Check if it's a valid URL
            if not href.startswith('http'):
                continue
            
            # Skip excluded domains
            if any(domain in href.lower() for domain in exclude_domains):
                continue
            
            # Extract domain name
            match = re.search(r'https?://(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})', href)
            if match:
                domain = match.group(1)
                
                # Use link text as company name if available, otherwise use domain
                company_name = link_text if link_text and len(link_text) < 50 else domain.split('.')[0].title()
                
                # Clean company name
                company_name = re.sub(r'[^\w\s-]', '', company_name).strip()
                
                if company_name and len(company_name) > 2:
                    companies[company_name] = href
        
        print(f"Found {len(companies)} potential companies")
        return {
            "source_url": url,
            "companies": companies,
            "company_names": list(companies.keys()),
            "count": len(companies)
        }
        
    except Exception as e:
        print(f"Error scraping {url}: {str(e)}")
        return {
            "source_url": url,
            "companies": {},
            "company_names": [],
            "count": 0,
            "error": str(e)
        }


@mcp.tool()
async def find_companies_from_search(query: str, max_results: int = 5) -> dict:
    """
    Search for companies and scrape the results to extract actual company websites
    
    Args:
        query: Search query (e.g., "AI agent startups")
        max_results: Number of search results to process
    
    Returns:
        dict: Contains all companies found with their URLs and names
    """
    print(f"\n{'='*60}")
    print(f"Starting company search for: {query}")
    print(f"{'='*60}")
    
    # Step 1: Search the web
    search_results = await search_web(query, max_results=max_results)
    
    all_companies = {}
    all_company_names = []
    
    # Step 2: Scrape each result URL
    for i, result in enumerate(search_results['results'], 1):
        url = result['url']
        print(f"\n[{i}/{len(search_results['results'])}] Processing: {result['title'][:60]}...")
        
        scraped_data = await scrape_companies_from_url(url)
        
        # Merge companies from this page
        for company_name, company_url in scraped_data['companies'].items():
            if company_name not in all_companies:
                all_companies[company_name] = company_url
                all_company_names.append(company_name)
    
    return {
        "query": query,
        "total_companies_found": len(all_companies),
        "companies": all_companies,  # Dict: {company_name: company_url}
        "company_names": all_company_names,  # List: [company_name1, company_name2, ...]
        "company_urls": list(all_companies.values()),  # List: [url1, url2, ...]
        "sources_scraped": len(search_results['results'])
    }


async def save_companies_to_file(companies_data: dict, filename: str = "companies.json"):
    """
    Save the companies data to a JSON file
    
    Args:
        companies_data: Dictionary containing company information
        filename: Output filename
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(companies_data, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Saved {companies_data['total_companies_found']} companies to {filename}")
    except Exception as e:
        print(f"Error saving to file: {str(e)}")


async def main():
    """Main function to demonstrate the complete workflow"""
    
    # Search for AI agent companies and scrape them
    query = "startups building AI agents 2024"
    companies_data = await find_companies_from_search(query, max_results=5)
    
    # Display results
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Query: {companies_data['query']}")
    print(f"Sources Scraped: {companies_data['sources_scraped']}")
    print(f"Total Companies Found: {companies_data['total_companies_found']}")
    
    print(f"\n{'='*60}")
    print(f"COMPANY LIST")
    print(f"{'='*60}")
    for i, (name, url) in enumerate(companies_data['companies'].items(), 1):
        print(f"{i}. {name}")
        print(f"   → {url}")
    
    print(f"\n{'='*60}")
    print(f"COMPANY NAMES ONLY")
    print(f"{'='*60}")
    for i, name in enumerate(companies_data['company_names'], 1):
        print(f"{i}. {name}")
    
    print(f"\n{'='*60}")
    print(f"COMPANY URLs ONLY")
    print(f"{'='*60}")
    for i, url in enumerate(companies_data['company_urls'], 1):
        print(f"{i}. {url}")
    
    # Save to file
    await save_companies_to_file(companies_data, "ai_agent_companies.json")


if __name__ == "__main__":
    # Install required package: pip install beautifulsoup4
    asyncio.run(main())