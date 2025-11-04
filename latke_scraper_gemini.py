#!/usr/bin/env python3
"""
============================================================
JEWISH LATKE CORPUS BUILDER - GEMINI LLM VERSION
============================================================
Uses Google Gemini AI to parse messy OCR text from historical sources
Modern sites still use fast JSON-LD parsing

Setup:
1. pip install google-generativeai requests beautifulsoup4 pandas
2. Get free API key: https://aistudio.google.com/app/apikey
3. Set GEMINI_API_KEY environment variable or edit config below

Features:
- Google Gemini 1.5 Flash for OCR text parsing
- Rate limiting (15 req/min free tier)
- Proper validation
- Resume capability
- Modern sites use fast JSON-LD (no LLM needed)
============================================================
"""

import os
import re
import time
import json
import csv
import pickle
import hashlib
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Google Gemini
import google.generativeai as genai

# ========== Configuration ==========

# GET YOUR FREE API KEY: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

# Output files
OUT_CSV = "jewish_latke_corpus_gemini.csv"
CHECKPOINT_FILE = "latke_corpus_checkpoint_gemini.pkl"
PROGRESS_FILE = "latke_corpus_progress_gemini.json"

# Rate limiting for Gemini free tier
GEMINI_RPM_LIMIT = 15  # Requests per minute (free tier)
GEMINI_DAILY_LIMIT = 1500  # Requests per day (free tier)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('latke_corpus_gemini.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== Gemini Setup ==========

if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
    logger.warning("⚠️  Please set your GEMINI_API_KEY in the script or environment!")
    logger.warning("Get free key at: https://aistudio.google.com/app/apikey")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✓ Gemini API configured")

