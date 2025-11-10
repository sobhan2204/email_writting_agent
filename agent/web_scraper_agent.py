"""
Advanced Company Email Scraper
More aggressive scraping with multiple strategies
"""

import asyncio
import httpx
import re
import json
from bs4 import BeautifulSoup
from typing import List, Dict, Set
from urllib.parse import urljoin, urlparse

# Import from company_finder_agent
from company_finder_agent import find_companies_from_search


class EmailScraper:
    def __init__(self):
        self.visited_urls = set()
        self.max_pages_per_site = 10
        
    async def find_all_internal_links(self, url: str, soup: BeautifulSoup) -> Set[str]:
        """Find all internal links on a page"""
        base_domain = urlparse(url).netloc
        internal_links = set()
        
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            full_url = urljoin(url, href)
            
            # Only include links from the same domain
            if urlparse(full_url).netloc == base_domain:
                # Remove fragments and queries for cleaner URLs
                clean_url = full_url.split('#')[0].split('?')[0]
                internal_links.add(clean_url)
        
        return internal_links
    
    async def extract_emails_from_text(self, text: str) -> Set[str]:
        """Extract all email addresses from text with much more robust regex"""
        
        # First, let's normalize the text a bit
        text = text.replace('\n', ' ').replace('\r', ' ')
        
        # Primary comprehensive email regex - captures full emails only
        # This pattern ensures we capture the COMPLETE email with @ symbol
        email_pattern = r'(?:[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-zA-Z0-9-]*[a-zA-Z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])'
        
        raw_emails = re.findall(email_pattern, text, re.IGNORECASE)
        
        clean_emails = set()
        for email in raw_emails:
            email = email.strip().lower()
            
            # Must contain @ symbol
            if '@' not in email:
                continue
            
            # Basic length validation
            if len(email) < 6 or len(email) > 254:  # RFC 5321
                continue
            
            # Split and validate parts
            try:
                local, domain = email.split('@', 1)
            except:
                continue
            
            # Local part validation
            if len(local) < 1 or len(local) > 64:
                continue
            
            # Domain validation - must have at least one dot and valid TLD
            if '.' not in domain:
                continue
            
            domain_parts = domain.split('.')
            if len(domain_parts) < 2:
                continue
            
            # TLD should be at least 2 chars
            tld = domain_parts[-1]
            if len(tld) < 2:
                continue
            
            # Skip placeholder/test domains
            exclude_domains = [
                'example.com', 'test.com', 'domain.com', 'email.com',
                'yourcompany', 'company.com', 'youremail', 'placeholder',
                'sampleemail', 'wixpress.com', 'sentry.io', 'w3.org', 
                'schema.org', 'xmlns.com', 'xmlsoap.org'
            ]
            
            if any(ex_domain in email for ex_domain in exclude_domains):
                continue
            
            # Skip no-reply addresses
            if email.startswith('noreply') or email.startswith('no-reply') or email.startswith('donotreply'):
                continue
            
            # Final check: must look like a real email
            if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$', email):
                clean_emails.add(email)
        
        return clean_emails
    
    async def prioritize_urls(self, urls: Set[str]) -> List[str]:
        """Prioritize URLs based on likelihood of containing contact info"""
        priority_keywords = [
            'contact', 'career', 'careers', 'jobs', 'join', 'team',
            'about', 'hiring', 'recruit', 'work', 'opportunity',
            'hr', 'human-resources', 'employment', 'apply'
        ]
        
        priority_urls = []
        other_urls = []
        
        for url in urls:
            url_lower = url.lower()
            if any(keyword in url_lower for keyword in priority_keywords):
                priority_urls.append(url)
            else:
                other_urls.append(url)
        
        # Return priority URLs first, then others
        return priority_urls + other_urls
    
    async def scrape_single_page(self, url: str, client: httpx.AsyncClient) -> tuple:
        """Scrape a single page for emails and links"""
        emails = set()
        links = set()
        
        try:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
            html_content = response.text
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Decode HTML entities first
            import html
            decoded_html = html.unescape(html_content)
            
            # Method 1: Extract from decoded HTML directly (catches encoded emails)
            emails.update(await self.extract_emails_from_text(decoded_html))
            
            # Method 2: Extract emails from visible page text
            page_text = soup.get_text(separator=' ', strip=True)
            emails.update(await self.extract_emails_from_text(page_text))
            
            # Method 3: Extract emails from mailto links
            for mailto in soup.find_all('a', href=True):
                href = mailto.get('href', '')
                if 'mailto:' in href.lower():
                    # Clean mailto link
                    email = href.lower().replace('mailto:', '').split('?')[0].split('&')[0]
                    extracted = await self.extract_emails_from_text(email)
                    emails.update(extracted)
            
            # Method 4: Extract from data attributes (sometimes emails hidden there)
            for elem in soup.find_all(attrs={'data-email': True}):
                email_data = elem.get('data-email', '')
                extracted = await self.extract_emails_from_text(email_data)
                emails.update(extracted)
            
            # Method 5: Search in script tags (JavaScript contact forms)
            for script in soup.find_all('script'):
                script_text = script.string if script.string else ''
                if '@' in script_text:
                    # Decode any JavaScript string encoding
                    script_text = script_text.replace('\\u0040', '@')
                    script_text = script_text.replace('\\x40', '@')
                    extracted = await self.extract_emails_from_text(script_text)
                    emails.update(extracted)
            
            # Method 6: Search in meta tags
            for meta in soup.find_all('meta'):
                content = meta.get('content', '')
                if '@' in content:
                    extracted = await self.extract_emails_from_text(content)
                    emails.update(extracted)
            
            # Method 7: Handle obfuscated emails (e.g., "info [at] company [dot] com")
            obfuscated_patterns = [
                r'([a-zA-Z0-9._-]+)\s*(?:\[at\]|\(at\))\s*([a-zA-Z0-9.-]+)\s*(?:\[dot\]|\(dot\))\s*([a-zA-Z]{2,})',
                r'([a-zA-Z0-9._-]+)\s*\[?\(?at\)?\]?\s*([a-zA-Z0-9.-]+)\s*\[?\(?dot\)?\]?\s*([a-zA-Z]{2,})'
            ]
            
            for pattern in obfuscated_patterns:
                matches = re.findall(pattern, decoded_html, re.IGNORECASE)
                for local, domain, tld in matches:
                    email = f"{local.strip()}@{domain.strip()}.{tld.strip()}"
                    extracted = await self.extract_emails_from_text(email)
                    emails.update(extracted)
            
            # Get internal links
            links = await self.find_all_internal_links(url, soup)
            
        except Exception as e:
            print(f"      ⚠️  Error on {url}: {str(e)[:50]}")
        
        return emails, links
    
    async def scrape_website_deep(self, url: str, company_name: str = None) -> dict:
        """
        Deep scrape a website for emails by crawling multiple pages
        
        Args:
            url: Company website URL
            company_name: Name of the company (optional)
        
        Returns:
            dict: Contains company name, URL, and found emails
        """
        print(f"\n🔍 Deep scraping: {company_name or url}")
        
        self.visited_urls = set()
        all_emails = set()
        to_visit = {url}
        pages_scraped = 0
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
            while to_visit and pages_scraped < self.max_pages_per_site:
                # Prioritize URLs
                prioritized = await self.prioritize_urls(to_visit)
                current_url = prioritized[0]
                to_visit.remove(current_url)
                
                if current_url in self.visited_urls:
                    continue
                
                self.visited_urls.add(current_url)
                pages_scraped += 1
                
                print(f"   [{pages_scraped}/{self.max_pages_per_site}] Checking: {current_url.split('/')[-1] or 'home'}")
                
                emails, links = await self.scrape_single_page(current_url, client)
                all_emails.update(emails)
                
                # Add new links to visit
                new_links = links - self.visited_urls - to_visit
                to_visit.update(new_links)
                
                # If we found emails on priority pages, we can be less aggressive
                if emails and pages_scraped >= 5:
                    break
        
        # Filter for career/HR related emails first
        career_keywords = ['career', 'careers', 'job', 'jobs', 'recruit', 'hr', 'human', 'talent', 'hiring']
        career_emails = {email for email in all_emails if any(kw in email.lower() for kw in career_keywords)}
        
        # If no career emails, use contact emails
        if not career_emails:
            contact_keywords = ['contact', 'info', 'hello', 'support', 'help']
            career_emails = {email for email in all_emails if any(kw in email.lower() for kw in contact_keywords)}
        
        # If still nothing, return all emails found
        final_emails = list(career_emails) if career_emails else list(all_emails)
        
        if final_emails:
            print(f"   ✅ Found {len(final_emails)} email(s): {', '.join(final_emails)}")
        else:
            print(f"   ❌ No emails found after checking {pages_scraped} pages")
        
        return {
            "company_name": company_name or urlparse(url).netloc,
            "url": url,
            "emails": final_emails,
            "pages_scraped": pages_scraped
        }


