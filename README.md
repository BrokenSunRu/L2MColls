# Lineage 2M Collections Tracker

*[Читать на русском (Read in Russian)](README_ru.md)*

A lightweight, local web application designed to help Lineage 2M players track their Classes, Agathions, and Collections. Built with Python (FastAPI) and vanilla HTML/JS/CSS, it provides a fast and responsive interface with a dark fantasy aesthetic.

## Core Features

- **Data Management:** Add and manage Classes and Agathions, specifying their rarities and available upgrade paths (Ascend, Elevate, Meld, Spiritualize).
- **Collections Tracking:** Create collections with specific stat bonuses and item requirements (including minimum upgrade levels required).
- **Personal Inventory (My Items):** Mark items you currently own and adjust their specific upgrade levels.
- **Smart Finder:** Search for one or multiple stats simultaneously (e.g., `Damage Reduction` or `CC Duration Reduction`). The app will display which collections provide the stats, whether you have unlocked them, and exactly **what items or upgrades you are missing** to complete them. It also features a recommendation system suggesting the **"Top 10 upgrades"** and **"Easiest collections"** to complete based on your current inventory.
- **Import / Export:** Easily backup your entire database (classes, agathions, collections, and inventory) to a JSON file and restore it at any time. You can also export/import just your personal inventory to smoothly update your local database from someone else's file!

## Tech Stack

- **Backend:** Python, FastAPI, Pydantic
- **Database:** SQLite (Local file `app.db` with WAL mode for performance)
- **Frontend:** Vanilla HTML5, JavaScript (Fetch API), and CSS3 (Custom L2M-inspired dark theme)

## Prerequisites

- Python 3.8 or higher installed on your system.

## Installation & Running

1. **Open your terminal** and navigate to the project directory:
   ```bash
   cd path/to/L2MColls
   ```

2. **Install the required Python packages:**
   ```bash
   pip install fastapi uvicorn pydantic
   ```

3. **Start the local server:**
   You can simply double-click the `run.bat` file (on Windows) or run the following command in your terminal:
   ```bash
   python -m uvicorn main:app --reload
   ```
   *(The `--reload` flag allows the server to auto-restart if you modify the Python code).*

4. **Access the application:**
   Open your web browser and go to:
   http://localhost:8000

5. **API Documentation (Optional):**
   FastAPI automatically generates interactive API documentation. You can view it at:
   http://localhost:8000/docs

## Suggested Workflow

**For regular users:**
1. **Load Database:** If someone shared a ready-to-use database with you, go to the **Data** page and click **Import JSON**. You generally don't need to manually edit anything on the Data page unless you want to add or fix something yourself!
2. **Track Inventory:** Go to the **My Items** page and check the boxes for the items your character currently owns, setting their specific upgrade levels.
3. **Find Upgrades:** Use the **Finder** page to type in a stat you want to boost. The app will show you which collections provide it and exactly what items you are missing.

**How to update your local database without losing your inventory:**
1. Go to **My Items** and click **Export Owned JSON** to safely backup your personal inventory.
2. Go to the **Data** page and click **Import JSON** to load the new, updated database file you received.
3. Finally, click **Import Owned JSON** and select your previously saved inventory file to instantly restore all your checked items and upgrade levels!

**For database maintainers:**
- Use the **Data** page to manually populate the database with new Classes, Agathions, and Collections. Once done, use **Export JSON** to share your comprehensive work with others.

## Acknowledgments

This application was created entirely with the assistance of Google's Gemini AI.

## License

This is a personal utility tool. Feel free to modify and adapt it to your needs!