# Rate limiter for Gemini API
class RateLimiter:
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.requests = []
        self.daily_count = 0

    def wait_if_needed(self):
        """Wait if we're hitting rate limits"""
        now = time.time()

        # Remove requests older than 1 minute
        self.requests = [req_time for req_time in self.requests if now - req_time < 60]

        # If we've hit the per-minute limit, wait
        if len(self.requests) >= self.requests_per_minute:
            sleep_time = 60 - (now - self.requests[0]) + 1
            if sleep_time > 0:
                logger.info(f"⏳ Rate limit: waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                self.requests = []

        # Track the request
        self.requests.append(time.time())
        self.daily_count += 1

        # Warn if approaching daily limit
        if self.daily_count >= GEMINI_DAILY_LIMIT * 0.9:
            logger.warning(f"⚠️  Approaching daily limit: {self.daily_count}/{GEMINI_DAILY_LIMIT}")

gemini_limiter = RateLimiter(GEMINI_RPM_LIMIT)

# ========== Progress Management ==========

class ProgressTracker:
    """Track progress and enable resume capability"""

    def __init__(self, checkpoint_file=CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        self.processed_sources = defaultdict(set)
        self.recipes_by_source = defaultdict(int)
        self.total_recipes = 0
        self.start_time = time.time()
        self.last_checkpoint = time.time()
        self.load()

    def load(self):
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'rb') as f:
                    data = pickle.load(f)
                    self.processed_sources = data.get('processed_sources', defaultdict(set))
                    self.recipes_by_source = data.get('recipes_by_source', defaultdict(int))
                    self.total_recipes = data.get('total_recipes', 0)
                logger.info(f"📂 Loaded checkpoint: {self.total_recipes} recipes already processed")
            except Exception as e:
                logger.warning(f"Could not load checkpoint: {e}")

    def save(self):
        try:
            data = {
                'processed_sources': dict(self.processed_sources),
                'recipes_by_source': dict(self.recipes_by_source),
                'total_recipes': self.total_recipes,
                'timestamp': datetime.now().isoformat()
            }
            with open(self.checkpoint_file, 'wb') as f:
                pickle.dump(data, f)

            with open(PROGRESS_FILE, 'w') as f:
                json.dump({
                    'total_recipes': self.total_recipes,
                    'by_source': dict(self.recipes_by_source),
                    'timestamp': data['timestamp'],
                    'runtime_minutes': (time.time() - self.start_time) / 60,
                    'gemini_calls': gemini_limiter.daily_count
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save checkpoint: {e}")

    def is_processed(self, source_type: str, identifier: str) -> bool:
        return identifier in self.processed_sources[source_type]

    def mark_processed(self, source_type: str, identifier: str, recipe_count: int = 0):
        self.processed_sources[source_type].add(identifier)
        if recipe_count > 0:
            self.recipes_by_source[source_type] += recipe_count
            self.total_recipes += recipe_count

        if time.time() - self.last_checkpoint > 300:
            self.save()
            self.last_checkpoint = time.time()

    def get_stats(self) -> Dict:
        return {
            'total_recipes': self.total_recipes,
            'by_source': dict(self.recipes_by_source),
            'runtime_minutes': (time.time() - self.start_time) / 60,
            'gemini_calls': gemini_limiter.daily_count
        }

progress = ProgressTracker()

# ========== Utilities ==========

def fetch(url: str, timeout: int = 30, retries: int = 3) -> Optional[requests.Response]:
    """Fetch URL with retries"""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.debug(f"Failed to fetch {url}: {e}")
    return None

def clean_text(text: str) -> str:
    """Clean text"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()

def extract_year(text: str) -> Optional[int]:
    """Extract year from text"""
    if not text:
        return None
    years = re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', str(text))
    valid_years = [int(y) for y in years if 1890 <= int(y) <= 2025]
    return max(valid_years) if valid_years else None

def generate_recipe_hash(ingredients: str, instructions: str) -> str:
    """Generate hash for deduplication"""
    content = f"{clean_text(ingredients or '')}{clean_text(instructions or '')}"
    return hashlib.md5(content.encode()).hexdigest()

# ========== LLM-Based Recipe Extraction ==========

def extract_recipes_with_gemini(ocr_text: str, source_title: str = "", max_chars: int = 15000) -> List[Dict]:
    """
    Use Gemini to extract latke recipes from OCR text

    Args:
        ocr_text: Raw OCR text from historical source
        source_title: Title of the source book/document
        max_chars: Maximum characters to send (Gemini has limits)

    Returns:
        List of recipe dictionaries
    """

    # Truncate if too long (keep middle section where recipes likely are)
    if len(ocr_text) > max_chars:
        # Look for "latke" mentions and extract around them
        latke_positions = [m.start() for m in re.finditer(r'\blatke|potato pancake\b', ocr_text, re.I)]

        if latke_positions:
            # Take text around first latke mention
            start = max(0, latke_positions[0] - max_chars // 2)
            end = min(len(ocr_text), latke_positions[0] + max_chars // 2)
            ocr_text = ocr_text[start:end]
        else:
            # Just take first chunk
            ocr_text = ocr_text[:max_chars]

    # Prepare prompt
    prompt = f"""You are a recipe extraction expert. Extract ALL latke (potato pancake) recipes from the following OCR text from a historical cookbook.

Source: {source_title}

For each latke recipe found, extract:
1. Recipe title/name
2. Ingredients list (each ingredient as a separate item)
3. Instructions/directions (step by step)

Return ONLY valid JSON in this exact format:
{{
  "recipes": [
    {{
      "title": "Recipe name here",
      "ingredients": ["ingredient 1", "ingredient 2", ...],
      "instructions": ["step 1", "step 2", ...]
    }}
  ]
}}

Important rules:
- Only extract recipes for LATKES or POTATO PANCAKES (not other potato dishes)
- Skip recipes that are clearly NOT latkes (e.g., potato soup, mashed potatoes)
- If no latke recipes found, return: {{"recipes": []}}
- Keep ingredients and instructions as they appear in the text
- Do NOT make up or invent recipes
- Return ONLY the JSON, no other text

OCR Text:
{ocr_text}

JSON Response:"""

    try:
        # Rate limiting
        gemini_limiter.wait_if_needed()

        # Call Gemini API
        # Use 'gemini-pro' for stability (or try 'gemini-1.5-flash-latest' if available)
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,  # Low temperature for consistent output
                max_output_tokens=2048,
            )
        )

        # Parse response
        response_text = response.text.strip()

        # Try to extract JSON from response (sometimes LLM adds markdown)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(0)

        data = json.loads(response_text)
        recipes = data.get('recipes', [])

        logger.info(f"  Gemini found {len(recipes)} recipes")

        return recipes

    except json.JSONDecodeError as e:
        logger.error(f"Gemini returned invalid JSON: {e}")
        logger.debug(f"Response was: {response_text[:500]}")
        return []

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return []

def validate_recipe_data(recipe: Dict) -> Tuple[bool, str]:
    """
    Validate that recipe data looks correct (not garbage)

    Returns:
        (is_valid, reason)
    """

    title = recipe.get('title', '')
    ingredients = recipe.get('ingredients_raw', '')
    instructions = recipe.get('instructions_raw', '')

    # Check title
    if not title or len(title) < 5:
        return False, "Title too short"

    if len(title) > 200:
        return False, "Title too long (likely book title)"

    # Title shouldn't contain OCR garbage indicators
    garbage_patterns = [
        r'CORNELL UNIVERSITY',
        r'TABLE OF CONTENTS',
        r'FOREWORD',
        r'Gift of ',
        r'http://',
        r'cornell\.edu',
        r'being a manuscript',
    ]

    if any(re.search(pattern, title, re.I) for pattern in garbage_patterns):
        return False, "Title contains book metadata"

    # Check that ingredients/instructions don't have measurement words in wrong fields
    # (This catches when entire book is dumped into instructions)
    if len(instructions or '') > 5000:
        return False, "Instructions too long (likely entire book)"

    # Must have at least some content
    if not ingredients and not instructions:
        return False, "No ingredients or instructions"

    if len(ingredients or '') < 20 and len(instructions or '') < 30:
        return False, "Content too short"

    # Check that ingredients looks like ingredients (has measurements or food words)
    if ingredients:
        has_measurements = bool(re.search(r'\d+.*(?:cup|tablespoon|teaspoon|pound|egg|potato)',
                                         ingredients, re.I))
        if not has_measurements and len(ingredients) > 50:
            return False, "Ingredients don't look like ingredients"

    return True, "OK"

# ========== Internet Archive (GEMINI-POWERED) ==========

def ia_search_comprehensive() -> List[Dict]:
    """Search Internet Archive for Jewish cookbooks"""
    all_items = []

    queries = [
        'subject:"Jewish cookery" AND mediatype:texts AND language:eng',
        'title:(jewish cookbook) AND mediatype:texts AND year:[1890 TO 1960]',
        '(latke OR latkes) AND mediatype:texts',
        'fulltext:(potato latke) AND mediatype:texts',
        'subject:(kosher) AND cookbook AND mediatype:texts',
        'title:(settlement cookbook) AND mediatype:texts',
        'creator:("Aunt Babette") AND mediatype:texts',
    ]

    for query in queries:
        logger.info(f"IA Query: {query[:60]}...")

        for page in range(1, 6):  # Limit to 5 pages per query
            try:
                url = "https://archive.org/advancedsearch.php"
                params = {
                    "q": query,
                    "fl[]": ["identifier", "title", "creator", "date", "year", "publisher"],
                    "rows": 50,
                    "page": page,
                    "output": "json",
                    "sort[]": "year asc"
                }

                r = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=30)
                r.raise_for_status()
                data = r.json()
                docs = data.get("response", {}).get("docs", [])

                if not docs:
                    break

                all_items.extend(docs)
                time.sleep(1.5)

            except Exception as e:
                logger.error(f"IA search error: {e}")
                break

    # Deduplicate
    seen = set()
    unique_items = []
    for item in all_items:
        ident = item.get("identifier")
        if ident and ident not in seen:
            seen.add(ident)
            unique_items.append(item)

    logger.info(f"Found {len(unique_items)} unique Internet Archive items")
    return unique_items

def ia_get_full_text(identifier: str) -> Optional[str]:
    """Get full text from Internet Archive"""

    methods = [
        f"https://archive.org/download/{identifier}/{identifier}_djvu.txt",
        f"https://archive.org/download/{identifier}/{identifier}.txt",
        f"https://archive.org/stream/{identifier}/{identifier}_djvu.txt",
    ]

    for url in methods:
        try:
            r = fetch(url, timeout=60)
            if r and r.text and len(r.text) > 500:
                logger.debug(f"✓ Got text from {identifier}")
                return r.text
        except:
            continue

    return None

def ia_extract_recipes_gemini(identifier: str, metadata: Dict) -> List[Dict]:
    """Extract recipes from Internet Archive using Gemini"""

    if progress.is_processed('internet_archive', identifier):
        logger.debug(f"Skipping {identifier} (already processed)")
        return []

    records = []

    try:
        # Get full text
        full_text = ia_get_full_text(identifier)
        if not full_text:
            progress.mark_processed('internet_archive', identifier, 0)
            return []

        # Check if it even mentions latkes
        if not re.search(r'\blatke|potato pancake\b', full_text, re.I):
            logger.info(f"  {identifier}: No latke mentions, skipping")
            progress.mark_processed('internet_archive', identifier, 0)
            return []

        # Extract metadata
        title = metadata.get("title", "Unknown")
        year = extract_year(metadata.get("year") or metadata.get("date"))

        creator = metadata.get("creator", [])
        author = creator[0] if isinstance(creator, list) and creator else (creator or "Unknown")

        publisher = metadata.get("publisher", [])
        publisher = publisher[0] if isinstance(publisher, list) and publisher else (publisher or "")

        # Use Gemini to extract recipes
        logger.info(f"  Using Gemini to parse {identifier}...")
        gemini_recipes = extract_recipes_with_gemini(full_text, title)

        # Convert to our format
        for i, recipe_data in enumerate(gemini_recipes):
            # Join ingredients/instructions lists
            ingredients = '\n'.join(recipe_data.get('ingredients', []))
            instructions = '\n'.join(recipe_data.get('instructions', []))

            recipe = {
                "source": "internet_archive",
                "legality_tier": "public_domain_full_text",
                "site": "archive.org",
                "year": year or 1900,
                "title": recipe_data.get('title', f"Latke Recipe from {title}"),
                "ingredients_raw": ingredients,
                "instructions_raw": instructions,
                "url": f"https://archive.org/details/{identifier}",
                "author": author,
                "publisher": publisher,
                "book_id": identifier,
                "country": "US",
                "quality_score": 0.0  # Will be set by validation
            }

            # Validate
            is_valid, reason = validate_recipe_data(recipe)

            if is_valid:
                recipe['quality_score'] = 0.8  # High quality since Gemini parsed
                records.append(recipe)
                logger.info(f"    ✓ Recipe {i+1}: {recipe['title'][:60]}")
            else:
                logger.debug(f"    ✗ Recipe {i+1} rejected: {reason}")

        progress.mark_processed('internet_archive', identifier, len(records))

        if records:
            logger.info(f"✓ {identifier}: {len(records)} valid recipes extracted")

    except Exception as e:
        logger.error(f"Error processing {identifier}: {e}")
        progress.mark_processed('internet_archive', identifier, 0)

    return records

# ========== Modern Recipe Sites (JSON-LD - NO LLM NEEDED) ==========

# All your modern URLs from before
MODERN_RECIPE_URLS = [
    # Include all your 285+ URLs here - keeping the file shorter for this example
    "https://www.allrecipes.com/recipe/16073/potato-latkes-i/",
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe2-1963445",
    "https://www.seriouseats.com/old-fashioned-latkes-chanukah-hanukah-potato-pancakes",
    # ... (add all your other URLs)
]

def extract_json_ld_recipe(soup: BeautifulSoup) -> Optional[Dict]:
    """Extract recipe from JSON-LD structured data"""
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)

            if isinstance(data, list):
                data = next((item for item in data if item.get("@type") == "Recipe"), {})
            elif "@graph" in data:
                data = next((item for item in data["@graph"] if item.get("@type") == "Recipe"), {})

            if data.get("@type") == "Recipe":
                ingredients = data.get("recipeIngredient", [])
                if isinstance(ingredients, list):
                    ingredients = "\n".join(str(i) for i in ingredients)

                instructions = data.get("recipeInstructions", [])
                inst_text = []
                if isinstance(instructions, list):
                    for step in instructions:
                        if isinstance(step, dict):
                            inst_text.append(step.get("text", ""))
                        else:
                            inst_text.append(str(step))
                    instructions = "\n".join(inst_text)

                author = data.get("author")
                if isinstance(author, dict):
                    author = author.get("name")
                elif isinstance(author, list) and author:
                    author = author[0].get("name") if isinstance(author[0], dict) else str(author[0])

                publisher = data.get("publisher")
                if isinstance(publisher, dict):
                    publisher = publisher.get("name")

                return {
                    "title": data.get("name"),
                    "ingredients": str(ingredients),
                    "instructions": str(instructions),
                    "author": author,
                    "year": extract_year(data.get("datePublished")),
                    "publisher": publisher
                }
        except:
            continue

    return None

def scrape_modern_recipe(url: str) -> Optional[Dict]:
    """Scrape a single modern recipe URL (NO LLM - uses structured data)"""

    if progress.is_processed('modern_site', url):
        return None

    try:
        r = fetch(url, timeout=30)
        if not r:
            progress.mark_processed('modern_site', url, 0)
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        recipe_data = extract_json_ld_recipe(soup)

        if recipe_data:
            domain = urlparse(url).netloc.replace("www.", "")

            recipe = {
                "source": "modern_site",
                "legality_tier": "structured_only",
                "site": domain,
                "year": recipe_data.get("year") or 2024,
                "title": recipe_data.get("title") or "Latkes",
                "ingredients_raw": recipe_data.get("ingredients"),
                "instructions_raw": recipe_data.get("instructions"),
                "url": url,
                "author": recipe_data.get("author"),
                "publisher": recipe_data.get("publisher"),
                "book_id": None,
                "country": "US",
                "quality_score": 1.0  # Modern sites have perfect structure
            }

            is_valid, _ = validate_recipe_data(recipe)

            if is_valid:
                progress.mark_processed('modern_site', url, 1)
                return recipe

        progress.mark_processed('modern_site', url, 0)

    except Exception as e:
        logger.debug(f"Error scraping {url}: {e}")
        progress.mark_processed('modern_site', url, 0)

    return None

def scrape_modern_recipes_parallel(max_workers=5) -> List[Dict]:
    """Scrape modern recipes in parallel"""
    records = []

    logger.info(f"Scraping {len(MODERN_RECIPE_URLS)} modern recipe URLs")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(scrape_modern_recipe, url): url for url in MODERN_RECIPE_URLS}

        for future in as_completed(future_to_url):
            result = future.result()
            if result:
                records.append(result)

            if len(records) % 10 == 0:
                logger.info(f"Progress: {len(records)} modern recipes scraped")

    logger.info(f"✓ Modern sites: {len(records)} recipes")
    return records

# ========== Deduplication ==========

class Deduplicator:
    """Remove duplicate recipes"""

    def __init__(self):
        self.seen_hashes = set()
        self.seen_urls = set()

    def is_duplicate(self, recipe: Dict) -> bool:
        url = recipe.get('url')
        if url and url in self.seen_urls:
            return True

        ingredients = recipe.get('ingredients_raw', '')
        instructions = recipe.get('instructions_raw', '')

        if ingredients or instructions:
            recipe_hash = generate_recipe_hash(ingredients, instructions)

            if recipe_hash in self.seen_hashes:
                return True

            self.seen_hashes.add(recipe_hash)

        if url:
            self.seen_urls.add(url)

        return False

    def deduplicate(self, recipes: List[Dict]) -> List[Dict]:
        unique_recipes = []
        duplicates_removed = 0

        for recipe in recipes:
            if not self.is_duplicate(recipe):
                unique_recipes.append(recipe)
            else:
                duplicates_removed += 1

        logger.info(f"Deduplication: Removed {duplicates_removed} duplicates, kept {len(unique_recipes)}")
        return unique_recipes

# ========== CSV Writing ==========

def write_csv_safely(recipes: List[Dict], filename: str):
    """Write recipes to CSV"""
    if not recipes:
        logger.warning("No recipes to write!")
        return

    columns = [
        "source", "legality_tier", "site", "year", "title",
        "ingredients_raw", "instructions_raw", "url",
        "author", "publisher", "book_id", "country", "quality_score"
    ]

    try:
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=columns,
                quoting=csv.QUOTE_ALL,
                escapechar='\\',
                quotechar='"'
            )

            writer.writeheader()

            for recipe in recipes:
                row = {col: recipe.get(col, "") for col in columns}

                for key in ["ingredients_raw", "instructions_raw", "title", "author", "publisher"]:
                    if row[key]:
                        row[key] = str(row[key]).replace('"', "'").replace('\r', ' ')

                writer.writerow(row)

        logger.info(f"✅ Successfully wrote {len(recipes)} recipes to {filename}")

    except Exception as e:
        logger.error(f"Error writing CSV: {e}")
        raise

# ========== Main Orchestrator ==========

def build_corpus_with_gemini():
    """Main function"""

    logger.info("="*80)
    logger.info("🚀 BUILDING LATKE CORPUS WITH GEMINI AI")
    logger.info("="*80)
    logger.info("Modern sites: Fast JSON-LD parsing (no LLM)")
    logger.info("Historical sources: Google Gemini 1.5 Flash")
    logger.info(f"Gemini API calls today: {gemini_limiter.daily_count}/{GEMINI_DAILY_LIMIT}")
    logger.info("="*80)

    all_recipes = []

    # Phase 1: Modern Sites (NO LLM - fast!)
    logger.info("\n" + "="*80)
    logger.info("PHASE 1: Modern Recipe Websites (JSON-LD)")
    logger.info("="*80)

    try:
        modern_recipes = scrape_modern_recipes_parallel(max_workers=5)
        all_recipes.extend(modern_recipes)
    except Exception as e:
        logger.error(f"Modern sites error: {e}")

    progress.save()

    # Phase 2: Internet Archive (GEMINI)
    logger.info("\n" + "="*80)
    logger.info("PHASE 2: Internet Archive (Gemini AI)")
    logger.info("="*80)

    try:
        ia_items = ia_search_comprehensive()
        logger.info(f"Processing {len(ia_items)} Internet Archive items with Gemini...")

        # Process in smaller batches to avoid hitting daily limits
        batch_size = 20
        for i in range(0, min(len(ia_items), 100), batch_size):  # Limit to 100 for testing
            batch = ia_items[i:i+batch_size]
            logger.info(f"\nBatch {i//batch_size + 1}")

            for j, item in enumerate(batch):
                identifier = item.get("identifier")
                logger.info(f"  [{i+j+1}] {identifier}")

                recipes = ia_extract_recipes_gemini(identifier, item)
                all_recipes.extend(recipes)

                # Check if approaching daily limit
                if gemini_limiter.daily_count >= GEMINI_DAILY_LIMIT * 0.95:
                    logger.warning("⚠️  Approaching Gemini daily limit - stopping IA processing")
                    break

                time.sleep(0.5)

            progress.save()

            if gemini_limiter.daily_count >= GEMINI_DAILY_LIMIT * 0.95:
                break

    except Exception as e:
        logger.error(f"Internet Archive error: {e}", exc_info=True)

    # Deduplication
    logger.info("\n" + "="*80)
    logger.info("DEDUPLICATION")
    logger.info("="*80)

    deduplicator = Deduplicator()
    unique_recipes = deduplicator.deduplicate(all_recipes)

    # Sort
    logger.info("Sorting by year and title...")
    df = pd.DataFrame(unique_recipes)
    if not df.empty:
        df.sort_values(by=["year", "title"], ascending=[True, True], inplace=True)

    # Save
    logger.info("\n" + "="*80)
    logger.info("SAVING RESULTS")
    logger.info("="*80)

    write_csv_safely(df.to_dict('records'), OUT_CSV)

    # Final statistics
    logger.info("\n" + "="*80)
    logger.info("📊 FINAL STATISTICS")
    logger.info("="*80)
    logger.info(f"Total recipes: {len(df)}")

    if not df.empty:
        logger.info(f"\nBy source:")
        for source, count in df['source'].value_counts().items():
            logger.info(f"  {source}: {count}")
        logger.info(f"\nYear range: {df['year'].min()} - {df['year'].max()}")
        logger.info(f"Recipes with ingredients: {df['ingredients_raw'].notna().sum()}")
        logger.info(f"Recipes with instructions: {df['instructions_raw'].notna().sum()}")
        logger.info(f"Average quality score: {df['quality_score'].mean():.2f}")

    stats = progress.get_stats()
    logger.info(f"\nTotal runtime: {stats['runtime_minutes']:.1f} minutes")
    logger.info(f"Gemini API calls: {stats['gemini_calls']}")

    logger.info("="*80)
    logger.info("✅ SUCCESS! Corpus building complete.")
    logger.info(f"📁 Output file: {OUT_CSV}")
    logger.info("="*80)

    return df

# ========== Entry Point ==========

if __name__ == "__main__":
    try:
        if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
            print("\n❌ ERROR: Please set your GEMINI_API_KEY")
            print("Get free key at: https://aistudio.google.com/app/apikey")
            print("\nThen either:")
            print("  1. Set environment variable: export GEMINI_API_KEY='your-key'")
            print("  2. Edit script and replace YOUR_API_KEY_HERE")
            exit(1)

        df = build_corpus_with_gemini()

        if not df.empty:
            print("\n" + "="*80)
            print("SAMPLE RECIPES:")
            print("="*80)
            print(df.head(10)[['year', 'title', 'source', 'quality_score']].to_string(index=False))

    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user. Progress has been saved.")
        stats = progress.get_stats()
        logger.info(f"Current progress: {stats['total_recipes']} recipes, {stats['gemini_calls']} Gemini calls")

    except Exception as e:
        logger.error(f"\n❌ FATAL ERROR: {e}", exc_info=True)
        raise
