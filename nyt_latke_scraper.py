#!/usr/bin/env python3
"""
NY Times Latke Recipe Scraper using Apify API

This script uses Apify's NY Times Cooking Scraper to extract latke recipes
from the NY Times Cooking website. It focuses on extracting:
- Recipe title
- Recipe author
- Recipe published date (high priority)
- Ingredients list (high priority)
- Instructions

Usage:
    1. Install dependencies: pip install apify-client pandas
    2. Set your Apify API token as an environment variable:
       export APIFY_API_TOKEN='your_token_here'
    3. Run the script: python nyt_latke_scraper.py
"""

import os
import json
import csv
from datetime import datetime
from typing import List, Dict, Any, Optional

# Check for required dependencies
try:
    from apify_client import ApifyClient
except ImportError:
    print("ERROR: apify-client is not installed!")
    print("\nPlease install it using:")
    print("  pip install apify-client")
    print("\nOr install all dependencies:")
    print("  pip install apify-client pandas")
    raise


class NYTLatkeRecipeScraper:
    """Scraper for NY Times latke recipes using Apify API."""

    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize the scraper with Apify API token.

        Args:
            api_token: Apify API token. If None, reads from APIFY_API_TOKEN env var.
        """
        self.api_token = api_token or os.getenv('APIFY_API_TOKEN')
        if not self.api_token:
            raise ValueError(
                "Apify API token is required. Set APIFY_API_TOKEN environment "
                "variable or pass it to the constructor."
            )

        self.client = ApifyClient(self.api_token)
        self.actor_id = "harvest/nyt-cooking-scraper"

    def generate_recipe_urls(self) -> List[str]:
        """
        Generate NY Times Cooking recipe URLs for latke recipes.

        NOTE: The Apify scraper requires specific recipe URLs, not search URLs.
        Add known latke recipe URLs here.

        Returns:
            List of recipe URLs to scrape
        """
        # Known NYT Cooking latke recipe URLs
        # Add more URLs as you find them on cooking.nytimes.com
        urls = [
            "https://cooking.nytimes.com/recipes/1016071-classic-potato-latkes",
            "https://cooking.nytimes.com/recipes/1018039-sweet-potato-latkes",
            "https://cooking.nytimes.com/recipes/1017325-potato-latkes",
            "https://cooking.nytimes.com/recipes/1014654-carrot-and-sweet-potato-latkes",
            "https://cooking.nytimes.com/recipes/1020570-zucchini-latkes",
            "https://cooking.nytimes.com/recipes/1013987-latkes",
            "https://cooking.nytimes.com/recipes/1017326-apple-latkes",
            "https://cooking.nytimes.com/recipes/1019605-cauliflower-latkes",
            "https://cooking.nytimes.com/recipes/1014655-butternut-squash-latkes",
            "https://cooking.nytimes.com/recipes/1016072-scallion-latkes",
        ]

        return urls

    def scrape_recipes(self, urls: List[str]) -> List[Dict[str, Any]]:
        """
        Scrape recipes from the provided URLs using Apify.

        The NYT Cooking Scraper processes one URL at a time, so we'll
        run it multiple times and collect all results.

        Args:
            urls: List of NY Times Cooking recipe URLs to scrape

        Returns:
            List of recipe dictionaries with extracted data
        """
        print(f"Starting scrape with {len(urls)} recipe URLs...")
        print("Note: The scraper will process each recipe one at a time.")
        print()

        all_items = []

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Scraping: {url}")

            # Prepare the input for the Apify actor (one URL at a time)
            run_input = {
                "url": url,
            }

            try:
                # Run the actor and wait for it to finish
                run = self.client.actor(self.actor_id).call(run_input=run_input)

                # Get the dataset ID
                dataset_id = run["defaultDatasetId"]

                # Fetch items from the dataset
                for item in self.client.dataset(dataset_id).iterate_items():
                    all_items.append(item)
                    print(f"  ✓ Successfully scraped: {item.get('name', 'Unknown recipe')}")

            except Exception as e:
                print(f"  ✗ Error scraping this URL: {e}")
                continue

        print()
        print(f"Scrape complete! Retrieved {len(all_items)} recipes total")
        return all_items

    def extract_recipe_fields(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract and format the required fields from raw scraped data.

        Args:
            raw_data: Raw data from Apify scraper

        Returns:
            List of formatted recipe dictionaries
        """
        recipes = []

        for item in raw_data:
            # Extract the fields we care about
            recipe = {
                'title': item.get('name') or item.get('title', 'N/A'),
                'author': item.get('author', 'N/A'),
                'published_date': item.get('datePublished') or item.get('publishedDate', 'N/A'),
                'ingredients': item.get('recipeIngredient') or item.get('ingredients', []),
                'instructions': item.get('recipeInstructions') or item.get('instructions', 'N/A'),
                'url': item.get('url', 'N/A'),
                'description': item.get('description', 'N/A'),
                'prep_time': item.get('prepTime', 'N/A'),
                'cook_time': item.get('cookTime', 'N/A'),
                'total_time': item.get('totalTime', 'N/A'),
                'yield': item.get('recipeYield') or item.get('yield', 'N/A'),
                'rating': item.get('aggregateRating', {}).get('ratingValue', 'N/A') if isinstance(item.get('aggregateRating'), dict) else 'N/A',
            }

            # Format instructions if they're in a structured format
            if isinstance(recipe['instructions'], list):
                instructions_text = []
                for i, instruction in enumerate(recipe['instructions'], 1):
                    if isinstance(instruction, dict):
                        text = instruction.get('text', '')
                    else:
                        text = str(instruction)
                    if text:
                        instructions_text.append(f"{i}. {text}")
                recipe['instructions'] = '\n'.join(instructions_text)

            # Format ingredients list
            if isinstance(recipe['ingredients'], list):
                # Handle case where ingredients might be dictionaries or strings
                ingredients_text = []
                for ing in recipe['ingredients']:
                    if isinstance(ing, dict):
                        # Extract text from dictionary (could be 'text', 'ingredient', or the whole dict as string)
                        text = ing.get('text') or ing.get('ingredient') or str(ing)
                    else:
                        text = str(ing)
                    if text:
                        ingredients_text.append(text)

                recipe['ingredients_list'] = ingredients_text
                recipe['ingredients'] = '\n'.join(ingredients_text)
            else:
                recipe['ingredients_list'] = [str(recipe['ingredients'])]
                recipe['ingredients'] = str(recipe['ingredients'])

            recipes.append(recipe)

        return recipes

    def filter_latke_recipes(self, recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter recipes to only include those related to latkes.

        Args:
            recipes: List of all scraped recipes

        Returns:
            List of recipes containing latke-related keywords
        """
        latke_keywords = ['latke', 'latkes', 'potato pancake']

        filtered_recipes = []
        for recipe in recipes:
            title = recipe.get('title', '').lower()
            description = recipe.get('description', '').lower()
            ingredients = recipe.get('ingredients', '').lower()

            # Check if any latke keyword appears in title, description, or ingredients
            if any(keyword in title or keyword in description or keyword in ingredients
                   for keyword in latke_keywords):
                filtered_recipes.append(recipe)

        print(f"Filtered to {len(filtered_recipes)} latke-related recipes")
        return filtered_recipes

    def save_to_json(self, recipes: List[Dict[str, Any]], filename: str = None):
        """Save recipes to JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"nyt_latke_recipes_{timestamp}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(recipes, f, indent=2, ensure_ascii=False)

        print(f"Saved {len(recipes)} recipes to {filename}")

    def save_to_csv(self, recipes: List[Dict[str, Any]], filename: str = None):
        """Save recipes to CSV file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"nyt_latke_recipes_{timestamp}.csv"

        if not recipes:
            print("No recipes to save to CSV")
            return

        # Define the fields to include in CSV (flatten the structure)
        fieldnames = [
            'title', 'author', 'published_date', 'url', 'description',
            'ingredients', 'instructions', 'prep_time', 'cook_time',
            'total_time', 'yield', 'rating'
        ]

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(recipes)

        print(f"Saved {len(recipes)} recipes to {filename}")

    def run(self):
        """Main method to run the complete scraping workflow."""
        print("=" * 60)
        print("NY Times Latke Recipe Scraper")
        print("=" * 60)

        # Generate recipe URLs
        urls = self.generate_recipe_urls()
        print(f"\nFound {len(urls)} latke recipe URLs to scrape:")
        for url in urls:
            print(f"  - {url}")

        # Scrape recipes
        print("\n" + "=" * 60)
        raw_data = self.scrape_recipes(urls)

        # Extract and format recipe fields
        print("\n" + "=" * 60)
        print("Extracting recipe fields...")
        recipes = self.extract_recipe_fields(raw_data)

        # Since we're using specific latke URLs, filtering is optional
        # but we'll keep it to verify the recipes are latke-related
        print("\n" + "=" * 60)
        print("Verifying latke-related recipes...")
        latke_recipes = self.filter_latke_recipes(recipes)

        # If filter removed everything, just use all recipes
        if not latke_recipes and recipes:
            print("Warning: Filter removed all recipes. Using all scraped recipes.")
            latke_recipes = recipes

        # Display summary
        print("\n" + "=" * 60)
        print(f"Found {len(latke_recipes)} latke recipes!")
        print("=" * 60)

        if latke_recipes:
            print("\nRecipe Titles:")
            for i, recipe in enumerate(latke_recipes, 1):
                print(f"{i}. {recipe['title']}")
                print(f"   Author: {recipe['author']}")
                print(f"   Published: {recipe['published_date']}")
                print(f"   Ingredients: {len(recipe.get('ingredients_list', []))} items")
                print()

        # Save results
        print("=" * 60)
        print("Saving results...")
        self.save_to_json(latke_recipes)
        self.save_to_csv(latke_recipes)

        print("\n" + "=" * 60)
        print("Scraping complete!")
        print("=" * 60)

        return latke_recipes


def main():
    """Main entry point for the script."""
    try:
        # For Spyder users: You can set your API token here directly
        # Uncomment the line below and add your token:
        # os.environ['APIFY_API_TOKEN'] = 'your_api_token_here'

        scraper = NYTLatkeRecipeScraper()
        recipes = scraper.run()

        print(f"\nTotal latke recipes found: {len(recipes)}")

    except ValueError as e:
        print(f"Error: {e}")
        print("\nTo use this script, you need an Apify API token.")
        print("Get one at: https://console.apify.com/account/integrations")
        print("\n=== For Spyder users ===")
        print("Add this line at the top of main() function (around line 293):")
        print("  os.environ['APIFY_API_TOKEN'] = 'your_api_token_here'")
        print("\n=== For terminal users ===")
        print("Set it as an environment variable:")
        print("  export APIFY_API_TOKEN='your_token_here'")
        return 1

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    # Don't use exit() as it can restart Spyder's kernel
    main()