async def scrape_emails_from_companies(companies_data: dict, max_pages: int = 10) -> dict:
    """
    Scrape emails from all companies using deep scraping
    
    Args:
        companies_data: Output from find_companies_from_search()
        max_pages: Maximum pages to scrape per website
    
    Returns:
        dict: Contains all emails and company-email mapping
    """
    print(f"\n{'='*70}")
    print(f"STARTING DEEP EMAIL SCRAPING FOR {companies_data['total_companies_found']} COMPANIES")
    print(f"{'='*70}")
    
    scraper = EmailScraper()
    scraper.max_pages_per_site = max_pages
    
    company_emails = {}  # {company_name: [emails]}
    all_emails = []  # List of all emails
    
    companies = companies_data['companies']
    
    for i, (company_name, company_url) in enumerate(companies.items(), 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(companies)}] {company_name}")
        print(f"{'='*70}")
        
        result = await scraper.scrape_website_deep(company_url, company_name)
        
        if result['emails']:
            company_emails[company_name] = result['emails']
            all_emails.extend(result['emails'])
        else:
            company_emails[company_name] = []
        
        # Small delay to be respectful
        await asyncio.sleep(1)
    
    return {
        "total_companies_scraped": len(companies),
        "companies_with_emails": len([c for c in company_emails.values() if c]),
        "total_emails_found": len(all_emails),
        "company_emails": company_emails,  # Dict: {company_name: [email1, email2]}
        "all_emails": all_emails  # List: [email1, email2, email3, ...]
    }


