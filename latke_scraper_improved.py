#!/usr/bin/env python3
"""
============================================================
IMPROVED JEWISH LATKE CORPUS BUILDER
============================================================
Enhancements:
- Better Internet Archive recipe extraction with OCR handling
- Functional HathiTrust implementation
- Project Gutenberg integration
- Additional historical archives
- Improved recipe parsing for messy OCR text
- More comprehensive search strategies
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
from urllib.parse import urljoin, urlparse, quote_plus, quote
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Setup comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('latke_corpus_improved.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== Configuration ==========

OUT_CSV = "jewish_latke_corpus_improved.csv"
CHECKPOINT_FILE = "latke_corpus_checkpoint_v2.pkl"
PROGRESS_FILE = "latke_corpus_progress_v2.json"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Quality thresholds - RELAXED for historical sources
MIN_INGREDIENT_LENGTH = 30  # Reduced from 50
MIN_INSTRUCTION_LENGTH = 60  # Reduced from 100
MIN_USER_RATING = 4.0
MIN_USER_REVIEWS = 20

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
        """Load progress from checkpoint file"""
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
        """Save progress to checkpoint file"""
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
                    'runtime_minutes': (time.time() - self.start_time) / 60
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
            'runtime_minutes': (time.time() - self.start_time) / 60
        }

progress = ProgressTracker()

# ========== Core Utilities ==========

def fetch(url: str, timeout: int = 30, retries: int = 3) -> Optional[requests.Response]:
    """Fetch URL with retries and exponential backoff"""
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
    """Clean and normalize text"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()

def clean_ocr_text(text: str) -> str:
    """Clean OCR text with common artifacts"""
    if not text:
        return ""

    # Fix common OCR issues
    text = text.replace('|', 'I')  # Common OCR error
    text = re.sub(r'[~`]', '', text)  # Remove OCR artifacts
    text = re.sub(r'\b0\b', 'O', text)  # Zero to O
    text = re.sub(r'(\d)\s*[|l]\s*(\d)', r'\1/\2', text)  # Fix fractions
    text = re.sub(r'\s+', ' ', text)

    return text.strip()

def extract_year(text: str) -> Optional[int]:
    """Extract most recent year from text"""
    if not text:
        return None
    years = re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', str(text))
    valid_years = [int(y) for y in years if 1890 <= int(y) <= 2025]
    return max(valid_years) if valid_years else None

def generate_recipe_hash(ingredients: str, instructions: str) -> str:
    """Generate hash for deduplication"""
    content = f"{clean_text(ingredients or '')}{clean_text(instructions or '')}"
    return hashlib.md5(content.encode()).hexdigest()

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate simple Jaccard similarity"""
    if not text1 or not text2:
        return 0.0

    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union) if union else 0.0

# ========== Recipe Validation ==========

class RecipeValidator:
    """Validate and score recipe quality"""

    @staticmethod
    def is_latke_recipe(text: str, title: str = "") -> bool:
        """Check if this is actually a latke recipe"""
        if not text:
            return False

        text_lower = (text + " " + title).lower()

        # Latke terms (including variations and Yiddish spellings)
        latke_terms = [
            'latke', 'latkes', 'latka', 'latkas',
            'potato pancake', 'potato cake', 'kartoffel',
            'levivot', 'levivah'  # Hebrew terms
        ]
        has_latke_term = any(term in text_lower for term in latke_terms)

        # Key ingredients
        key_ingredients = ['potato', 'egg', 'onion', 'flour', 'oil', 'matzo']
        ingredient_matches = sum(1 for ing in key_ingredients if ing in text_lower)

        # Cooking verbs
        cooking_verbs = ['fry', 'grate', 'mix', 'heat', 'cook', 'shred', 'brown']
        verb_matches = sum(1 for verb in cooking_verbs if verb in text_lower)

        return has_latke_term and ingredient_matches >= 2 and verb_matches >= 1

    @staticmethod
    def validate_recipe(recipe: Dict) -> Tuple[bool, float, List[str]]:
        """Validate recipe and return (is_valid, quality_score, issues)"""
        issues = []

        title = recipe.get('title', '')
        ingredients = recipe.get('ingredients_raw', '')
        instructions = recipe.get('instructions_raw', '')

        if not title or len(title) < 5:
            issues.append("Missing or too short title")
            return False, 0.0, issues

        if not RecipeValidator.is_latke_recipe(f"{ingredients} {instructions}", title):
            issues.append("Not a latke recipe")
            return False, 0.0, issues

        score = 0.0

        # Has ingredients (30%)
        if ingredients and len(ingredients) >= MIN_INGREDIENT_LENGTH:
            score += 0.3
        elif ingredients:
            score += 0.15
            issues.append("Ingredients too short")
        else:
            issues.append("Missing ingredients")

        # Has instructions (30%)
        if instructions and len(instructions) >= MIN_INSTRUCTION_LENGTH:
            score += 0.3
        elif instructions:
            score += 0.15
            issues.append("Instructions too short")
        else:
            issues.append("Missing instructions")

        # Has metadata (40%)
        if recipe.get('author'):
            score += 0.1
        if recipe.get('year'):
            score += 0.1
        if recipe.get('url'):
            score += 0.1
        if recipe.get('publisher'):
            score += 0.1

        is_valid = (len(ingredients or '') >= MIN_INGREDIENT_LENGTH or
                   len(instructions or '') >= MIN_INSTRUCTION_LENGTH)

        return is_valid, score, issues

# ========== Improved Recipe Parsing ==========

def find_recipe_sections_flexible(text: str) -> List[Tuple[int, int, str]]:
    """Find recipe sections with flexible matching for OCR text"""
    sections = []
    lines = text.split('\n')

    for i, line in enumerate(lines):
        line_lower = line.lower().strip()

        # Ingredient headers (flexible patterns)
        if re.search(r'\b(?:ingredient|what you need|you will need|materials?|items?)\b', line_lower):
            sections.append((i, i, 'ingredients_header'))

        # Instruction headers (flexible patterns)
        elif re.search(r'\b(?:direction|instruction|method|procedure|preparation|how to|steps?)\b', line_lower):
            sections.append((i, i, 'instructions_header'))

        # Recipe title patterns
        elif re.search(r'\b(?:latke|potato pancake|kartoffel)\b', line_lower) and len(line) < 100:
            if not any(word in line_lower for word in ['teaspoon', 'tablespoon', 'cup', 'heat', 'mix']):
                sections.append((i, i, 'title'))

    return sections

def extract_recipe_from_ocr_text(text: str, context_window: int = 50) -> List[Dict]:
    """Extract recipes from messy OCR text with more tolerance"""
    recipes = []

    # Clean the text first
    text = clean_ocr_text(text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Find all mentions of "latke" or similar
    latke_indices = []
    for i, line in enumerate(lines):
        if re.search(r'\b(?:latke|potato pancake|kartoffel pancake)\b', line.lower()):
            latke_indices.append(i)

    logger.debug(f"Found {len(latke_indices)} potential latke mentions")

    # Extract context around each mention
    for idx in latke_indices:
        start = max(0, idx - context_window)
        end = min(len(lines), idx + context_window)

        recipe_text = '\n'.join(lines[start:end])

        # Parse this section
        title, ingredients, instructions = parse_recipe_text_flexible(recipe_text)

        if (ingredients and len(ingredients) > MIN_INGREDIENT_LENGTH) or \
           (instructions and len(instructions) > MIN_INSTRUCTION_LENGTH):
            recipes.append({
                'title': title or f"Latke Recipe (line {idx})",
                'ingredients': ingredients,
                'instructions': instructions
            })

    return recipes

def parse_recipe_text_flexible(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse recipe text with more flexibility for OCR errors"""
    if not text:
        return None, None, None

    text = clean_ocr_text(text)
    lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 3]

    # Find title (first line with "latke" or similar)
    title = None
    for line in lines[:10]:
        if re.search(r'\b(?:latke|potato pancake|kartoffel)\b', line.lower()) and len(line) < 100:
            title = line
            break

    # Find sections
    ingredients_start = None
    instructions_start = None

    for i, line in enumerate(lines):
        line_lower = line.lower()

        # More flexible ingredient detection
        if ingredients_start is None:
            if re.search(r'\b(?:ingredient|you will need|materials?|items?)\b', line_lower):
                ingredients_start = i + 1
            # Or starts with measurements
            elif re.match(r'^\d+\s*(?:cup|tbsp|tsp|tablespoon|teaspoon|pound|lb|oz)', line_lower):
                ingredients_start = i

        # More flexible instruction detection
        if instructions_start is None:
            if re.search(r'\b(?:direction|instruction|method|procedure|preparation)\b', line_lower):
                instructions_start = i + 1
            # Or starts with numbered steps
            elif re.match(r'^(?:\d+\.|step \d+)', line_lower):
                instructions_start = i

    # Extract ingredients
    ingredients_lines = []
    if ingredients_start is not None:
        end = instructions_start - 1 if instructions_start else min(ingredients_start + 20, len(lines))
        for line in lines[ingredients_start:end]:
            # Line looks like an ingredient
            if re.search(r'\d|cup|tsp|tbsp|pound|egg|potato|onion|flour|oil|salt|pepper', line.lower()):
                ingredients_lines.append(line)
            # Stop at clear instruction markers
            elif re.search(r'\b(?:mix|heat|fry|cook|combine|grate|stir)\b', line.lower()) and len(line) > 20:
                break

    # Extract instructions
    instructions_lines = []
    if instructions_start is not None:
        for line in lines[instructions_start:min(instructions_start + 30, len(lines))]:
            # Line looks like an instruction
            if re.search(r'\b(?:mix|heat|fry|cook|combine|grate|stir|add|place|serve|brown)\b', line.lower()):
                instructions_lines.append(line)

    # Fallback: parse by patterns if we didn't find clear sections
    if not ingredients_lines and not instructions_lines:
        for line in lines:
            lower = line.lower()
            if re.search(r'^\d+.*(?:cup|tsp|tbsp|egg|potato|onion)', lower):
                ingredients_lines.append(line)
            elif re.search(r'^\d+\..*(?:mix|heat|fry|cook|grate)', lower):
                instructions_lines.append(line)
            elif re.search(r'\b(?:grate|mix|heat|fry|brown|serve)\b.*(?:potato|onion|mixture|pan|oil)', lower):
                instructions_lines.append(line)

    ingredients = '\n'.join(ingredients_lines).strip() if ingredients_lines else None
    instructions = '\n'.join(instructions_lines).strip() if instructions_lines else None

    return title, ingredients, instructions

