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
print("🔍 Available Gemini models:\n")

for model in genai.list_models():
    if 'generateContent' in model.supported_generation_methods:
        print(f"✓ {model.name}")
        print(f"  Display name: {model.display_name}")
        print(f"  Description: {model.description}")
        print()

# Test a simple generation with the first available model
print("\n🧪 Testing generation with first available model...\n")

try:
    # Try the most common model names
    model_names_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-pro',
        'gemini-pro',
        'models/gemini-1.5-flash',
        'models/gemini-1.5-pro',
        'models/gemini-pro'
    ]

    for model_name in model_names_to_try:
        try:
            print(f"Trying: {model_name}...", end=" ")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Say 'hello' in one word")
            print(f"✓ WORKS! Response: {response.text.strip()}")
            print(f"\n✅ USE THIS MODEL NAME: {model_name}\n")
            break
        except Exception as e:
            print(f"✗ {str(e)[:80]}")

except Exception as e:
    print(f"❌ Error: {e}")