async def scrape_emails_from_url_list(company_urls: List[str], max_pages: int = 10) -> dict:
    """
    Scrape emails from a list of company URLs using deep scraping
    
    Args:
        company_urls: List of company website URLs
        max_pages: Maximum pages to scrape per website
    
    Returns:
        dict: Contains all emails found
    """
    print(f"\n{'='*70}")
    print(f"STARTING DEEP EMAIL SCRAPING FOR {len(company_urls)} URLs")
    print(f"{'='*70}")
    
    scraper = EmailScraper()
    scraper.max_pages_per_site = max_pages
    
    all_emails = []
    url_emails = {}  # {url: [emails]}
    
    for i, url in enumerate(company_urls, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(company_urls)}] Processing")
        print(f"{'='*70}")
        
        result = await scraper.scrape_website_deep(url)
        
        if result['emails']:
            url_emails[url] = result['emails']
            all_emails.extend(result['emails'])
        else:
            url_emails[url] = []
        
        await asyncio.sleep(1)
    
    return {
        "total_urls_scraped": len(company_urls),
        "urls_with_emails": len([e for e in url_emails.values() if e]),
        "total_emails_found": len(all_emails),
        "url_emails": url_emails,  # Dict: {url: [email1, email2]}
        "all_emails": all_emails  # List: [email1, email2, email3, ...]
    }