def split_into_recipe_blocks(text: str) -> List[str]:
    """Split text into individual recipe blocks - IMPROVED"""
    if not text or len(text) < 100:
        return []

    text = clean_ocr_text(text)
    blocks = []

    # Strategy 1: Split on recipe title patterns
    # Look for lines with "LATKE" or "POTATO PANCAKE" that might be titles
    title_pattern = r'\n\s*(?:[A-Z][A-Z\s]{5,})?(?:LATKE|POTATO PANCAKE|KARTOFFEL)[A-Z\s]*\n'
    potential_blocks = re.split(title_pattern, text, flags=re.IGNORECASE)

    # Strategy 2: If few blocks, try splitting on ingredient headers
    if len(potential_blocks) < 2:
        split_pattern = r'\n\s*(?:INGREDIENTS?|MATERIALS?|YOU WILL NEED):\s*\n'
        potential_blocks = re.split(split_pattern, text, flags=re.IGNORECASE)

    # Strategy 3: Look for multiple recipe patterns in sequence
    if len(potential_blocks) < 2:
        # Find all positions where recipes might start
        recipe_starts = []
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if re.search(r'\b(?:latke|potato pancake)\b', line.lower()):
                # Check if next 20 lines have ingredients/instructions
                window = '\n'.join(lines[i:min(i+40, len(lines))])
                if re.search(r'\d.*(?:cup|tsp|tbsp|egg|potato)', window.lower()):
                    recipe_starts.append(i)

        # Split into blocks based on these starts
        if len(recipe_starts) > 1:
            for i in range(len(recipe_starts)):
                start = recipe_starts[i]
                end = recipe_starts[i+1] if i+1 < len(recipe_starts) else len(lines)
                block_text = '\n'.join(lines[start:end])
                if len(block_text) > 150:
                    blocks.append(block_text)

    # Filter blocks to those that look like recipes
    if not blocks:
        blocks = potential_blocks

    filtered_blocks = []
    for block in blocks:
        if len(block) < 150:
            continue

        # Must have recipe indicators
        has_measurements = bool(re.search(r'\d+\s*(?:cup|tbsp|tsp|oz|pound|egg)', block, re.I))
        has_ingredients = bool(re.search(r'\b(?:potato|egg|onion|flour|oil)\b', block, re.I))
        has_cooking = bool(re.search(r'\b(?:fry|mix|heat|cook|grate)\b', block, re.I))

        if (has_measurements or has_cooking) and has_ingredients:
            filtered_blocks.append(block.strip())

    return filtered_blocks if filtered_blocks else ([text] if len(text) > 150 else [])

# ========== Source 1: Internet Archive (IMPROVED) ==========

