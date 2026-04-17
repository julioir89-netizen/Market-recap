name: Update Portfolio Prices

on:
  schedule:
    - cron: '0,15,30,45 13 * * 1-5'
    - cron: '0,15,30,45 14 * * 1-5'
    - cron: '0,15,30,45 15 * * 1-5'
    - cron: '0,15,30,45 16 * * 1-5'
    - cron: '0,15,30,45 17 * * 1-5'
    - cron: '0,15,30,45 18 * * 1-5'
    - cron: '0,15,30,45 19 * * 1-5'
    - cron: '0,15 20 * * 1-5'
    - cron: '0 12 * * 1-5'

  workflow_dispatch:

permissions:
  contents: write

jobs:
  update-prices:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install yfinance pytz numpy pandas

      - name: Update prices.json
        run: python prices_updater.py
        env:
          GIST_TOKEN: ${{ secrets.GIST_TOKEN }}

      - name: Commit prices.json
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "Portfolio Bot"
          git add prices.json
          git diff --staged --quiet || git commit -m "Update prices $(TZ='America/Los_Angeles' date '+%I:%M %p PT')"
          git push
