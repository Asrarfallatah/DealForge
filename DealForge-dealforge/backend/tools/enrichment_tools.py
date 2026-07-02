# backend/tools/enrichment_tools.py

import re
import html
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langsmith import traceable

# ============================================================
# EXTERNAL ENRICHMENT TOOLS
# ============================================================


@traceable(name="clean_text", run_type="tool")
def clean_text(text: str) -> str:
    """
    Clean whitespace and repeated spaces.
    """
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.strip()


@traceable(name="is_valid_url", run_type="tool")
def is_valid_url(url: str) -> bool:
    """
    Basic URL validation.
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme in ["http", "https"] and bool(parsed.netloc)
    except Exception:
        return False


@traceable(name="merge_unique_list", run_type="tool")
def merge_unique_list(items: list) -> list:
    """
    Remove duplicates while preserving order.
    """
    clean_items = []

    for item in items:
        if item and item not in clean_items:
            clean_items.append(item)

    return clean_items


# ============================================================
# SEARCH TOOL
# ============================================================


@traceable(name="find_company_website", run_type="tool")
def find_company_website(company_name: str) -> dict:
    """
    Search the web for the official company website.

    This uses DuckDuckGo search through ddgs.
    """

    if not company_name:
        return {
            "success": False,
            "message": "company_name is required.",
        }

    try:
        from ddgs import DDGS
    except ImportError:
        return {
            "success": False,
            "message": "Missing dependency. Run: pip install ddgs",
        }

    query = f"{company_name} official website"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=7))

        if not results:
            return {
                "success": False,
                "message": "No search results found.",
                "company_name": company_name,
            }

        blocked_domains = [
            "linkedin.com",
            "facebook.com",
            "instagram.com",
            "twitter.com",
            "x.com",
            "youtube.com",
            "wikipedia.org",
            "crunchbase.com",
            "glassdoor.com",
            "indeed.com",
        ]

        for item in results:
            url = item.get("href") or item.get("url")

            if not url:
                continue

            domain = urlparse(url).netloc.lower()

            if any(blocked in domain for blocked in blocked_domains):
                continue

            return {
                "success": True,
                "company_name": company_name,
                "website": url,
                "title": item.get("title"),
                "snippet": item.get("body"),
                "source": "DuckDuckGo Search",
            }

        first = results[0]

        return {
            "success": True,
            "company_name": company_name,
            "website": first.get("href") or first.get("url"),
            "title": first.get("title"),
            "snippet": first.get("body"),
            "source": "DuckDuckGo Search",
        }

    except Exception as error:
        return {
            "success": False,
            "message": str(error),
            "company_name": company_name,
        }


# ============================================================
# EXTRACTION HELPERS
# ============================================================


@traceable(name="extract_emails", run_type="tool")
def extract_emails(text: str) -> list[str]:
    """
    Extract clean public email addresses.
    """
    if not text:
        return []

    text = html.unescape(text)
    text = text.replace("\\u003e", " ")
    text = text.replace("\\u003c", " ")
    text = text.replace(">", " ")
    text = text.replace("<", " ")

    emails = re.findall(
        r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b",
        text,
    )

    blocked_patterns = [
        "example.com",
        "domain.com",
        "email.com",
        "test.com",
        "wght@",
        "@100",
        "@200",
        "@300",
        "@400",
        "@500",
        "@600",
        "@700",
        "@800",
        "@900",
    ]

    clean_emails = []

    for email in emails:
        email = email.strip().lower().rstrip(".,;:)")

        if any(pattern in email for pattern in blocked_patterns):
            continue

        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$", email):
            continue

        if email not in clean_emails:
            clean_emails.append(email)

    return clean_emails


@traceable(name="extract_phone_numbers", run_type="tool")
def extract_phone_numbers(text: str) -> list[str]:
    """
    Extract realistic public phone numbers only.
    Avoid SVG/CSS/date/random numeric values.
    """
    if not text:
        return []

    text = html.unescape(text)

    phone_candidates = re.findall(
        r"(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,5}\d{2,4}",
        text,
    )

    phones = []

    for phone in phone_candidates:
        cleaned = clean_text(phone)
        digits_only = re.sub(r"\D", "", cleaned)

        if len(digits_only) < 9 or len(digits_only) > 15:
            continue

        # remove dates like 2024-06-10
        if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
            continue

        # remove SVG coordinate-like values
        if cleaned.count(".") >= 2:
            continue

        if cleaned.count("-") >= 3:
            continue

        # require phone-like signal
        has_phone_signal = (
            cleaned.startswith("+")
            or cleaned.startswith("00")
            or cleaned.startswith("966")
            or cleaned.startswith("05")
            or cleaned.startswith("5")
            or cleaned.startswith("01")
            or cleaned.startswith("02")
            or cleaned.startswith("03")
            or cleaned.startswith("04")
            or cleaned.startswith("07")
        )

        if not has_phone_signal:
            continue

        if cleaned not in phones:
            phones.append(cleaned)

    return phones


@traceable(name="extract_social_links", run_type="tool")
def extract_social_links(soup: BeautifulSoup, page_url: str) -> dict:
    """
    Extract public company social links and contact/career pages.
    """
    social_links = {
        "linkedin": [],
        "twitter_x": [],
        "facebook": [],
        "instagram": [],
        "youtube": [],
        "contact_pages": [],
        "careers_pages": [],
        "email_links": [],
        "phone_links": [],
    }

    for link in soup.find_all("a", href=True):
        href = link.get("href")
        text = clean_text(link.get_text()).lower()

        if not href:
            continue

        lower_href = href.lower()

        if lower_href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if email:
                social_links["email_links"].append(email)
            continue

        if lower_href.startswith("tel:"):
            phone = href.replace("tel:", "").strip()
            if phone:
                social_links["phone_links"].append(phone)
            continue

        full_url = urljoin(page_url, href)
        lower_url = full_url.lower()

        if "linkedin.com" in lower_url:
            social_links["linkedin"].append(full_url)

        elif "twitter.com" in lower_url or "x.com" in lower_url:
            social_links["twitter_x"].append(full_url)

        elif "facebook.com" in lower_url:
            social_links["facebook"].append(full_url)

        elif "instagram.com" in lower_url:
            social_links["instagram"].append(full_url)

        elif "youtube.com" in lower_url or "youtu.be" in lower_url:
            social_links["youtube"].append(full_url)

        if "contact" in lower_url or "contact" in text:
            social_links["contact_pages"].append(full_url)

        if (
            "career" in lower_url
            or "careers" in lower_url
            or "jobs" in lower_url
            or "career" in text
            or "jobs" in text
        ):
            social_links["careers_pages"].append(full_url)

    for key in social_links:
        social_links[key] = merge_unique_list(social_links[key])

    return social_links


@traceable(name="extract_people_candidates", run_type="tool")
def extract_people_candidates(soup: BeautifulSoup, page_url: str = "") -> list[dict]:
    """
    Extract possible public people names only from relevant pages.
    This avoids false positives from homepage marketing text.
    """

    relevant_page_words = [
        "team",
        "leadership",
        "people",
        "management",
        "about",
    ]

    page_url_lower = page_url.lower()

    if not any(word in page_url_lower for word in relevant_page_words):
        return []

    title_keywords = [
        "ceo",
        "cto",
        "cfo",
        "coo",
        "founder",
        "co-founder",
        "director",
        "manager",
        "head of",
        "president",
        "vice president",
        "vp",
        "sales",
        "marketing",
        "business development",
        "operations",
        "chief",
    ]

    blocked_names = [
        "About Us",
        "Contact Us",
        "Privacy Policy",
        "Terms Conditions",
        "Read More",
        "Learn More",
        "Google Analytics",
        "The Google",
        "Privacy Focused",
    ]

    people = []

    possible_blocks = soup.find_all(
        ["div", "section", "article", "li", "p"],
        limit=300,
    )

    for block in possible_blocks:
        text = clean_text(block.get_text(" "))

        if not text:
            continue

        if len(text) < 10 or len(text) > 220:
            continue

        lower_text = text.lower()

        if not any(keyword in lower_text for keyword in title_keywords):
            continue

        names = re.findall(
            r"\b[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,}){1,2}\b",
            text,
        )

        for name in names:
            if name in blocked_names:
                continue

            if any(blocked in name for blocked in blocked_names):
                continue

            person = {
                "name": name,
                "context": text[:220],
            }

            if person not in people:
                people.append(person)

    return people[:10]


# ============================================================
# SCRAPING TOOLS
# ============================================================


@traceable(name="scrape_website_text", run_type="tool")
def scrape_website_text(url: str, max_chars: int = 6000) -> dict:
    """
    Scrape readable text and public contact info from one website page.
    """

    if not url:
        return {
            "success": False,
            "message": "url is required.",
        }

    if not url.startswith("http"):
        url = "https://" + url

    if not is_valid_url(url):
        return {
            "success": False,
            "message": "Invalid URL.",
            "url": url,
        }

    try:
        headers = {"User-Agent": "Mozilla/5.0 (DealForge CRM Agent)"}

        response = requests.get(
            url,
            headers=headers,
            timeout=12,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return {
                "success": False,
                "message": f"Website returned status code {response.status_code}.",
                "url": url,
            }

        soup = BeautifulSoup(response.text, "html.parser")

        social_links = extract_social_links(soup, response.url)
        people_candidates = extract_people_candidates(soup, response.url)

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = clean_text(soup.title.get_text()) if soup.title else None

        meta_description = None
        meta_tag = soup.find("meta", attrs={"name": "description"})

        if meta_tag and meta_tag.get("content"):
            meta_description = clean_text(meta_tag.get("content"))

        headings = [
            clean_text(h.get_text())
            for h in soup.find_all(["h1", "h2", "h3"])
            if clean_text(h.get_text())
        ]

        paragraphs = [
            clean_text(p.get_text())
            for p in soup.find_all("p")
            if clean_text(p.get_text())
        ]

        combined_text = clean_text(" ".join(headings + paragraphs))

        visible_text = soup.get_text(" ")

        emails = extract_emails(visible_text + " " + combined_text)
        phones = extract_phone_numbers(visible_text + " " + combined_text)

        emails.extend(social_links.get("email_links", []))
        phones.extend(social_links.get("phone_links", []))

        emails = merge_unique_list(emails)
        phones = merge_unique_list(phones)

        return {
            "success": True,
            "url": response.url,
            "title": title,
            "meta_description": meta_description,
            "headings": headings[:20],
            "text": combined_text[:max_chars],
            "emails": emails,
            "phone_numbers": phones,
            "social_links": social_links,
            "people_candidates": people_candidates,
        }

    except Exception as error:
        return {
            "success": False,
            "message": str(error),
            "url": url,
        }


@traceable(name="collect_internal_links", run_type="tool")
def collect_internal_links(base_url: str, max_links: int = 10) -> list[str]:
    """
    Collect useful internal links from the company website.
    Prioritizes contact, about, team, services, products, and solutions pages.
    """

    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    try:
        headers = {"User-Agent": "Mozilla/5.0 (DealForge CRM Agent)"}

        response = requests.get(base_url, headers=headers, timeout=12)
        soup = BeautifulSoup(response.text, "html.parser")

        base_domain = urlparse(response.url).netloc

        priority_keywords = [
            "contact",
            "about",
            "team",
            "leadership",
            "people",
            "management",
            "services",
            "solutions",
            "products",
            "pricing",
            "industries",
            "customers",
            "case-studies",
            "what-we-do",
            "company",
        ]

        blocked_extensions = [
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
            ".svg",
            ".webp",
            ".zip",
            ".mp4",
            ".mp3",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
        ]

        links = []

        for link in soup.find_all("a", href=True):
            href = link.get("href")
            full_url = urljoin(response.url, href)
            parsed = urlparse(full_url)

            if parsed.netloc != base_domain:
                continue

            clean_url = full_url.split("#")[0].rstrip("/")

            if any(clean_url.lower().endswith(ext) for ext in blocked_extensions):
                continue

            if clean_url not in links:
                links.append(clean_url)

        def priority_score(url: str):
            url_lower = url.lower()

            for index, keyword in enumerate(priority_keywords):
                if keyword in url_lower:
                    return index

            return 999

        links = sorted(links, key=priority_score)

        homepage = response.url.split("#")[0].rstrip("/")
        final_links = [homepage]

        for link in links:
            if link not in final_links:
                final_links.append(link)

            if len(final_links) >= max_links:
                break

        return final_links

    except Exception:
        return [base_url]


# ============================================================
# MAIN COMPANY ENRICHMENT TOOL
# ============================================================


@traceable(name="scrape_company_website", run_type="tool")
def scrape_company_website(
    company_name: str = None,
    website: str = None,
    max_pages: int = 10,
) -> dict:
    """
    Main external enrichment tool.

    It can:
    - search for the official company website
    - crawl useful internal pages
    - extract public emails
    - extract public phone numbers
    - extract social/contact links
    - extract possible public people names and titles
    """

    if not company_name and not website:
        return {
            "success": False,
            "message": "company_name or website is required.",
        }

    search_result = None

    if not website:
        search_result = find_company_website(company_name)

        if not search_result.get("success"):
            return search_result

        website = search_result.get("website")

    links = collect_internal_links(
        base_url=website,
        max_links=max_pages,
    )

    scraped_pages = []
    collected_text_parts = []

    all_emails = []
    all_phones = []
    all_people = []

    all_social_links = {
        "linkedin": [],
        "twitter_x": [],
        "facebook": [],
        "instagram": [],
        "youtube": [],
        "contact_pages": [],
        "careers_pages": [],
        "email_links": [],
        "phone_links": [],
    }

    for link in links:
        page_result = scrape_website_text(link)

        scraped_pages.append(
            {
                "url": link,
                "success": page_result.get("success"),
                "title": page_result.get("title"),
                "meta_description": page_result.get("meta_description"),
            }
        )

        if not page_result.get("success"):
            continue

        collected_text_parts.append(page_result.get("meta_description") or "")
        collected_text_parts.append(page_result.get("text") or "")

        all_emails.extend(page_result.get("emails", []))
        all_phones.extend(page_result.get("phone_numbers", []))
        all_people.extend(page_result.get("people_candidates", []))

        page_socials = page_result.get("social_links", {})

        for key in all_social_links:
            all_social_links[key].extend(page_socials.get(key, []))

    collected_text = clean_text(" ".join(part for part in collected_text_parts if part))

    all_emails = merge_unique_list(all_emails)
    all_phones = merge_unique_list(all_phones)

    unique_people = []
    seen_people = set()

    for person in all_people:
        name = person.get("name")

        if not name:
            continue

        if name not in seen_people:
            unique_people.append(person)
            seen_people.add(name)

    for key in all_social_links:
        all_social_links[key] = merge_unique_list(all_social_links[key])

    if not collected_text and not all_emails and not all_phones:
        return {
            "success": False,
            "message": "Website was found, but no useful text or contact info could be scraped.",
            "company_name": company_name,
            "website": website,
            "pages_checked": scraped_pages,
        }

    return {
        "success": True,
        "company_name": company_name,
        "website": website,
        "search_result": search_result,
        "pages_scraped_count": len(scraped_pages),
        "pages_scraped": scraped_pages,
        "company_profile": {
            "scraped_text": collected_text[:15000],
            "source": website,
        },
        "contact_info": {
            "emails": all_emails,
            "phone_numbers": all_phones,
            "social_links": all_social_links,
            "people_candidates": unique_people[:20],
        },
    }
