# Web Scrapers

This repo now houses two coordinated scrapers for the Cafe24 → Shopify pipeline:

1. **Python pipeline (`web-scraper-python/`)** – loads URLs, downloads product data + images, transforms to Shopify CSV, and writes run summaries.
2. **Node.js Puppeteer workflow (`web-scraper-node/`)** – loads the same URL list and captures full page/detail screenshots for QA or marketing assets.

Both tools rely on the shared `urls.csv` file stored at the repository root.

## Python Pipeline

### Install / activate

```bash
cd web-scraper-python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Populate a `.env.local` (or `.env`) with configuration—minimum:

```
SCRAPER_INPUT_URLS=/absolute/path/to/urls.csv
```

### Run a scrape

```bash
cd web-scraper-python
../.venv/bin/python scrape.py --env-file ../.env.local --run-id <run-name>

# optional: automatically trigger Puppeteer screenshots
# ../.venv/bin/python scrape.py --env-file ../.env.local --run-id <run-name> --enable-puppeteer
```

Outputs land in `web-scraper-python/output/<run-name>/` and include:

- `shopify_import.csv` – Shopify-ready rows
- `run_summary.json` – success/failure counts
- `images/` – downloaded images (when available)
- `screenshots/` – Puppeteer output when enabled

## Node.js Puppeteer Screenshots

### Install

```bash
cd web-scraper-node
npm install
```

### Capture screenshots

```bash
cd web-scraper-node
node scrape.js \
  --input ../urls.csv \
  --output ../web-scraper-python/output/screenshots \
  --width 1440 \
  --height 900
```

The script reads the same CSV, visits each product page, and saves:

- `<slug>-full.png` – full page screenshot
- `<slug>-detail.png` – cropped detail/product section screenshot

## Suggested Integration Flow

1. Update `urls.csv` with the product pages to scrape.
2. Run the Python pipeline to collect structured data and raw images.
   - Add `--enable-puppeteer` to have the Python runner invoke the Node workflow automatically.
3. Run the Puppeteer workflow manually when debugging or capturing alternate viewport sizes.
4. Package `output/<run-id>/` plus `output/screenshots/` for QA or Shopify import.
