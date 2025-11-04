#!/usr/bin/env python3
"""
Quick test to see what Gemini models are available with your API key
"""

import os
import google.generativeai as genai

# Get API key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
    print("❌ Please set GEMINI_API_KEY environment variable")
    exit(1)

# Configure
genai.configure(api_key=GEMINI_API_KEY)

# List available models
print("🔍 Listing ALL available Gemini models:\n")

available_models = []
try:
    for model in genai.list_models():
        print(f"Model: {model.name}")
        print(f"  Display name: {model.display_name}")
        print(f"  Supported methods: {model.supported_generation_methods}")
        print()

        if 'generateContent' in model.supported_generation_methods:
            available_models.append(model.name)
except Exception as e:
    print(f"❌ Error listing models: {e}")
    print("\nTrying alternative approach...\n")

print(f"\n📋 Models that support generateContent: {len(available_models)}")
for model_name in available_models:
    print(f"  - {model_name}")
print()

# Test available models
print("\n🧪 Testing available models...\n")

if available_models:
    print(f"Testing models found from list_models():\n")
    for model_name in available_models[:3]:  # Test first 3
        try:
            print(f"Trying: {model_name}...", end=" ")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Say 'hello' in one word")
            print(f"✓ WORKS! Response: {response.text.strip()}")
            print(f"\n✅ USE THIS MODEL NAME IN YOUR SCRAPER: {model_name}\n")
            break
        except Exception as e:
            print(f"✗ {str(e)[:80]}")
else:
    print("No models found from list_models(). Trying common names:\n")

    # Try common model names with different prefixes
    model_names_to_try = [
        'gemini-1.5-flash-001',
        'gemini-1.5-pro-001',
        'gemini-pro-vision',
        'gemini-1.0-pro',
        'models/gemini-1.5-flash-001',
        'models/gemini-1.5-pro-001',
        'models/gemini-pro-vision',
        'models/gemini-1.0-pro'
    ]

    for model_name in model_names_to_try:
        try:
            print(f"Trying: {model_name}...", end=" ")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Say 'hello' in one word")
            print(f"✓ WORKS! Response: {response.text.strip()}")
            print(f"\n✅ USE THIS MODEL NAME IN YOUR SCRAPER: {model_name}\n")
            break
        except Exception as e:
            print(f"✗ {str(e)[:80]}")

print("\n" + "="*80)
print("RECOMMENDATION:")
print("="*80)
print("If all models failed, your API key might:")
print("  1. Need to enable the Gemini API in Google Cloud Console")
print("  2. Be from an older API Studio version")
print("  3. Need regeneration")
print("\nTry regenerating your API key at: https://aistudio.google.com/app/apikey")
print("="*80)
