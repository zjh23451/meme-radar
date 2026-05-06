name: Meme Radar

on:
  schedule:
    - cron: '*/5 * * * *'
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Run radar
        env:
          TG_TOKEN:   ${{ secrets.TG_TOKEN }}
          TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}
        run: |
          pip install requests -q
          python radar.py

      - name: Save state
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "update seen state"
          file_pattern: seen.json