async def save_emails_to_file(emails_data: dict, filename: str = "company_emails.json"):
    """Save the emails data to a JSON file"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(emails_data, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Saved email data to {filename}")
    except Exception as e:
        print(f"❌ Error saving to file: {str(e)}")


async def main():
    """Main function demonstrating the complete workflow"""
    
    # Step 1: Find companies
    print("STEP 1: Finding AI Agent Companies...")
    companies_data = await find_companies_from_search("AI agent startups 2024", max_results=3)
    
    # Step 2: Deep scrape emails from all companies (10 pages per site)
    print("\n\nSTEP 2: Deep Scraping Emails from Companies...")
    emails_data = await scrape_emails_from_companies(companies_data, max_pages=10)
    
    # Display results
    print(f"\n\n{'='*70}")
    print(f"📊 EMAIL SCRAPING RESULTS")
    print(f"{'='*70}")
    print(f"Total Companies Scraped: {emails_data['total_companies_scraped']}")
    print(f"Companies with Emails Found: {emails_data['companies_with_emails']}")
    print(f"Total Emails Found: {emails_data['total_emails_found']}")
    
    print(f"\n{'='*70}")
    print(f"📧 COMPANY EMAILS")
    print(f"{'='*70}")
    for company, emails in emails_data['company_emails'].items():
        if emails:
            print(f"\n✅ {company}:")
            for email in emails:
                print(f"   • {email}")
        else:
            print(f"\n❌ {company}: No emails found")
    
    print(f"\n{'='*70}")
    print(f"📋 ALL EMAILS LIST")
    print(f"{'='*70}")
    for i, email in enumerate(emails_data['all_emails'], 1):
        print(f"{i}. {email}")
    
    # Save to file
    await save_emails_to_file(emails_data, "company_emails.json")
    
    print("\n✅ Email scraping complete!")


if __name__ == "__main__":
    asyncio.run(main())
    
async def prioritize_urls(self, urls: Set[str]) -> List[str]:
        """Prioritize URLs based on likelihood of containing contact info"""
        priority_keywords = [
            'contact', 'career', 'careers', 'jobs', 'join', 'team',
            'about', 'hiring', 'recruit', 'work', 'opportunity',
            'hr', 'human-resources', 'employment', 'apply'
        ]
        
        priority_urls = []
        other_urls = []
        
        for url in urls:
            url_lower = url.lower()
            if any(keyword in url_lower for keyword in priority_keywords):
                priority_urls.append(url)
            else:
                other_urls.append(url)
        
        # Return priority URLs first, then others
        return priority_urls + other_urls
    
async def scrape_single_page(self, url: str, client: httpx.AsyncClient) -> tuple:
        """Scrape a single page for emails and links"""
        emails = set()
        links = set()
        
        try:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
            html_content = response.text
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Method 1: Extract emails from visible page text
            page_text = soup.get_text(separator=' ', strip=True)
            emails.update(await self.extract_emails_from_text(page_text))
            
            # Method 2: Extract emails from mailto links
            for mailto in soup.find_all('a', href=True):
                href = mailto.get('href', '')
                if href.startswith('mailto:'):
                    email = href.replace('mailto:', '').split('?')[0].split('&')[0]
                    extracted = await self.extract_emails_from_text(email)
                    emails.update(extracted)
            
            # Method 3: Extract from all href attributes (sometimes emails are in hrefs)
            for link in soup.find_all(['a', 'link'], href=True):
                href = link.get('href', '')
                if '@' in href:
                    extracted = await self.extract_emails_from_text(href)
                    emails.update(extracted)
            
            # Method 4: Search in script tags (sometimes contact info in JS)
            for script in soup.find_all('script'):
                script_text = script.string
                if script_text and '@' in script_text:
                    extracted = await self.extract_emails_from_text(script_text)
                    emails.update(extracted)
            
            # Method 5: Search in meta tags
            for meta in soup.find_all('meta'):
                content = meta.get('content', '')
                if '@' in content:
                    extracted = await self.extract_emails_from_text(content)
                    emails.update(extracted)
            
            # Method 6: Search the raw HTML for obfuscated emails
            # Sometimes emails are written as "info [at] company [dot] com"
            obfuscated_pattern = r'([a-zA-Z0-9._-]+)\s*(?:\[at\]|@|\(at\))\s*([a-zA-Z0-9.-]+)\s*(?:\[dot\]|\.|\.|\(dot\))\s*([a-zA-Z]{2,})'
            obfuscated = re.findall(obfuscated_pattern, html_content, re.IGNORECASE)
            for local, domain, tld in obfuscated:
                email = f"{local.strip()}@{domain.strip()}.{tld.strip()}"
                extracted = await self.extract_emails_from_text(email)
                emails.update(extracted)
            
            # Get internal links
            links = await self.find_all_internal_links(url, soup)
            
        except Exception as e:
            print(f"      ⚠️  Error on {url}: {str(e)[:50]}")
        
        return emails, links
    
async def scrape_website_deep(self, url: str, company_name: str = None) -> dict:
        """
        Deep scrape a website for emails by crawling multiple pages
        
        Args:
            url: Company website URL
            company_name: Name of the company (optional)
        
        Returns:
            dict: Contains company name, URL, and found emails
        """
        print(f"\n🔍 Deep scraping: {company_name or url}")
        
        self.visited_urls = set()
        all_emails = set()
        to_visit = {url}
        pages_scraped = 0
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
            while to_visit and pages_scraped < self.max_pages_per_site:
                # Prioritize URLs
                prioritized = await self.prioritize_urls(to_visit)
                current_url = prioritized[0]
                to_visit.remove(current_url)
                
                if current_url in self.visited_urls:
                    continue
                
                self.visited_urls.add(current_url)
                pages_scraped += 1
                
                print(f"   [{pages_scraped}/{self.max_pages_per_site}] Checking: {current_url.split('/')[-1] or 'home'}")
                
                emails, links = await self.scrape_single_page(current_url, client)
                all_emails.update(emails)
                
                # Add new links to visit
                new_links = links - self.visited_urls - to_visit
                to_visit.update(new_links)
                
                # If we found emails on priority pages, we can be less aggressive
                if emails and pages_scraped >= 5:
                    break
        
        # Filter for career/HR related emails first
        career_keywords = ['career', 'careers', 'job', 'jobs', 'recruit', 'hr', 'human', 'talent', 'hiring']
        career_emails = {email for email in all_emails if any(kw in email.lower() for kw in career_keywords)}
        
        # If no career emails, use contact emails
        if not career_emails:
            contact_keywords = ['contact', 'info', 'hello', 'support', 'help']
            career_emails = {email for email in all_emails if any(kw in email.lower() for kw in contact_keywords)}
        
        # If still nothing, return all emails found
        final_emails = list(career_emails) if career_emails else list(all_emails)
        
        if final_emails:
            print(f"   ✅ Found {len(final_emails)} email(s): {', '.join(final_emails)}")
        else:
            print(f"   ❌ No emails found after checking {pages_scraped} pages")
        
        return {
            "company_name": company_name or urlparse(url).netloc,
            "url": url,
            "emails": final_emails,
            "pages_scraped": pages_scraped
        }


async def scrape_emails_from_companies(companies_data: dict, max_pages: int = 10) -> dict:
    """
    Scrape emails from all companies using deep scraping
    
    Args:
        companies_data: Output from find_companies_from_search()
        max_pages: Maximum pages to scrape per website
    
    Returns:
        dict: Contains all emails and company-email mapping
    """
    print(f"\n{'='*70}")
    print(f"STARTING DEEP EMAIL SCRAPING FOR {companies_data['total_companies_found']} COMPANIES")
    print(f"{'='*70}")
    
    scraper = EmailScraper()
    scraper.max_pages_per_site = max_pages
    
    company_emails = {}  # {company_name: [emails]}
    all_emails = []  # List of all emails
    
    companies = companies_data['companies']
    
    for i, (company_name, company_url) in enumerate(companies.items(), 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(companies)}] {company_name}")
        print(f"{'='*70}")
        
        result = await scraper.scrape_website_deep(company_url, company_name)
        
        if result['emails']:
            company_emails[company_name] = result['emails']
            all_emails.extend(result['emails'])
        else:
            company_emails[company_name] = []
        
        # Small delay to be respectful
        await asyncio.sleep(1)
    
    return {
        "total_companies_scraped": len(companies),
        "companies_with_emails": len([c for c in company_emails.values() if c]),
        "total_emails_found": len(all_emails),
        "company_emails": company_emails,  # Dict: {company_name: [email1, email2]}
        "all_emails": all_emails  # List: [email1, email2, email3, ...]
    }


async def scrape_emails_from_url_list(company_urls: List[str], max_pages: int = 10) -> dict:
    """
    Scrape emails from a list of company URLs using deep scraping
    
    Args:
        company_urls: List of company website URLs
        max_pages: Maximum pages to scrape per website
    
    Returns:
        dict: Contains all emails found
    """
    print(f"\n{'='*70}")
    print(f"STARTING DEEP EMAIL SCRAPING FOR {len(company_urls)} URLs")
    print(f"{'='*70}")
    
    scraper = EmailScraper()
    scraper.max_pages_per_site = max_pages
    
    all_emails = []
    url_emails = {}  # {url: [emails]}
    
    for i, url in enumerate(company_urls, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(company_urls)}] Processing")
        print(f"{'='*70}")
        
        result = await scraper.scrape_website_deep(url)
        
        if result['emails']:
            url_emails[url] = result['emails']
            all_emails.extend(result['emails'])
        else:
            url_emails[url] = []
        
        await asyncio.sleep(1)
    
    return {
        "total_urls_scraped": len(company_urls),
        "urls_with_emails": len([e for e in url_emails.values() if e]),
        "total_emails_found": len(all_emails),
        "url_emails": url_emails,  # Dict: {url: [email1, email2]}
        "all_emails": all_emails  # List: [email1, email2, email3, ...]
    }


async def save_emails_to_file(emails_data: dict, filename: str = "company_emails.json"):
    """Save the emails data to a JSON file"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(emails_data, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Saved email data to {filename}")
    except Exception as e:
        print(f"❌ Error saving to file: {str(e)}")


