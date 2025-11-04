# Gemini-Powered Latke Recipe Scraper - Setup Guide

## Overview

This improved scraper uses **Google Gemini AI** to parse messy OCR text from historical sources while keeping fast JSON-LD parsing for modern sites.

**Key Benefits:**
- ✅ **Accurate parsing** of historical OCR text (no more garbage in CSV)
- ✅ **Free tier**: 1,500 requests/day (plenty for this project)
- ✅ **Smart validation** rejects bad extractions
- ✅ **Rate limiting** stays within free tier
- ✅ **Fast modern parsing** unchanged (no LLM needed)

## Quick Start (5 minutes)

### Step 1: Install Dependencies

```bash
pip install google-generativeai requests beautifulsoup4 pandas
```

### Step 2: Get Free Gemini API Key

1. Go to: https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy your key

### Step 3: Set API Key

**Option A: Environment Variable (Recommended)**
```bash
export GEMINI_API_KEY='your-api-key-here'
```

**Option B: Edit Script**
Open `latke_scraper_gemini.py` and replace:
```python
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
```
with:
```python
GEMINI_API_KEY = "your-actual-api-key-here"
```

### Step 4: Add Your Modern Recipe URLs

The script includes 3 sample URLs. Replace `MODERN_RECIPE_URLS` with your full list of 285+ URLs:

```python
MODERN_RECIPE_URLS = [
    # ALLRECIPES
    "https://www.allrecipes.com/recipe/16073/potato-latkes-i/",
    "https://www.allrecipes.com/recipe/235052/moms-potato-latkes/",
    # ... add all your URLs
]
```

### Step 5: Run!

```bash
python latke_scraper_gemini.py
```

## How It Works

### Modern Sites (Fast - No LLM)
- Uses existing JSON-LD structured data parsing
- No API calls needed
- Same quality as before
- ~200-300 recipes

### Historical Sources (Gemini AI)
- Sends OCR text to Gemini API
- Gemini extracts recipe in JSON format
- Validates output (rejects garbage)
- ~400-600 recipes from Internet Archive

## Sample Output

**Before (Broken):**
```csv
title: "Latke Recipe from Just a few tried and true receipts : being a manuscript..."
ingredients_raw: ""
instructions_raw: "CORNELL UNIVERSITY LIBRARY... [entire book dumped here]"
```

**After (Gemini):**
```csv
title: "Potato Latkes"
ingredients_raw: "4 potatoes, grated
1 onion, chopped
2 eggs
Salt and pepper"
instructions_raw: "Grate potatoes and squeeze dry.
Mix with eggs and onion.
Fry in hot oil until golden brown."
```

## Rate Limits & Costs

### Free Tier Limits
- **15 requests/minute**
- **1,500 requests/day**
- **1M requests/month**

### Expected Usage
- **Modern sites**: 0 API calls (uses JSON-LD)
- **Internet Archive**: ~100-300 API calls (one per book)
- **Project Gutenberg**: ~20-40 API calls
- **Total**: ~150-400 calls

**You're well within the free tier!** Even if you process 500 books, that's only 1/3 of your daily limit.

## Script Features

### Rate Limiting
```python
# Automatically waits if hitting limits
gemini_limiter = RateLimiter(GEMINI_RPM_LIMIT)
```

### Validation
```python
def validate_recipe_data(recipe: Dict):
    # Rejects:
    # - Title > 200 chars (likely book title)
    # - Contains "CORNELL UNIVERSITY" etc. (metadata)
    # - Instructions > 5000 chars (entire book)
    # - No measurements in ingredients
    # - OCR garbage patterns
```

### Resume Capability
```python
# Checkpoint saved every 5 minutes
# If interrupted, just run again - it resumes where it left off
```

### Progress Tracking
```bash
# Creates latke_corpus_progress_gemini.json:
{
  "total_recipes": 450,
  "by_source": {
    "modern_site": 250,
    "internet_archive": 200
  },
  "runtime_minutes": 45.2,
  "gemini_calls": 180
}
```

## Configuration Options

### Change Rate Limits
```python
# In script config section:
GEMINI_RPM_LIMIT = 15  # Requests per minute
GEMINI_DAILY_LIMIT = 1500  # Daily limit
```

### Change Max Text Sent to Gemini
```python
# Sends max 15,000 chars per book to save tokens
max_chars = 15000  # Adjust if needed
```

### Limit Internet Archive Items (for testing)
```python
# In build_corpus_with_gemini():
for i in range(0, min(len(ia_items), 100), batch_size):  # Change 100 to process more
```

## Testing First

Before processing hundreds of books, test with a small batch:

```python
# In the script, change:
for i in range(0, min(len(ia_items), 100), batch_size):
# To:
for i in range(0, min(len(ia_items), 5), batch_size):  # Test with 5 books
```

Run it and check the output CSV. If results look good, increase the limit.

## Troubleshooting

### "GEMINI_API_KEY not set"
- Make sure you exported the environment variable OR edited the script
- Restart your terminal after setting the variable

### "Invalid API Key"
- Regenerate key at https://aistudio.google.com/app/apikey
- Make sure you copied the entire key (no spaces)

### "Quota exceeded"
- You hit the daily limit (1,500 requests)
- Wait until tomorrow or upgrade to paid tier
- Script automatically saves progress - just resume tomorrow

### "No recipes found"
- The book might not contain latke recipes
- Check the log file: `latke_corpus_gemini.log`
- Gemini may have decided the text doesn't contain latke recipes

### "Invalid JSON from Gemini"
- Rare, but Gemini sometimes formats JSON incorrectly
- Script logs the invalid response
- Will skip that book and continue

## Output Files

1. **jewish_latke_corpus_gemini.csv** - Final recipe corpus
2. **latke_corpus_gemini.log** - Detailed logs
3. **latke_corpus_progress_gemini.json** - Progress stats (human-readable)
4. **latke_corpus_checkpoint_gemini.pkl** - Resume data (binary)

## Comparing Results

### Original Script (Broken for Historical)
- Modern sites: ✅ 200-300 recipes
- Internet Archive: ❌ Garbage data
- **Total usable: ~200-300**

### Gemini Script
- Modern sites: ✅ 200-300 recipes (unchanged)
- Internet Archive: ✅ 200-400 quality recipes
- Project Gutenberg: ✅ 10-30 recipes
- **Total usable: ~450-750**

## Cost Analysis

### Free Tier (What You're Using)
- **Cost**: $0
- **Limit**: 1,500 requests/day
- **Your usage**: ~150-400 requests
- **Verdict**: ✅ Perfect fit!

### If You Needed More (You Don't)
- Paid tier: ~$0.001 per request
- 1,000 books: ~$1
- Still very cheap!

## Example Gemini Prompt

Here's what gets sent to Gemini for each book:

```
You are a recipe extraction expert. Extract ALL latke (potato pancake)
recipes from the following OCR text from a historical cookbook.

For each latke recipe found, extract:
1. Recipe title/name
2. Ingredients list
3. Instructions

Return ONLY valid JSON:
{
  "recipes": [
    {
      "title": "Recipe name",
      "ingredients": ["ingredient 1", "ingredient 2"],
      "instructions": ["step 1", "step 2"]
    }
  ]
}

Rules:
- Only extract LATKE recipes
- Skip non-latke dishes
- If no recipes found: {"recipes": []}
- Do NOT invent recipes

OCR Text:
[book text here]
```

## Best Practices

1. **Start small** - Test with 5-10 books first
2. **Check the CSV** - Verify results look good
3. **Monitor progress.json** - Watch Gemini call count
4. **Save your API key** - Don't commit it to git!
5. **Use environment variable** - Safer than hardcoding

## Advanced: Switching to Ollama (Local)

If you want to avoid API calls entirely, you can use Ollama (runs locally):

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model
ollama pull llama3.2:3b

# Modify script to use Ollama instead of Gemini
# (I can provide this if you want)
```

**Tradeoff:** Slower, uses your GPU/CPU, but 100% free and private.

## Questions?

1. **How long will it take?**
   - Modern sites: ~5-10 minutes
   - Internet Archive (100 books): ~30-60 minutes
   - Total: ~45-70 minutes

2. **Can I stop and resume?**
   - Yes! Checkpoint saved every 5 minutes
   - Just run the script again

3. **What if I hit the daily limit?**
   - Script stops automatically
   - Progress is saved
   - Resume tomorrow

4. **Is my API key safe?**
   - Use environment variable (not hardcoded)
   - Don't commit to git
   - Regenerate if exposed

## Success Checklist

- [ ] Installed: `google-generativeai`, `requests`, `beautifulsoup4`, `pandas`
- [ ] Got Gemini API key from https://aistudio.google.com/app/apikey
- [ ] Set `GEMINI_API_KEY` environment variable
- [ ] Added all 285+ modern recipe URLs to script
- [ ] Tested with 5 books first
- [ ] Checked CSV output looks good
- [ ] Running full corpus build

## Next Steps

After running the script:

1. **Review the CSV** - Check for quality
2. **Check logs** - Look for any errors
3. **Analyze statistics** - See breakdown by source
4. **Iterate if needed** - Adjust prompts or validation

Good luck! 🎉