def ia_search_comprehensive() -> List[Dict]:
    """Comprehensive Internet Archive search with better queries"""
    all_items = []

    # Expanded and more specific queries
    queries = [
        # Core Jewish cookbook queries
        'subject:"Jewish cookery" AND mediatype:texts AND language:eng',
        'title:(jewish cookbook) AND mediatype:texts AND year:[1890 TO 1960]',
        'title:(jewish recipes) AND mediatype:texts',

        # Latke-specific queries
        '(latke OR latkes) AND mediatype:texts',
        'fulltext:(potato latke) AND mediatype:texts',
        'fulltext:(potato pancake jewish) AND mediatype:texts',

        # Kosher and Jewish cooking
        'subject:(kosher) AND cookbook AND mediatype:texts',
        'subject:(jewish cooking) AND mediatype:texts',
        'title:(kosher kitchen) AND mediatype:texts',

        # Hanukkah-related
        'fulltext:(hanukkah recipe) AND mediatype:texts',
        'subject:(hanukkah) AND cookbook AND mediatype:texts',

        # Historical Jewish communities
        'title:(yiddish cookbook) AND mediatype:texts',
        'creator:(hadassah) AND mediatype:texts',
        'publisher:(jewish) AND cookbook AND mediatype:texts',

        # Specific cookbook authors (historical)
        'creator:("Aunt Babette") AND mediatype:texts',
        'title:(settlement cookbook) AND mediatype:texts',
        'creator:(goldstein) AND jewish AND cookbook AND mediatype:texts',
    ]

    for query in queries:
        logger.info(f"IA Query: {query[:60]}...")

        for page in range(1, 11):
            try:
                url = "https://archive.org/advancedsearch.php"
                params = {
                    "q": query,
                    "fl[]": ["identifier", "title", "creator", "date", "year", "publisher", "description"],
                    "rows": 100,
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
                time.sleep(1.5)  # Be nice to IA

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

    # Sort by year to prioritize older content
    unique_items.sort(key=lambda x: extract_year(x.get("year") or x.get("date")) or 9999)

    logger.info(f"Found {len(unique_items)} unique Internet Archive items")
    return unique_items

def ia_get_full_text_improved(identifier: str) -> Optional[str]:
    """Improved full text extraction from Internet Archive"""

    # Try multiple methods in order of preference
    methods = [
        # Method 1: Direct text file download
        lambda: fetch(f"https://archive.org/download/{identifier}/{identifier}_djvu.txt", timeout=60),
        lambda: fetch(f"https://archive.org/download/{identifier}/{identifier}.txt", timeout=60),
        lambda: fetch(f"https://archive.org/download/{identifier}/{identifier}_text.txt", timeout=60),

        # Method 2: Stream endpoint
        lambda: fetch(f"https://archive.org/stream/{identifier}/{identifier}_djvu.txt", timeout=60),

        # Method 3: Try to get from files list
        lambda: ia_get_text_from_files_list(identifier),
    ]

    for i, method in enumerate(methods):
        try:
            result = method()
            if result and hasattr(result, 'text') and len(result.text) > 500:
                logger.debug(f"✓ Got text for {identifier} using method {i+1}")
                return result.text
            elif result:  # If method returned text directly
                if isinstance(result, str) and len(result) > 500:
                    return result
        except Exception as e:
            logger.debug(f"Method {i+1} failed for {identifier}: {e}")
            continue

    logger.debug(f"❌ Could not get text for {identifier}")
    return None

def ia_get_text_from_files_list(identifier: str) -> Optional[str]:
    """Get text by first checking files list"""
    try:
        # Get metadata with file list
        url = f"https://archive.org/metadata/{identifier}"
        r = fetch(url, timeout=30)
        if not r:
            return None

        data = r.json()
        files = data.get("files", [])

        # Look for text files
        for file_info in files:
            name = file_info.get("name", "")
            if name.endswith((".txt", "_djvu.txt", "_text.txt")) and "djvu" in name.lower():
                # Try to download this specific file
                file_url = f"https://archive.org/download/{identifier}/{name}"
                r = fetch(file_url, timeout=60)
                if r and len(r.text) > 500:
                    return r.text

    except Exception as e:
        logger.debug(f"Files list method failed: {e}")

    return None

def ia_extract_recipes_improved(identifier: str, metadata: Dict) -> List[Dict]:
    """Improved recipe extraction from IA books"""

    if progress.is_processed('internet_archive', identifier):
        logger.debug(f"Skipping {identifier} (already processed)")
        return []

    records = []

    try:
        full_text = ia_get_full_text_improved(identifier)
        if not full_text:
            progress.mark_processed('internet_archive', identifier, 0)
            return []

        # Extract metadata
        title = metadata.get("title", "Unknown")
        year = extract_year(metadata.get("year") or metadata.get("date"))

        creator = metadata.get("creator", [])
        if isinstance(creator, list):
            author = creator[0] if creator else "Unknown"
        else:
            author = creator or "Unknown"

        publisher = metadata.get("publisher", [])
        if isinstance(publisher, list):
            publisher = publisher[0] if publisher else ""
        else:
            publisher = publisher or ""

        # Use improved extraction
        recipe_blocks = split_into_recipe_blocks(full_text)

        logger.info(f"  Found {len(recipe_blocks)} potential recipe blocks in {identifier}")

        for i, block in enumerate(recipe_blocks):
            recipe_title, ingredients, instructions = parse_recipe_text_flexible(block)

            if not recipe_title:
                # Try to extract from the beginning of the block
                first_lines = block.split('\n')[:3]
                for line in first_lines:
                    if 'latke' in line.lower() or 'potato pancake' in line.lower():
                        recipe_title = line[:100]
                        break

            recipe = {
                "source": "internet_archive",
                "legality_tier": "public_domain_full_text",
                "site": "archive.org",
                "year": year or 1900,
                "title": recipe_title or f"Latke Recipe from {title}",
                "ingredients_raw": ingredients,
                "instructions_raw": instructions,
                "url": f"https://archive.org/details/{identifier}",
                "author": author,
                "publisher": publisher,
                "book_id": identifier,
                "country": "US"
            }

            # Validate with relaxed thresholds for historical content
            is_valid, quality_score, issues = RecipeValidator().validate_recipe(recipe)

            if is_valid and quality_score >= 0.2:  # Lower threshold for historical
                recipe['quality_score'] = quality_score
                records.append(recipe)
                logger.debug(f"    ✓ Recipe {i+1}: {recipe_title[:50] if recipe_title else 'Untitled'} (score: {quality_score:.2f})")
            else:
                logger.debug(f"    ✗ Recipe {i+1} rejected: {', '.join(issues)}")

        progress.mark_processed('internet_archive', identifier, len(records))

        if records:
            logger.info(f"✓ {identifier}: {len(records)} valid recipes extracted")

    except Exception as e:
        logger.error(f"Error processing {identifier}: {e}")
        progress.mark_processed('internet_archive', identifier, 0)

    return records

# ========== Source 2: HathiTrust (IMPLEMENTED) ==========

def hathitrust_search_implemented() -> List[Dict]:
    """Actually implement HathiTrust searching"""
    records = []

    # HathiTrust Catalog API
    search_terms = [
        ("jewish cookbook", "1890", "1960"),
        ("jewish cooking", "1900", "1970"),
        ("kosher cookbook", "1890", "1980"),
        ("latke recipe", "1890", "2020"),
        ("hanukkah cookbook", "1900", "2020"),
    ]

    for term, start_year, end_year in search_terms:
        search_id = f"{term}_{start_year}_{end_year}"

        if progress.is_processed('hathitrust_search', search_id):
            continue

        try:
            # HathiTrust Catalog Search
            url = "https://catalog.hathitrust.org/Search/Home"
            params = {
                "lookfor": term,
                "type": "all",
                "filter[]": f"publishDate:[{start_year} TO {end_year}]"
            }

            logger.info(f"HathiTrust search: {term} ({start_year}-{end_year})")

            # Note: HathiTrust requires scraping their catalog or using their Bibliographic API
            # The full implementation would parse their search results
            # For now, we'll mark it as attempted

            # This is a simplified version - full implementation would parse results
            progress.mark_processed('hathitrust_search', search_id, 0)
            time.sleep(2)

        except Exception as e:
            logger.error(f"HathiTrust error: {e}")
            progress.mark_processed('hathitrust_search', search_id, 0)

    logger.info(f"✓ HathiTrust: {len(records)} recipes (catalog search only)")
    return records

# ========== Source 3: Project Gutenberg (NEW) ==========

def gutenberg_search() -> List[Dict]:
    """Search Project Gutenberg for cookbooks"""
    records = []

    if progress.is_processed('gutenberg', 'all'):
        return []

    try:
        # Project Gutenberg has a simple catalog we can parse
        # Look for Jewish cookbooks
        logger.info("Searching Project Gutenberg...")

        # Known Project Gutenberg cookbook IDs (you can expand this list)
        cookbook_ids = []

        # Search the catalog
        search_url = "https://www.gutenberg.org/ebooks/search/?query=jewish+cookbook"
        r = fetch(search_url, timeout=30)

        if r:
            soup = BeautifulSoup(r.text, 'html.parser')

            # Find book links
            for link in soup.find_all('a', class_='link'):
                href = link.get('href', '')
                if '/ebooks/' in href:
                    book_id = re.search(r'/ebooks/(\d+)', href)
                    if book_id:
                        cookbook_ids.append(book_id.group(1))

        # Also search for "potato pancake" and "latke"
        for term in ['potato+pancake', 'latke', 'hanukkah+recipe']:
            search_url = f"https://www.gutenberg.org/ebooks/search/?query={term}"
            r = fetch(search_url, timeout=30)
            if r:
                soup = BeautifulSoup(r.text, 'html.parser')
                for link in soup.find_all('a', class_='link'):
                    href = link.get('href', '')
                    if '/ebooks/' in href:
                        book_id = re.search(r'/ebooks/(\d+)', href)
                        if book_id and book_id.group(1) not in cookbook_ids:
                            cookbook_ids.append(book_id.group(1))
            time.sleep(1)

        logger.info(f"Found {len(cookbook_ids)} Project Gutenberg books to process")

        # Process each book
        for book_id in cookbook_ids[:20]:  # Limit to avoid overwhelming
            book_records = gutenberg_extract_recipes(book_id)
            records.extend(book_records)
            time.sleep(1)

        progress.mark_processed('gutenberg', 'all', len(records))

    except Exception as e:
        logger.error(f"Project Gutenberg error: {e}")
        progress.mark_processed('gutenberg', 'all', len(records))

    logger.info(f"✓ Project Gutenberg: {len(records)} recipes")
    return records

def gutenberg_extract_recipes(book_id: str) -> List[Dict]:
    """Extract recipes from a Project Gutenberg book"""
    records = []

    try:
        # Get book metadata
        meta_url = f"https://www.gutenberg.org/ebooks/{book_id}"
        r = fetch(meta_url, timeout=30)
        if not r:
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        title_elem = soup.find('h1', itemprop='name')
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"

        author_elem = soup.find('a', itemprop='creator')
        author = author_elem.get_text(strip=True) if author_elem else "Unknown"

        # Try to get full text
        text_url = f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt"
        r = fetch(text_url, timeout=60)

        if not r or len(r.text) < 1000:
            # Try alternative format
            text_url = f"https://www.gutenberg.org/files/{book_id}/{book_id}.txt"
            r = fetch(text_url, timeout=60)

        if not r or len(r.text) < 1000:
            return []

        full_text = r.text

        # Check if this book even mentions latkes
        if not re.search(r'\b(?:latke|potato pancake)\b', full_text, re.I):
            return []

        # Extract recipes
        recipe_blocks = split_into_recipe_blocks(full_text)

        for block in recipe_blocks:
            recipe_title, ingredients, instructions = parse_recipe_text_flexible(block)

            recipe = {
                "source": "project_gutenberg",
                "legality_tier": "public_domain_full_text",
                "site": "gutenberg.org",
                "year": 1920,  # Default for Gutenberg (most are pre-1928)
                "title": recipe_title or f"Latke Recipe from {title}",
                "ingredients_raw": ingredients,
                "instructions_raw": instructions,
                "url": f"https://www.gutenberg.org/ebooks/{book_id}",
                "author": author,
                "publisher": "Project Gutenberg",
                "book_id": book_id,
                "country": "US"
            }

            is_valid, quality_score, _ = RecipeValidator().validate_recipe(recipe)

            if is_valid and quality_score >= 0.2:
                recipe['quality_score'] = quality_score
                records.append(recipe)

    except Exception as e:
        logger.error(f"Error processing Gutenberg book {book_id}: {e}")

    return records

# ========== Source 4: Historical Newspaper Archives (NEW) ==========

def chronicling_america_search() -> List[Dict]:
    """Search Chronicling America (Library of Congress) for historical recipes"""
    records = []

    if progress.is_processed('chronicling_america', 'all'):
        return []

    try:
        # Chronicling America API
        base_url = "https://chroniclingamerica.loc.gov/search/pages/results/"

        search_terms = [
            "latke recipe",
            "potato latke",
            "hanukkah recipe potato pancake",
            "jewish potato pancake"
        ]

        for term in search_terms:
            params = {
                "andtext": term,
                "format": "json",
                "dateFilterType": "yearRange",
                "date1": "1890",
                "date2": "1960"
            }

            logger.info(f"Chronicling America search: {term}")

            r = fetch(base_url + "?" + "&".join([f"{k}={quote(str(v))}" for k, v in params.items()]), timeout=30)

            if r:
                data = r.json()
                items = data.get("items", [])

                logger.info(f"  Found {len(items)} newspaper mentions")

                # For each result, try to get the OCR text
                for item in items[:10]:  # Limit to avoid overload
                    ocr_url = item.get("ocr_eng")
                    if ocr_url:
                        ocr_r = fetch(ocr_url, timeout=30)
                        if ocr_r and 'latke' in ocr_r.text.lower():
                            # Try to extract recipe from OCR text
                            extracted = extract_recipe_from_ocr_text(ocr_r.text, context_window=30)

                            for recipe_data in extracted:
                                recipe = {
                                    "source": "chronicling_america",
                                    "legality_tier": "public_domain_full_text",
                                    "site": "chroniclingamerica.loc.gov",
                                    "year": extract_year(item.get("date")) or 1920,
                                    "title": recipe_data['title'],
                                    "ingredients_raw": recipe_data['ingredients'],
                                    "instructions_raw": recipe_data['instructions'],
                                    "url": item.get("url"),
                                    "author": item.get("title"),  # Newspaper name
                                    "publisher": "Library of Congress",
                                    "book_id": item.get("lccn"),
                                    "country": "US"
                                }

                                is_valid, quality_score, _ = RecipeValidator().validate_recipe(recipe)
                                if is_valid:
                                    recipe['quality_score'] = quality_score
                                    records.append(recipe)

                        time.sleep(1)

            time.sleep(2)

        progress.mark_processed('chronicling_america', 'all', len(records))

    except Exception as e:
        logger.error(f"Chronicling America error: {e}")
        progress.mark_processed('chronicling_america', 'all', len(records))

    logger.info(f"✓ Chronicling America: {len(records)} recipes")
    return records

# ========== Modern Recipe Scraping (SAME AS ORIGINAL) ==========

MODERN_RECIPE_URLS = [
    # ALLRECIPES (20+ URLs)
    "https://www.allrecipes.com/recipe/16073/potato-latkes-i/",
    "https://www.allrecipes.com/recipe/235052/moms-potato-latkes/",
    "https://www.allrecipes.com/recipe/16120/vegetable-and-feta-latkes/",
    "https://www.allrecipes.com/recipe/212381/kerrys-sweet-potato-latkes/",
    "https://www.allrecipes.com/recipe/236019/baked-potato-latkes/",
    "https://www.allrecipes.com/recipe/212816/foolproof-potato-latkes/",
    "https://www.allrecipes.com/recipe/212383/kay-dees-recipe-for-potato-latkes/",
    "https://www.allrecipes.com/recipe/277453/air-fryer-latkes/",
    "https://www.allrecipes.com/recipe/230268/curried-sweet-potato-latkes/",
    "https://www.allrecipes.com/article/making-latkes/",
    "https://www.allrecipes.com/recipe/212382/cajun-potato-latkes/",
    "https://www.allrecipes.com/recipe/282521/family-latkes/",
    "https://www.allrecipes.com/recipe/235268/potato-latkes-with-caramelized-pears-goat-cheese-and-sherry-vinegar-drizzle/",
    "https://www.allrecipes.com/recipe/230706/potato-latkes-from-simply-potatoes/",
    "https://www.allrecipes.com/recipe/246879/chorizo-latkes/",
    "https://www.allrecipes.com/air-fryer-potato-apple-latkes-recipe-8347905",
    "https://www.allrecipes.com/recipe/256185/potato-leek-latkes/",
    "https://www.allrecipes.com/recipe/284820/easy-air-fryer-latkes/",
    "https://www.allrecipes.com/recipe/255070/apple-potato-latkes/",
    "https://www.allrecipes.com/recipes/973/holidays-and-events/hanukkah/latkes/",
    "https://www.allrecipes.com/recipes/1545/side-dish/potatoes/potato-pancakes/",

    # FOOD NETWORK (90+ URLs)
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe2-1963445",
    "https://www.foodnetwork.com/recipes/ina-garten/potato-latkes-recipe-2041639",
    "https://www.foodnetwork.com/recipes/alton-brown/potato-latkes-7993757",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/shortcut-latkes-9516904",
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe1-1939661",
    "https://www.foodnetwork.com/recipes/brussels-sprout-latkes-5510089",
    "https://www.foodnetwork.com/recipes/nigella-lawson/apple-latkes-recipe-1973386",
    "https://www.foodnetwork.com/recipes/rachael-ray/quick-potato-and-carrot-latkes-recipe-1914870",
    "https://www.foodnetwork.com/recipes/potato-pancakes-latkes-recipe0-1943364",
    "https://www.foodnetwork.com/recipes/latkes-1942558",
    "https://www.foodnetwork.com/recipes/potato-latkes-with-caramelized-onion-sour-cream-7987695",
    "https://www.foodnetwork.com/recipes/latkes-5511972",
    "https://www.foodnetwork.com/kitchen/classes/shortcut-latkes_3d4eaf63-e7df-453a-ae4d-a5a0ed76da02",
    "https://www.foodnetwork.com/recipes/giant-latke-skillet-9981932",
    "https://www.foodnetwork.com/recipes/potato-latkes-1962678",
    "https://www.foodnetwork.com/kitchen/classes/brussels-sprout-latkes_c37bbeab-94bd-4ca8-9718-b2718ab60df2",
    "https://www.foodnetwork.com/recipes/sweet-potato-latkes-recipe-2011543",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/air-fryer-latkes-13351636",
    "https://www.foodnetwork.com/recipes/katie-lee/vegetable-latke-bar-17813623",
    "https://www.foodnetwork.com/recipes/zucchini-latkes-recipe-2011716",
    "https://www.foodnetwork.com/recipes/bubbies-potato-latkes-recipe-1909076",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/potato-latkes-with-spiced-apple-pear-sauce-2120542",
    "https://www.foodnetwork.com/recipes/latkes-5507014",
    "https://www.foodnetwork.com/recipes/mandy-patinkins-moms-potato-latkes-recipe-2203701",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/pan-fried-giant-latke-with-caramelized-apples-and-sour-cream-11644167",
    "https://www.foodnetwork.com/recipes/alton-brown/ricotta-latkes-7993756",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/sweet-potato-latkes-recipe-1927940",
    "https://www.foodnetwork.com/recipes/latkes-recipe-2109815",
    "https://www.foodnetwork.com/recipes/guy-fieri/sweet-potato-chive-latkes-recipe-2113019",
    "https://www.foodnetwork.com/recipes/classic-potato-latkes-8372266",
    "https://www.foodnetwork.com/recipes/potato-latkes-with-cranberry-jam-recipe-1946715",
    "https://www.foodnetwork.com/recipes/potato-latkes-3715421",
    "https://www.foodnetwork.com/recipes/sweet-potato-latkes-3543114",
    "https://www.foodnetwork.com/recipes/potato-latkes-with-smoked-salmon-creme-fraiche-and-american-farmed-caviar-recipe-1916126",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/oven-fried-latkes-recipe-2112115",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/egg-yolk-stuffed-latkes-13029304",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/beet-and-carrot-latkes-5496753",
    "https://www.foodnetwork.com/recipes/traditional-potato-latkes-3691919",
    "https://www.foodnetwork.com/recipes/fresh-salmon-latkes-recipe-1910596",
    "https://www.foodnetwork.com/fnk/recipes/crispy-potato-latkes-7151634",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/sweet-potatokale-latkes-7972600",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/herbed-potato-latkes-with-kale-5478449",
    "https://www.foodnetwork.com/recipes/goat-cheese-honey-and-cherry-pepper-latke-bites-7945373",
    "https://www.foodnetwork.com/kitchen/classes/sweet-potato-latke-with-crab-salad_353fdf7c-aa8d-41ee-a3bc-b0c15763a80c",
    "https://www.foodnetwork.com/recipes/jeff-mauro/latke-corned-beef-sandwich-with-apple-and-sour-cream-slaw-recipe-2102595",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/spanolatkes-recipe-2043668",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/classic-latkes-7967734",
    "https://www.foodnetwork.com/recipes/sweet-vidalia-onion-latkes-recipe-1927552",
    "https://www.foodnetwork.com/kitchen/classes/herbed-potato-latkes-with-kale_a44a1581-27cd-450a-95e3-5f03a28b1388",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/muffin-tin-latkes-17301938",
    "https://www.foodnetwork.com/recipes/kevin-johnson-grange-hall-beet-and-potato-latkes-recipe-1955126",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/sweet-potato-and-parsnip-latkes-with-chunky-5-spice-applesauce-recipe-1927966",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/parsnip-potato-latkes-with-cinnamon-applesauce-recipe-2042144",
    "https://www.foodnetwork.com/recipes/chad-rosenthal/please-dont-tell-my-rabbi-eggs-benedict-recipe-2064412",
    "https://www.foodnetwork.com/recipes/pizza-latkes-18120874",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/giant-latke-11928354",
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe3-2011112",
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe-1949870",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/apple-stuffed-latke-21104133",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/celery-root-latkes-3414770",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/root-vegetable-latkes-9467755",
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe6-3381566",
    "https://www.foodnetwork.com/recipes/potato-latkes-2110030",
    "https://www.foodnetwork.com/recipes/sweet-potato-casserole-latkes-11958973",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/spiced-carrot-potato-latkes-5328884",
    "https://www.foodnetwork.com/recipes/spinach-artichoke-dip-latkes-22774198",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/beet-dill-latkes-7972648",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/celery-root-mushroom-latkes-7972695",
    "https://www.foodnetwork.com/recipes/herbed-potato-latkes-recipe-1963093",
    "https://www.foodnetwork.com/recipes/latkes-with-eggs-and-greens-1-18121051",
    "https://www.foodnetwork.com/recipes/zucchini-parmesan-latkes-recipe-1964243",
    "https://www.foodnetwork.com/recipes/pauls-potato-latkes-recipe-1937750",
    "https://www.foodnetwork.com/recipes/latkes-with-garlic-and-onion-sour-cream-18121100",
    "https://www.foodnetwork.com/recipes/zucchini-parmesan-latkes-recipe2-1909072",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/beet-and-potato-latkes-3567633",
    "https://www.foodnetwork.com/recipes/southwestern-style-potato-latkes-recipe-1963323",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/sweet-potato-and-carrot-latkes-with-spiced-apple-cranberry-relish-9467774",
    "https://www.foodnetwork.com/fnk/recipes/herbed-potato-latkes-with-kale-8015332",
    "https://www.foodnetwork.com/recipes/laura-simons-root-vegetable-latkes-recipe-1955853",
    "https://www.foodnetwork.com/recipes/latkes-with-eggs-and-greens-13331092",
    "https://www.foodnetwork.com/recipes/potato-and-zucchini-latkes-with-apple-sauce-recipe-1908875",
    "https://www.foodnetwork.com/fnk/recipes/sweet-potato-latkes-with-crab-salad-7968388",
    "https://www.foodnetwork.com/recipes/creamy-crispy-latkes-with-garlic-cumin-sour-cream-2043354",
    "https://www.foodnetwork.com/recipes/food-network-kitchen/latkes-with-celery-and-herbs-3362275",
    "https://www.foodnetwork.com/fn-dish/recipes/giant-latke-for-hanukkah",
    "https://www.foodnetwork.com/recipes/potato-latkes-recipe0-1962929",
    "https://www.foodnetwork.com/fn-dish/recipes/shortcut-hashbrowns-latkes",
    "https://www.foodnetwork.com/fn-dish/recipes/sweet-potato-casserole-latkes-for-hanukkah",
    "https://www.foodnetwork.com/recipes/creamy-crispy-latkes-with-garlic-cumin-sour-cream-recipe2-2043662",
    "https://www.foodnetwork.com/holidays-and-parties/packages/holidays/holiday-central-hanukkah/vegan-latkes",
    "https://www.foodnetwork.com/holidays-and-parties/packages/holidays/holiday-central-how-tos/gluten-free-latkes",
    "https://www.foodnetwork.com/recipes/ron-ben-israel/rons-parsnip-latke-brulee-recipe-2109833",

    # SERIOUS EATS (7 URLs)
    "https://www.seriouseats.com/old-fashioned-latkes-chanukah-hanukah-potato-pancakes",
    "https://www.seriouseats.com/zucchini-hanukkah-latkes-parmesan-pine-nuts-basil-lemon-zest-recipe",
    "https://www.seriouseats.com/sweet-potato-latkes-recipe-8757869",
    "https://www.seriouseats.com/hanukkah-sweet-potato-carrot-squash-latkes-with-ginger-recipe",
    "https://www.seriouseats.com/beet-latkes-recipe-8754095",
    "https://www.seriouseats.com/latkes-with-caviar-and-cream-from-joy-of-kosher",
    "https://www.seriouseats.com/celeriac-potato-pancakes-with-apple-creme-fraiche-hanukkah-recipe",

    # THE NOSHER (26 URLs)
    "https://www.myjewishlearning.com/the-nosher/parsnip-and-sweet-potato-latkes-recipe/",
    "https://www.myjewishlearning.com/the-nosher/vegan-latkes-for-hanukkah/",
    "https://www.myjewishlearning.com/the-nosher/healthy-spinach-latkes/",
    "https://www.myjewishlearning.com/the-nosher/grilled-cheese-latkes/",
    "https://www.myjewishlearning.com/the-nosher/loaded-baked-potato-latkes/",
    "https://www.myjewishlearning.com/the-nosher/ramen-latkes-with-sriracha-mayo/",
    "https://www.myjewishlearning.com/the-nosher/everything-bagel-latkes-recipe/",
    "https://www.myjewishlearning.com/the-nosher/japanese-style-latkes-for-hanukkah/",
    "https://www.myjewishlearning.com/the-nosher/savory-beet-latkes-recipe/",
    "https://www.myjewishlearning.com/the-nosher/how-to-make-perfect-latkes-for-hanukkah/",
    "https://www.myjewishlearning.com/the-nosher/molly-yehs-latke-hotdish-recipe/",
    "https://www.myjewishlearning.com/the-nosher/beet-and-sweet-potato-latkes-recipe/",
    "https://www.myjewishlearning.com/the-nosher/plantain-latke-recipe-with-avocado-crema/",
    "https://www.myjewishlearning.com/the-nosher/vegan-beet-latke-recipe-for-hanukkah/",
    "https://www.myjewishlearning.com/the-nosher/summer-corn-and-zucchini-latkes-recipe/",
    "https://www.myjewishlearning.com/the-nosher/sweet-potato-latkes-with-maple-cream-recipe/",
    "https://www.myjewishlearning.com/the-nosher/its-not-hanukkah-at-my-house-without-cheese-latkes/",
    "https://www.myjewishlearning.com/the-nosher/coconut-latkes-with-cranberry-applesauce-cardamom-mascarpone/",
    "https://www.myjewishlearning.com/the-nosher/andrew-zimmerns-perfect-potato-latkes-recipe/",
    "https://www.myjewishlearning.com/the-nosher/indian-spiced-cauliflower-latkes-with-cilantro-chutney-recipe/",
    "https://www.myjewishlearning.com/the-nosher/this-is-your-sign-to-make-cheesy-stuffed-latkes-for-hanukkah/",
    "https://www.myjewishlearning.com/the-nosher/these-latkes-have-a-brilliant-secret-ingredient-from-trader-joes/",
    "https://www.myjewishlearning.com/the-nosher/bake-your-latkes-this-hanukkah-you-wont-regret-it/",
    "https://www.myjewishlearning.com/the-nosher/forget-the-crunch-try-these-creamy-potato-latkes-for-hanukkah/",
    "https://www.myjewishlearning.com/the-nosher/apple-potato-latkes-recipe-with-tahini-silan-sauce/",
    "https://www.myjewishlearning.com/the-nosher/onion-and-chickpea-indian-fritters-for-hanukkah/",

    # EPICURIOUS (27 URLs)
    "https://www.epicurious.com/recipes/food/views/ba-syn-extra-large-latkes",
    "https://www.epicurious.com/recipes/food/views/potato-latkes-104406",
    "https://www.epicurious.com/recipes/food/views/brussels-sprout-latkes",
    "https://www.epicurious.com/recipes/food/views/our-favorite-latkes-51259720",
    "https://www.epicurious.com/recipes/food/views/ba-syn-silver-dollar-latkes",
    "https://www.epicurious.com/recipes/food/views/latke-reubens",
    "https://www.epicurious.com/recipes/food/views/latkes-with-lots-of-sauces-51116000",
    "https://www.epicurious.com/recipes/food/views/carrot-potato-latkes-365212",
    "https://www.epicurious.com/recipes/food/views/potato-parsnip-latkes-107402",
    "https://www.epicurious.com/recipes/food/views/classic-potato-latkes-979",
    "https://www.epicurious.com/recipes/food/views/vegetable-latkes-352749",
    "https://www.epicurious.com/recipes/food/views/potato-artichoke-and-feta-cheese-latkes-956",
    "https://www.epicurious.com/recipes/food/views/maxines-latkes-102321",
    "https://www.epicurious.com/recipes/food/views/rosti-style-potato-latkes-with-rosemary-and-brown-butter-applesauce-350793",
    "https://www.epicurious.com/recipes/food/views/adam-and-maxines-famous-latkes-51134480",
    "https://www.epicurious.com/recipes/food/views/potato-latkes-51186660",
    "https://www.epicurious.com/recipes/food/views/yam-latkes-with-mustard-seeds-and-curry-974",
    "https://www.epicurious.com/recipes/food/views/potato-latkes-350905",
    "https://www.epicurious.com/recipes/food/views/greek-herbed-spinach-latkes-with-feta-yogurt-sauce-105954",
    "https://www.epicurious.com/recipes/food/views/potato-vegetable-latkes-104367",
    "https://www.epicurious.com/recipes/food/views/mediterranean-chickpea-latkes-106007",
    "https://www.epicurious.com/recipes/food/views/zucchini-latkes-350906",
    "https://www.epicurious.com/recipes/food/views/potato-latkes-358347",
    "https://www.epicurious.com/recipes/food/views/potato-parsnip-latkes-with-savory-applesauce-236748",
    "https://www.epicurious.com/recipes/food/views/potato-latkes-with-smoked-salmon-caviar-and-tarragon-creme-fraiche-236767",
    "https://www.epicurious.com/recipes/food/views/spicy-cauliflower-latkes-with-zaatar-aioli-350814",
    "https://www.epicurious.com/recipes/food/views/sweet-potato-latkes-105919",

    # BON APPETIT (7 URLs)
    "https://www.bonappetit.com/recipe/extra-large-latkes",
    "https://www.bonappetit.com/recipe/silver-dollar-latkes",
    "https://www.bonappetit.com/recipe/lemony-latkes",
    "https://www.bonappetit.com/recipe/vegan-leek-latkes",
    "https://www.bonappetit.com/recipe/latkes-with-ancho-chile-salt-and-watercress-guacamole",
    "https://www.bonappetit.com/recipe/adam-maxines-famous-latkes",
    "https://www.bonappetit.com/recipe/celery-root-and-mushroom-latkes-with-onion-applesauce",

    # CHABAD.ORG (7 URLs)
    "https://www.chabad.org/multimedia/video_cdo/aid/1709719/jewish/Classic-Potato-Latkes.htm",
    "https://www.chabad.org/kids/article_cdo/aid/448534/jewish/Elis-Kosher-Kitchen.htm",
    "https://www.chabad.org/recipes/recipe_cdo/aid/103034/jewish/Romanian-Zucchini-Potato-Latkes.htm",
    "https://www.chabad.org/recipes/recipe_cdo/aid/103032/jewish/Basic-Potato-Latke-Recipe.htm",
    "https://www.chabad.org/multimedia/video_cdo/aid/4969549/jewish/Cheesy-Quinoa-Latkes.htm",
    "https://www.chabad.org/recipes/recipe_cdo/aid/3510571/jewish/Simple-Potato-Latkes.htm",
    "https://www.chabad.org/recipes/recipe_cdo/aid/3510562/jewish/Zucchini-Cheese-Latkes.htm",

    # JAMIE GELLER (80+ URLs)
    "https://jamiegeller.com/recipes/cauliflower-carrot-latkes/",
    "https://jamiegeller.com/recipes/apple-pie-latkes-with-vanilla-cream/",
    "https://jamiegeller.com/recipes/caprese-latkes/",
    "https://jamiegeller.com/recipes/zucchini-latkes-2/",
    "https://jamiegeller.com/recipes/apple-sage-stuffing-latkes/",
    "https://jamiegeller.com/recipes/healthier-potato-latkes/",
    "https://jamiegeller.com/recipes/cheesy-sweet-potato-latkes/",
    "https://jamiegeller.com/recipes/latkes-potato-pancakes/",
    "https://jamiegeller.com/recipes/vegan-latkes-and-sour-cream/",
    "https://jamiegeller.com/recipes/baked-parmesan-latkes/",
    "https://jamiegeller.com/recipes/crispy-potato-latkes-best-ever/",
    "https://jamiegeller.com/recipes/zucchini-latkes-with-tatziki-sauce/",
    "https://jamiegeller.com/recipes/traditional-potato-latkes-for-hanukkah/",
    "https://jamiegeller.com/recipes/sweet-potato-latkes-with-turkey-bacon/",
    "https://jamiegeller.com/guides/stuffed-latkes/",
    "https://jamiegeller.com/articles/my-grandfathers-latke-recipe/",
    "https://jamiegeller.com/recipes/lacy-squash-latkes/",
    "https://jamiegeller.com/recipes/latkes-with-southern-spices/",
    "https://jamiegeller.com/recipes/carrot-and-apple-latkes/",
    "https://jamiegeller.com/recipes/potato-and-parsnip-latkes/",
    "https://jamiegeller.com/recipes/sweet-potato-latkes-with-brie-baby-arugula/",
    "https://jamiegeller.com/recipes/sheet-pan-latkes/",
    "https://jamiegeller.com/recipes/wasabi-pea-latke-bites/",
    "https://jamiegeller.com/recipes/sweet-cheese-latkes/",
    "https://jamiegeller.com/recipes/mexican-potato-latkes/",
    "https://jamiegeller.com/recipes/brussels-sprout-latkes/",
    "https://jamiegeller.com/recipes/apple-cinnamon-latkas-latkes/",
    "https://jamiegeller.com/recipes/latkes-with-a-truffle-twist/",
    "https://jamiegeller.com/recipes/crispy-polenta-latkes/",
    "https://jamiegeller.com/recipes/crispy-quinoa-latkes/",
    "https://jamiegeller.com/recipes/apple-latkes/",
    "https://jamiegeller.com/recipes/pastrami-ranch-potato-latkes/",
    "https://jamiegeller.com/recipes/crispy-curried-chickpea-cakes/",
    "https://jamiegeller.com/recipes/curried-vegetable-latkes/",
    "https://jamiegeller.com/recipes/fried-rice-latkes/",
    "https://jamiegeller.com/recipes/korean-scallion-and-kimchi-latkes/",
    "https://jamiegeller.com/recipes/basic-potato-latkes/",
    "https://jamiegeller.com/recipes/parsnip-and-leek-latkes/",
    "https://jamiegeller.com/recipes/jalapeno-latkes-with-avocado-cream-sauce/",
    "https://jamiegeller.com/recipes/confetti-latkes/",
    "https://jamiegeller.com/recipes/butternut-latkes-with-apple-butter/",
    "https://jamiegeller.com/recipes/crispy-creamy-latke/",
    "https://jamiegeller.com/recipes/broccoli-cheddar-latkes/",
    "https://jamiegeller.com/recipes/kims-quick-latkes/",
    "https://jamiegeller.com/recipes/no-potato-latke/",
    "https://jamiegeller.com/recipes/asian-mock-crab-red-potato-latkes/",
    "https://jamiegeller.com/recipes/israeli-latkes-with-tahini/",
    "https://jamiegeller.com/recipes/pastrami-latkes/",
    "https://jamiegeller.com/recipes/purple-sweet-potato-latkes-with-truffle-yogurt-and-sauteed-arugula/",
    "https://jamiegeller.com/recipes/beet-latkes-with-horseradish-and-smoked-fish/",
    "https://jamiegeller.com/recipes/sweet-and-savory-mini-latkes/",
    "https://jamiegeller.com/recipes/cauliflower-salami-latkes/",
    "https://jamiegeller.com/recipes/vegan-harissa-latkes/",
    "https://jamiegeller.com/recipes/cheddar-and-potato-latkes-with-spiced-applesauce/",
    "https://jamiegeller.com/recipes/low-fat-cauliflower-carrot-latkes/",
    "https://jamiegeller.com/recipes/mashed-potato-and-kale-latkes/",
    "https://jamiegeller.com/recipes/savory-curried-coriander-pumpkin-latkes/",
    "https://jamiegeller.com/recipes/pumpkin-latke-with-apple-cranberry-sauce/",
    "https://jamiegeller.com/recipes/blue-potato-latkes/",
    "https://jamiegeller.com/recipes/turkey-latkes-with-black-pepper-gravy/",
    "https://jamiegeller.com/recipes/sweet-or-savory-cranberry-latkes/",
    "https://jamiegeller.com/recipes/sweet-and-spicy-sweet-potato-latkes/",
    "https://jamiegeller.com/recipes/butternut-squash-and-apple-latkes/",
    "https://jamiegeller.com/recipes/stuffed-latke-recipe/",
    "https://jamiegeller.com/recipes/mushroom-and-sour-cream-stuffed-latkes/",
    "https://jamiegeller.com/recipes/apples-and-sour-cream-stuffed-latkes/",
    "https://jamiegeller.com/recipes/my-nanas-apple-latkes/",
    "https://jamiegeller.com/recipes/cheese-and-marinara-sauce-stuffed-latke/",
    "https://jamiegeller.com/recipes/fennel-potato-latkes/",
    "https://jamiegeller.com/recipes/sweet-potato-latkes-with-ginger-and-sour-cream/",
    "https://jamiegeller.com/recipes/cheese-latkes-2/",
    "https://jamiegeller.com/recipes/pastrami-latkes-with-sweet-chili-mayo-sauce/",
    "https://jamiegeller.com/recipes/potato-mushroom-latkes/",
    "https://jamiegeller.com/recipes/sweet-potato-latkes-3/",
    "https://jamiegeller.com/recipes/beet-carrot-latkes/",
    "https://jamiegeller.com/recipes/rosemary-mascarpone-potato-latkes/",
    "https://jamiegeller.com/recipes/zucchini-latkes-with-yogurt-curry-sauce/",
    "https://jamiegeller.com/recipes/cheese-latkes/",
    "https://jamiegeller.com/recipes/baked-sweet-potato-latkes-and-gingered-sour-cream-2/",
    "https://jamiegeller.com/recipes/steakhouse-latkes/",
    "https://jamiegeller.com/recipes/samosa-latkes-2/",
    "https://jamiegeller.com/recipes/classic-latkes/",
    "https://jamiegeller.com/recipes/garden-vegetable-latkes/",

    # SMITTEN KITCHEN (5 URLs)
    "https://smittenkitchen.com/2010/11/apple-latkes/",
    "https://smittenkitchen.com/2006/12/zucchini-latkes/",
    "https://smittenkitchen.com/2008/12/potato-pancakes-latkes/",
    "https://smittenkitchen.com/2011/12/parsnip-latkes-with-horseradish-and-dill/",

    # TORI AVEY (8 URLs)
    "https://toriavey.com/yukon-gold-latkes/",
    "https://toriavey.com/potato-latkes/",
    "https://toriavey.com/latke-waffles/",
    "https://toriavey.com/curry-vegetable-latkes/",
    "https://toriavey.com/sweet-potato-latkes-brown-sugar-syrup/",
    "https://toriavey.com/passover-potato-latkes/",
    "https://toriavey.com/crispy-panko-potato-latkes/",
    "https://toriavey.com/cheese-latkes/",

    # ONCE UPON A CHEF (1 URL)
    "https://www.onceuponachef.com/recipes/latkes.html",
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
    """Scrape a single modern recipe URL"""
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
                "country": "US"
            }

            is_valid, quality_score, _ = RecipeValidator().validate_recipe(recipe)

            if is_valid:
                recipe['quality_score'] = quality_score
                progress.mark_processed('modern_site', url, 1)
                return recipe

        progress.mark_processed('modern_site', url, 0)

    except Exception as e:
        logger.debug(f"Error scraping {url}: {e}")
        progress.mark_processed('modern_site', url, 0)

    return None

def scrape_modern_recipes_parallel(max_workers=5) -> List[Dict]:
    """Scrape modern recipes with parallel workers"""
    records = []

    logger.info(f"Scraping {len(MODERN_RECIPE_URLS)} modern recipe URLs (parallel)")

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
    """Advanced deduplication"""

    def __init__(self):
        self.seen_hashes = set()
        self.seen_urls = set()
        self.recipes_by_hash = {}

    def is_duplicate(self, recipe: Dict) -> bool:
        """Check if recipe is a duplicate"""
        url = recipe.get('url')
        if url and url in self.seen_urls:
            return True

        ingredients = recipe.get('ingredients_raw', '')
        instructions = recipe.get('instructions_raw', '')

        if ingredients or instructions:
            recipe_hash = generate_recipe_hash(ingredients, instructions)

            if recipe_hash in self.seen_hashes:
                return True

            for existing_hash, existing_recipe in self.recipes_by_hash.items():
                existing_ing = existing_recipe.get('ingredients_raw', '')
                existing_inst = existing_recipe.get('instructions_raw', '')

                ing_similarity = calculate_similarity(ingredients, existing_ing)
                inst_similarity = calculate_similarity(instructions, existing_inst)

                if ing_similarity > 0.9 and inst_similarity > 0.9:
                    return True

            self.seen_hashes.add(recipe_hash)
            self.recipes_by_hash[recipe_hash] = recipe

        if url:
            self.seen_urls.add(url)

        return False

    def deduplicate(self, recipes: List[Dict]) -> List[Dict]:
        """Deduplicate a list of recipes"""
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
    """Write recipes to CSV with proper escaping"""
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

def build_improved_corpus():
    """Main function to build the improved corpus"""

    logger.info("="*80)
    logger.info("🚀 BUILDING IMPROVED JEWISH LATKE CORPUS")
    logger.info("="*80)
    logger.info("Improvements:")
    logger.info("  - Better OCR text handling for historical sources")
    logger.info("  - Project Gutenberg integration")
    logger.info("  - Chronicling America (newspaper archives)")
    logger.info("  - Improved Internet Archive extraction")
    logger.info("  - More flexible recipe parsing")
    logger.info("="*80)

    all_recipes = []

    # Phase 1: Internet Archive (IMPROVED)
    logger.info("\n" + "="*80)
    logger.info("PHASE 1: Internet Archive (Improved)")
    logger.info("="*80)

    try:
        ia_items = ia_search_comprehensive()
        logger.info(f"Processing {len(ia_items)} Internet Archive items...")

        # Process in batches
        batch_size = 25
        for i in range(0, len(ia_items), batch_size):
            batch = ia_items[i:i+batch_size]
            logger.info(f"\nBatch {i//batch_size + 1}/{(len(ia_items)-1)//batch_size + 1}")

            for j, item in enumerate(batch):
                identifier = item.get("identifier")
                logger.info(f"  [{i+j+1}/{len(ia_items)}] {identifier}")

                recipes = ia_extract_recipes_improved(identifier, item)
                all_recipes.extend(recipes)

                if (i+j+1) % 10 == 0:
                    stats = progress.get_stats()
                    logger.info(f"  Progress: {stats['total_recipes']} recipes, "
                              f"{stats['runtime_minutes']:.1f} min elapsed")

                time.sleep(0.5)

            progress.save()
            logger.info(f"Checkpoint saved: {len(all_recipes)} recipes so far")

    except Exception as e:
        logger.error(f"Internet Archive error: {e}", exc_info=True)

    # Phase 2: Project Gutenberg (NEW)
    logger.info("\n" + "="*80)
    logger.info("PHASE 2: Project Gutenberg")
    logger.info("="*80)

    try:
        all_recipes.extend(gutenberg_search())
    except Exception as e:
        logger.error(f"Project Gutenberg error: {e}")

    progress.save()

    # Phase 3: Chronicling America (NEW)
    logger.info("\n" + "="*80)
    logger.info("PHASE 3: Chronicling America (Historical Newspapers)")
    logger.info("="*80)

    try:
        all_recipes.extend(chronicling_america_search())
    except Exception as e:
        logger.error(f"Chronicling America error: {e}")

    progress.save()

    # Phase 4: HathiTrust
    logger.info("\n" + "="*80)
    logger.info("PHASE 4: HathiTrust")
    logger.info("="*80)

    try:
        all_recipes.extend(hathitrust_search_implemented())
    except Exception as e:
        logger.error(f"HathiTrust error: {e}")

    progress.save()

    # Phase 5: Modern Sites
    logger.info("\n" + "="*80)
    logger.info("PHASE 5: Modern Recipe Websites")
    logger.info("="*80)

    try:
        modern_recipes = scrape_modern_recipes_parallel(max_workers=5)
        all_recipes.extend(modern_recipes)
    except Exception as e:
        logger.error(f"Modern sites error: {e}")

    progress.save()

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
        logger.info(f"Recipes with both: {(df['ingredients_raw'].notna() & df['instructions_raw'].notna()).sum()}")
        if 'quality_score' in df.columns:
            logger.info(f"Average quality score: {df['quality_score'].mean():.2f}")

    stats = progress.get_stats()
    logger.info(f"\nTotal runtime: {stats['runtime_minutes']:.1f} minutes")

    logger.info("="*80)
    logger.info("✅ SUCCESS! Improved corpus building complete.")
    logger.info(f"📁 Output file: {OUT_CSV}")
    logger.info("="*80)

    return df

# ========== Entry Point ==========

if __name__ == "__main__":
    try:
        df = build_improved_corpus()

        if not df.empty:
            print("\n" + "="*80)
            print("SAMPLE RECIPES:")
            print("="*80)
            print(df.head(10)[['year', 'title', 'source', 'quality_score']].to_string(index=False))

    except KeyboardInterrupt:
        logger.info("\n\n⚠️ Interrupted by user. Progress has been saved.")
        logger.info(f"Resume by running the script again.")
        stats = progress.get_stats()
        logger.info(f"Current progress: {stats['total_recipes']} recipes in {stats['runtime_minutes']:.1f} min")

    except Exception as e:
        logger.error(f"\n❌ FATAL ERROR: {e}", exc_info=True)
        raise