async def main():
    """Main function demonstrating the complete workflow"""
    
    # Step 1: Find companies
    print("STEP 1: Finding AI Agent Companies...")
    companies_data = await find_companies_from_search("AI agent startups 2024", max_results=3)
    
    # Step 2: Deep scrape emails from all companies (10 pages per site)
    print("\n\nSTEP 2: Deep Scraping Emails from Companies...")
    emails_data = await scrape_emails_from_companies(companies_data, max_pages=10)
    
    # Display results
    print(f"\n\n{'='*70}")
    print(f"📊 EMAIL SCRAPING RESULTS")
    print(f"{'='*70}")
    print(f"Total Companies Scraped: {emails_data['total_companies_scraped']}")
    print(f"Companies with Emails Found: {emails_data['companies_with_emails']}")
    print(f"Total Emails Found: {emails_data['total_emails_found']}")
    
    print(f"\n{'='*70}")
    print(f"📧 COMPANY EMAILS")
    print(f"{'='*70}")
    for company, emails in emails_data['company_emails'].items():
        if emails:
            print(f"\n✅ {company}:")
            for email in emails:
                print(f"   • {email}")
        else:
            print(f"\n❌ {company}: No emails found")
    
    print(f"\n{'='*70}")
    print(f"📋 ALL EMAILS LIST")
    print(f"{'='*70}")
    for i, email in enumerate(emails_data['all_emails'], 1):
        print(f"{i}. {email}")
    
    # Save to file
    await save_emails_to_file(emails_data, "company_emails.json")
    
    print("\n✅ Email scraping complete!")


if __name__ == "__main__":
    asyncio.run(main())