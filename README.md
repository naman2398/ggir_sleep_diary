# GGIR Sleep Diary Converter

A Streamlit web app that converts long-format sleep diary CSVs into the [GGIR advanced sleeplog](https://wadpac.github.io/GGIR/articles/chapter9_SleepFundamentalsGuiders.html) wide format.

## Features

- **Upload** a sleep diary CSV (`SUBJECT`, `Out_Bed`, `In_Bed` columns)
- **Define segments** on the fly — add accelerometer recording IDs and their date ranges
- **Convert** to GGIR advanced sleeplog format
- **Download** the result as CSV
- **Export/Import** segment definitions as JSON for reuse

## Local Development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Azure Deployment

This app is deployed to **Azure Web App** (Python runtime) via GitHub Actions.

### Setup Steps

1. **Create an Azure Web App** in the Azure Portal:
   - Runtime: **Python 3.11**
   - Startup command:
     ```
     python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0
     ```

2. **Download the Publish Profile** from the Azure Portal (Web App → Overview → Download publish profile).

3. **Add secrets/variables to GitHub repo** (Settings → Secrets and variables → Actions):
   - **Secret:** `AZURE_WEBAPP_PUBLISH_PROFILE` — paste the full XML publish profile
   - **Variable:** `AZURE_WEBAPP_NAME` — your Azure Web App name

4. **Push to `main`** — the GitHub Actions workflow will automatically deploy.

## CLI Usage

The converter also works as a standalone CLI tool:

```bash
python convert_sleeplog.py input.csv -s segments.json -o output/
```
