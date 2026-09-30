import sys
sys.stdout.reconfigure(encoding="utf-8")
"""One-time: create the 3 tabs + headers.  Run: python setup_sheets.py"""
from sheets import SheetsClient

if __name__ == "__main__":
    for action in SheetsClient().ensure_structure():
        print("✓", action)
