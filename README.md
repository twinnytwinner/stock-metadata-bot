# stock-metadata-bot

Generates a title, description and up to 50 keywords for stock photos with Claude,
like MyKeyworder. Runs on your own computer, no hosting needed.

## Setup (once)

1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. Optional, to write keywords into the JPEG files: install [exiftool](https://exiftool.org).
4. Get an API key at https://console.anthropic.com (billed separately from claude.ai) and set it:
   - Mac/Linux: `export ANTHROPIC_API_KEY=sk-ant-...`
   - Windows: `setx ANTHROPIC_API_KEY sk-ant-...` (then open a new terminal)

## Use

```
python stock_keywords.py path/to/photos
python stock_keywords.py path/to/photos --embed --hint "Chiang Mai, Thailand"
```

- `--hint` gives facts the AI can't see (place, species, event). It won't guess these on its own.
- `--embed` writes title, description and keywords into the JPEGs (IPTC + XMP). It overwrites existing keywords.
- `--effort low` is cheaper and faster; default is `medium`.

Output in the photo folder:
- `adobe_stock.csv` (Filename, Title, Keywords)
- `shutterstock.csv` (Filename, Description, Keywords)
- `metadata.json` (everything)

Always review the keywords before submitting. The AI can be wrong.
