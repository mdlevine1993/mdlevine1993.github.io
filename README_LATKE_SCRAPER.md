# NY Times Latke Recipe Scraper

A Python script that uses [Apify's NY Times Cooking Scraper API](https://apify.com/harvest/nyt-cooking-scraper) to extract latke recipes from the New York Times Cooking website.

## Features

- Automatically searches for latke-related recipes using multiple search queries
- Extracts comprehensive recipe information including:
  - **Recipe title**
  - **Recipe author**
  - **Published date** (prioritized)
  - **Ingredients list** (prioritized)
  - **Instructions**
  - Additional metadata (prep time, cook time, yield, ratings, etc.)
- Filters results to ensure only latke-related recipes are included
- Exports data to both JSON and CSV formats
- Handles structured recipe data with proper formatting

## Prerequisites

1. **Python 3.7+**
2. **Apify Account and API Token**
   - Sign up for free at [Apify Console](https://console.apify.com/)
   - Get your API token from [Integrations](https://console.apify.com/account/integrations)
   - The free tier includes $5 of platform credits per month

## Installation

1. Install the required Python packages:

```bash
pip install -r requirements_latke_scraper.txt
```

Or install individually:

```bash
pip install apify-client pandas
```

2. Set your Apify API token as an environment variable:

```bash
export APIFY_API_TOKEN='your_api_token_here'
```

On Windows (Command Prompt):
```cmd
set APIFY_API_TOKEN=your_api_token_here
```

On Windows (PowerShell):
```powershell
$env:APIFY_API_TOKEN="your_api_token_here"
```

## Usage

Run the script:

```bash
python nyt_latke_scraper.py
```

The script will:
1. Generate search URLs for latke-related queries
2. Run the Apify scraper on those URLs
3. Extract and format recipe data
4. Filter for latke-specific recipes
5. Save results to timestamped JSON and CSV files

## Output Files

The script generates two output files with timestamps:

- `nyt_latke_recipes_YYYYMMDD_HHMMSS.json` - Complete recipe data in JSON format
- `nyt_latke_recipes_YYYYMMDD_HHMMSS.csv` - Flattened recipe data for spreadsheet analysis

## Output Fields

Each recipe includes the following fields:

| Field | Description | Priority |
|-------|-------------|----------|
| `title` | Recipe name | High |
| `author` | Recipe author | Medium |
| `published_date` | Publication date | **High** |
| `ingredients` | List of ingredients (newline-separated) | **High** |
| `ingredients_list` | Ingredients as array (JSON only) | **High** |
| `instructions` | Step-by-step instructions | High |
| `url` | Recipe URL | Medium |
| `description` | Recipe description | Low |
| `prep_time` | Preparation time | Low |
| `cook_time` | Cooking time | Low |
| `total_time` | Total time | Low |
| `yield` | Servings/yield | Medium |
| `rating` | User rating | Low |

## Customization

### Adding More Search Queries

Edit the `generate_search_urls()` method in the script:

```python
search_queries = [
    "latke",
    "latkes",
    "potato latke",
    "potato pancake",
    "hanukkah latke",
    # Add your own queries here
    "sweet potato latke",
    "zucchini latke",
]
```

### Adding Specific Recipe URLs

If you know specific recipe URLs, add them directly:

```python
urls = self.generate_search_urls()
urls.append("https://cooking.nytimes.com/recipes/1016071-classic-potato-latkes")
urls.append("https://cooking.nytimes.com/recipes/YOUR-RECIPE-ID")
```

### Adjusting Request Limits

Modify the `maxRequestsPerCrawl` parameter to scrape more or fewer pages:

```python
run_input = {
    "startUrls": [{"url": url} for url in urls],
    "maxRequestsPerCrawl": 200,  # Increase for more results
    # ...
}
```

## Cost Considerations

- The Apify free tier includes $5/month in platform credits
- The NY Times Cooking Scraper costs approximately $0.25 per 1000 pages scraped
- A typical run of this script uses minimal credits (usually under $0.50)
- Monitor your usage at [Apify Console](https://console.apify.com/)

## Troubleshooting

### "Apify API token is required" Error

Make sure you've set the `APIFY_API_TOKEN` environment variable correctly:

```bash
echo $APIFY_API_TOKEN  # Should print your token
```

### No Results Found

- Check that the NY Times Cooking website structure hasn't changed
- Try running with specific recipe URLs instead of search URLs
- Verify your search queries are returning results on the NYT Cooking website

### Rate Limiting

If you encounter rate limiting:
- Reduce `maxRequestsPerCrawl` in the script
- Add delays between runs
- Check your Apify account for any usage limits

## Example Output

```
============================================================
NY Times Latke Recipe Scraper
============================================================

Generated 5 search URLs:
  - https://cooking.nytimes.com/search?q=latke
  - https://cooking.nytimes.com/search?q=latkes
  ...

============================================================
Running Apify actor: harvest/nyt-cooking-scraper
This may take a few minutes...
Scrape complete! Dataset ID: xxxxx
Retrieved 45 items from the dataset

============================================================
Extracting recipe fields...

============================================================
Filtering for latke-related recipes...
Filtered to 23 latke-related recipes

============================================================
Found 23 latke recipes!
============================================================

Recipe Titles:
1. Classic Potato Latkes
   Author: Joan Nathan
   Published: 2014-12-05
   Ingredients: 8 items

2. Sweet Potato Latkes
   Author: Martha Rose Shulman
   Published: 2010-11-15
   Ingredients: 10 items
...
```

## API Documentation

- [Apify NY Times Cooking Scraper](https://apify.com/harvest/nyt-cooking-scraper)
- [Apify Python Client Documentation](https://docs.apify.com/api/client/python)
- [NY Times Cooking Website](https://cooking.nytimes.com/)

## License

This script is provided as-is for educational and personal use. Please respect the NY Times Cooking website's terms of service and rate limits.

## Notes

- This script requires an active internet connection
- Scraping may take several minutes depending on the number of URLs
- Results are cached by Apify, so repeat runs may be faster
- The quality of results depends on the NY Times Cooking website structure
