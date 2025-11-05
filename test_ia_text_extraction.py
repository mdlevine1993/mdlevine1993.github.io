#!/usr/bin/env python3
"""Test Internet Archive text extraction"""

import requests

def fetch(url, timeout=30):
    """Simple fetch wrapper"""
    try:
        r = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return r
    except:
        return None

def ia_get_full_text(identifier: str):
    """Get full text from Internet Archive"""

    # First, get metadata to find available text files
    try:
        metadata_url = f"https://archive.org/metadata/{identifier}"
        r = fetch(metadata_url, timeout=30)
        if r and r.status_code == 200:
            metadata = r.json()
            files = metadata.get('files', [])

            # Look for text files in the metadata
            text_files = []
            for file in files:
                name = file.get('name', '').lower()
                if name.endswith('.txt') or '_djvu.txt' in name or '_text.txt' in name:
                    text_files.append(file.get('name'))

            print(f"Found {len(text_files)} text files: {text_files[:3]}")

            # Try each text file found
            for filename in text_files:
                url = f"https://archive.org/download/{identifier}/{filename}"
                try:
                    print(f"  Trying: {filename}...")
                    r = fetch(url, timeout=60)
                    if r and r.text and len(r.text) > 500 and not r.text.startswith('<html'):
                        print(f"  ✓ SUCCESS with {filename}")
                        return r.text
                    else:
                        print(f"    ✗ Failed (len={len(r.text) if r else 0})")
                except Exception as e:
                    print(f"    ✗ Error: {e}")
                    continue
    except Exception as e:
        print(f"Metadata lookup failed: {e}")

    return None

# Test with union-cook-book
print("Testing union-cook-book:")
print("=" * 60)
text = ia_get_full_text('union-cook-book')

if text:
    print(f"\n✓ Got text! Length: {len(text)}")
    print(f"Contains 'latke': {'latke' in text.lower()}")
    print(f"Contains 'potato': {'potato' in text.lower()}")
    print("\nFirst 500 chars:")
    print(text[:500])
else:
    print("\n✗ Failed to get text")

# Test with the one that worked: jewishcookingfor00levy
print("\n\nTesting jewishcookingfor00levy (the one that worked):")
print("=" * 60)
text2 = ia_get_full_text('jewishcookingfor00levy')

if text2:
    print(f"\n✓ Got text! Length: {len(text2)}")
    print(f"Contains 'latke': {'latke' in text2.lower()}")
    print(f"Contains 'potato': {'potato' in text2.lower()}")
else:
    print("\n✗ Failed to get text")
