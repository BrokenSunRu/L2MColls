# Lineage 2M Collections Tracker

A lightweight, local web application designed to help Lineage 2M players track their Classes, Agathions, and Collections. Built with Python (FastAPI) and vanilla HTML/JS/CSS, it provides a fast and responsive interface with a dark fantasy aesthetic.

## Core Features

- **Data Management:** Add and manage Classes and Agathions, specifying their rarities and available upgrade paths (Ascend, Elevate, Meld, Spiritualize).
- **Collections Tracking:** Create collections with specific stat bonuses and item requirements (including minimum upgrade levels required).
- **Personal Inventory (My Items):** Mark items you currently own and adjust their specific upgrade levels.
- **Smart Finder:** Search for specific stats (e.g., `Damage_Reduction` or `CC_Duration_Reduction`). The app will display which collections provide the stat, whether you have unlocked them, and exactly **what items or upgrades you are missing** to complete them.
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

1. Go to the **Data** page and populate your database with the Classes and Agathions that exist in the game.
2. Stay on the **Data** page and create Collections, adding the required classes/agathions and specifying the bonuses they yield.
3. Go to the **Inventory** page and check the boxes for the items your character currently owns, setting their upgrade levels.
4. Use the **Finder** page to type in a stat you want to boost. The app will calculate the fastest route to get that stat based on your current inventory.

## License

This is a personal utility tool. Feel free to modify and adapt it to your needs!