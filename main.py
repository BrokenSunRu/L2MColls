from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union, Iterator

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# App & DB path (stable)
# -----------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
DB_PATH = str(APP_DIR / "app.db")
OWNED_DB_PATH = str(APP_DIR / "owned.db")
STATIC_DIR = APP_DIR / "static"

# Initialize the FastAPI application
app = FastAPI(title="Classes/Agathions Collections Tracker")

# Serve /static/*
if not STATIC_DIR.exists():
    # Not fatal, but better message than silent missing files.
    print(f"WARNING: static directory not found: {STATIC_DIR}")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def normalize_name(s: str) -> str:
    return " ".join(str(s).strip().split())

CLASS_RARITIES = {"Common", "Rare", "Unique", "Epic", "Legend", "Mythic", "Zenith"}
AGATHION_RARITIES = {"Common", "Rare", "Unique", "Epic", "Legend", "Mythic"}

def validate_class_rarity(r: str) -> None:
    if r not in CLASS_RARITIES:
        raise HTTPException(status_code=400, detail=f"Invalid class rarity: {r}")

def validate_agathion_rarity(r: str) -> None:
    if r not in AGATHION_RARITIES:
        raise HTTPException(status_code=400, detail=f"Invalid agathion rarity: {r}")

def db_connect() -> sqlite3.Connection:
    # Connect to the main application database containing static game data
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Подключаем пользовательскую базу данных
    # Attach the user's personal inventory database as a separate schema ('user_db')
    owned_path_str = OWNED_DB_PATH.replace("\\", "/")
    conn.execute(f"ATTACH DATABASE '{owned_path_str}' AS user_db;")

    return conn

# Dependency generator to provide a database connection for API routes
def get_db() -> Iterator[sqlite3.Connection]:
    conn = db_connect()
    try:
        yield conn
    finally:
        conn.close()

# Database initialization: creates tables if they don't exist
def db_init() -> None:
    conn = db_connect()
    # Create tables for game data in the main database
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS classes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            rarity TEXT NOT NULL,
            can_ascend INTEGER NOT NULL DEFAULT 0,
            can_elevate INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agathions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            rarity TEXT NOT NULL,
            can_meld INTEGER NOT NULL DEFAULT 0,
            can_elevate INTEGER NOT NULL DEFAULT 0,
            can_spiritualize INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS collections(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            bonus_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS collection_requirements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL,
            req_type TEXT NOT NULL CHECK(req_type IN ('class','agathion')),
            req_id INTEGER NOT NULL,

            min_class_ascend INTEGER NOT NULL DEFAULT 0,
            min_class_elevate INTEGER NOT NULL DEFAULT 0,

            min_ag_meld INTEGER NOT NULL DEFAULT 0,
            min_ag_elevate INTEGER NOT NULL DEFAULT 0,
            min_ag_spiritualize INTEGER NOT NULL DEFAULT 0,

            UNIQUE(collection_id, req_type, req_id),
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE
        );
        """
    )
    # Create the personal inventory table in the attached user database
    conn.executescript(
        """
        PRAGMA user_db.journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS user_db.owned(
            req_type TEXT NOT NULL CHECK(req_type IN ('class','agathion')),
            req_id INTEGER NOT NULL,

            class_ascend INTEGER NOT NULL DEFAULT 0,
            class_elevate INTEGER NOT NULL DEFAULT 0,

            ag_meld INTEGER NOT NULL DEFAULT 0,
            ag_elevate INTEGER NOT NULL DEFAULT 0,
            ag_spiritualize INTEGER NOT NULL DEFAULT 0,

            PRIMARY KEY(req_type, req_id)
        );
        """
    )

    # Автоматическая миграция: если таблица owned осталась в основной БД, переносим её
    rows = conn.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name='owned';").fetchall()
    if rows:
        print("Migrating 'owned' table from app.db to owned.db...")
        conn.execute("INSERT OR IGNORE INTO user_db.owned SELECT * FROM main.owned;")
        conn.execute("DROP TABLE main.owned;")

    conn.commit()
    conn.close()

db_init()


# -----------------------------------------------------------------------------
# Bonus types (supports legacy and typed)
# -----------------------------------------------------------------------------

class BonusTyped(BaseModel):
    value: float
    type: Literal["flat", "percent"]

BonusValue = Union[float, int, str, dict, BonusTyped]
BonusDict = Dict[str, BonusValue]

# Function to convert different formats of collection bonuses into a unified standard
def normalize_bonus(bonus: Any) -> Dict[str, Any]:
    """
    Accepts:
      1) {"Stat": 2, "Other": 3.5}                        (legacy numeric)
      2) {"Stat": {"value": 2, "type": "percent"}, ...}   (typed)
      3) {"Stat": BonusTyped(...), ...}                   (typed, pydantic)
      4) optional: {"Stat": "2%"}                         (string percent)
    Returns:
      {"Stat": 2.0, ...} or {"Stat": {"value":2.0,"type":"percent"}, ...}
    """
    if bonus is None:
        return {}

    if isinstance(bonus, BaseModel):
        bonus = bonus.model_dump()

    if not isinstance(bonus, dict):
        raise HTTPException(status_code=400, detail="Bonus JSON must be an object")

    out: Dict[str, Any] = {}

    for k, v in bonus.items():
        key = normalize_name(str(k))
        if not key:
            continue

        if isinstance(v, BaseModel):
            v = v.model_dump()

        # legacy numeric
        if isinstance(v, (int, float)):
            out[key] = float(v)
            continue

        # typed dict
        if isinstance(v, dict):
            val = v.get("value", 0)
            typ = v.get("type", "flat")

            if not isinstance(val, (int, float)):
                raise HTTPException(status_code=400, detail=f"Bonus '{key}': value must be a number")
            if not isinstance(typ, str):
                raise HTTPException(status_code=400, detail=f"Bonus '{key}': type must be a string")

            typ = typ.strip().lower()
            if typ not in ("flat", "percent"):
                raise HTTPException(status_code=400, detail=f"Bonus '{key}': type must be 'flat' or 'percent'")

            out[key] = {"value": float(val), "type": typ}
            continue

        # optional string support: "2%"
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("%"):
                try:
                    out[key] = {"value": float(s[:-1].strip()), "type": "percent"}
                    continue
                except Exception:
                    pass
            else:
                try:
                    out[key] = float(s)
                    continue
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail=f"Bonus '{key}': invalid string value")

        raise HTTPException(status_code=400, detail=f"Bonus '{key}': unsupported value type")

    return out


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------

# Pydantic models are used to validate incoming JSON requests and format outgoing API responses.
class ClassIn(BaseModel):
    name: str
    rarity: str
    can_ascend: bool = False
    can_elevate: bool = False

class ClassOut(ClassIn):
    id: int

class AgathionIn(BaseModel):
    name: str
    rarity: str
    can_meld: bool = False
    can_elevate: bool = False
    can_spiritualize: bool = False

class AgathionOut(AgathionIn):
    id: int

class RequirementIn(BaseModel):
    req_type: Literal["class", "agathion"]
    req_id: int

    min_class_ascend: int = 0
    min_class_elevate: int = 0

    min_ag_meld: int = 0
    min_ag_elevate: int = 0
    min_ag_spiritualize: int = 0

class RequirementOut(RequirementIn):
    id: int
    collection_id: int

class CollectionCreate(BaseModel):
    name: str
    bonus: BonusDict = Field(default_factory=dict)
    requirements: List[RequirementIn] = Field(default_factory=list)

class CollectionOut(BaseModel):
    id: int
    name: str
    bonus: Dict[str, Any]
    requirements: List[RequirementOut]

class OwnedRowOut(BaseModel):
    req_type: Literal["class", "agathion"]
    req_id: int
    class_ascend: int = 0
    class_elevate: int = 0
    ag_meld: int = 0
    ag_elevate: int = 0
    ag_spiritualize: int = 0

class OwnedSetIn(BaseModel):
    req_type: Literal["class", "agathion"]
    req_id: int
    owned: bool

class OwnedSetBulkIn(BaseModel):
    req_type: Literal["class", "agathion"]
    rarity: str
    owned: bool

class OwnedLevelsIn(BaseModel):
    req_type: Literal["class", "agathion"]
    req_id: int

    class_ascend: int = 0
    class_elevate: int = 0
    ag_meld: int = 0
    ag_elevate: int = 0
    ag_spiritualize: int = 0

class FinderResultReq(BaseModel):
    req_type: Literal["class", "agathion"]
    req_id: int
    name: str
    rarity: str
    missing: bool

    need_class_ascend: int = 0
    need_class_elevate: int = 0

    need_ag_meld: int = 0
    need_ag_elevate: int = 0
    need_ag_spiritualize: int = 0

    have_class_ascend: int = 0
    have_class_elevate: int = 0
    have_ag_meld: int = 0
    have_ag_elevate: int = 0
    have_ag_spiritualize: int = 0

class TopUpgradeOut(BaseModel):
    req_type: Literal["class", "agathion"]
    req_id: int
    name: str
    rarity: str
    action: str
    collections_count: int
    bonuses: Dict[str, Any]

class FinderResultOut(BaseModel):
    collection_id: int
    collection_name: str
    provides: Any  # number or typed dict
    unlocked: bool
    missing: List[FinderResultReq]


# -----------------------------------------------------------------------------
# Routes: Pages
# -----------------------------------------------------------------------------

# Endpoints to serve the raw HTML files to the browser
@app.get("/")
def page_index():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/data")
def page_data():
    return FileResponse(str(STATIC_DIR / "data.html"))

@app.get("/inventory")
def page_inventory():
    return FileResponse(str(STATIC_DIR / "inventory.html"))

@app.get("/finder")
def page_finder():
    return FileResponse(str(STATIC_DIR / "finder.html"))


# -----------------------------------------------------------------------------
# Routes: Classes & Agathions
# -----------------------------------------------------------------------------

# Get a list of all classes from the database
@app.get("/api/classes", response_model=List[ClassOut])
def api_list_classes(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT id, name, rarity, can_ascend, can_elevate FROM classes ORDER BY name;"
    ).fetchall()
    return [
        ClassOut(
            id=r["id"],
            name=r["name"],
            rarity=r["rarity"],
            can_ascend=bool(r["can_ascend"]),
            can_elevate=bool(r["can_elevate"]),
        )
        for r in rows
    ]

# Update an existing class by ID
@app.put("/api/classes/{class_id}", response_model=ClassOut)
def api_update_class(class_id: int, payload: ClassIn, conn: sqlite3.Connection = Depends(get_db)):
    name = normalize_name(payload.name)
    rarity = normalize_name(payload.rarity)
    validate_class_rarity(rarity)

    try:
        conn.execute(
            "UPDATE classes SET name=?, rarity=?, can_ascend=?, can_elevate=? WHERE id=?",
            (name, rarity, int(payload.can_ascend), int(payload.can_elevate), class_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Class with this name already exists")

    row = conn.execute("SELECT id, name, rarity, can_ascend, can_elevate FROM classes WHERE id=?;", (class_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Class not found")

    return ClassOut(
        id=row["id"], name=row["name"], rarity=row["rarity"],
        can_ascend=bool(row["can_ascend"]), can_elevate=bool(row["can_elevate"])
    )

# Add a new class to the database
@app.post("/api/classes", response_model=ClassOut)
def api_create_class(payload: ClassIn, conn: sqlite3.Connection = Depends(get_db)):
    name = normalize_name(payload.name)
    rarity = normalize_name(payload.rarity)
    validate_class_rarity(rarity)

    try:
        conn.execute(
            """
            INSERT INTO classes(name, rarity, can_ascend, can_elevate)
            VALUES (?,?,?,?);
            """,
            (name, rarity, int(payload.can_ascend), int(payload.can_elevate)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Class with this name already exists")

    row = conn.execute(
        "SELECT id, name, rarity, can_ascend, can_elevate FROM classes WHERE name=?;",
        (name,),
    ).fetchone()

    return ClassOut(
        id=row["id"],
        name=row["name"],
        rarity=row["rarity"],
        can_ascend=bool(row["can_ascend"]),
        can_elevate=bool(row["can_elevate"]),
    )

# Delete a class and clean up references from collections and user inventory
@app.delete("/api/classes/{class_id}", response_model=Dict[str, Any])
def api_delete_class(class_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM classes WHERE id=?;", (class_id,))
    conn.execute("DELETE FROM collection_requirements WHERE req_type='class' AND req_id=?;", (class_id,))
    conn.execute("DELETE FROM user_db.owned WHERE req_type='class' AND req_id=?;", (class_id,))
    conn.commit()
    return {"ok": True}

@app.get("/api/agathions", response_model=List[AgathionOut])
def api_list_agathions(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT id, name, rarity, can_meld, can_elevate, can_spiritualize FROM agathions ORDER BY name;"
    ).fetchall()
    return [
        AgathionOut(
            id=r["id"],
            name=r["name"],
            rarity=r["rarity"],
            can_meld=bool(r["can_meld"]),
            can_elevate=bool(r["can_elevate"]),
            can_spiritualize=bool(r["can_spiritualize"]),
        )
        for r in rows
    ]

@app.put("/api/agathions/{ag_id}", response_model=AgathionOut)
def api_update_agathion(ag_id: int, payload: AgathionIn, conn: sqlite3.Connection = Depends(get_db)):
    name = normalize_name(payload.name)
    rarity = normalize_name(payload.rarity)
    validate_agathion_rarity(rarity)

    try:
        conn.execute(
            "UPDATE agathions SET name=?, rarity=?, can_meld=?, can_elevate=?, can_spiritualize=? WHERE id=?",
            (name, rarity, int(payload.can_meld), int(payload.can_elevate), int(payload.can_spiritualize), ag_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Agathion with this name already exists")

    row = conn.execute("SELECT id, name, rarity, can_meld, can_elevate, can_spiritualize FROM agathions WHERE id=?;", (ag_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agathion not found")

    return AgathionOut(
        id=row["id"], name=row["name"], rarity=row["rarity"],
        can_meld=bool(row["can_meld"]), can_elevate=bool(row["can_elevate"]), can_spiritualize=bool(row["can_spiritualize"])
    )

@app.post("/api/agathions", response_model=AgathionOut)
def api_create_agathion(payload: AgathionIn, conn: sqlite3.Connection = Depends(get_db)):
    name = normalize_name(payload.name)
    rarity = normalize_name(payload.rarity)
    validate_agathion_rarity(rarity)

    try:
        conn.execute(
            """
            INSERT INTO agathions(name, rarity, can_meld, can_elevate, can_spiritualize)
            VALUES (?,?,?,?,?);
            """,
            (name, rarity, int(payload.can_meld), int(payload.can_elevate), int(payload.can_spiritualize)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Agathion with this name already exists")

    row = conn.execute(
        "SELECT id, name, rarity, can_meld, can_elevate, can_spiritualize FROM agathions WHERE name=?;",
        (name,),
    ).fetchone()

    return AgathionOut(
        id=row["id"],
        name=row["name"],
        rarity=row["rarity"],
        can_meld=bool(row["can_meld"]),
        can_elevate=bool(row["can_elevate"]),
        can_spiritualize=bool(row["can_spiritualize"]),
    )

@app.delete("/api/agathions/{ag_id}", response_model=Dict[str, Any])
def api_delete_agathion(ag_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM agathions WHERE id=?;", (ag_id,))
    conn.execute("DELETE FROM collection_requirements WHERE req_type='agathion' AND req_id=?;", (ag_id,))
    conn.execute("DELETE FROM user_db.owned WHERE req_type='agathion' AND req_id=?;", (ag_id,))
    conn.commit()
    return {"ok": True}

# Provide metadata to the frontend (available rarities, bonus types, etc.)
@app.get("/api/meta")
def api_meta():
    return {
        "class_rarities": ["Common", "Rare", "Unique", "Epic", "Legend", "Mythic", "Zenith"],
        "agathion_rarities": ["Common", "Rare", "Unique", "Epic", "Legend", "Mythic"],
        "bonus_types": ["flat", "percent"],
        "req_types": ["class", "agathion"],
    }


# -----------------------------------------------------------------------------
# Routes: Collections & Requirements
# -----------------------------------------------------------------------------

# Helper function to fetch a collection and its item requirements by ID
def _load_collection(conn: sqlite3.Connection, collection_id: int) -> CollectionOut:
    c = conn.execute(
        "SELECT id, name, bonus_json FROM collections WHERE id=?;",
        (collection_id,),
    ).fetchone()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")

    bonus = json.loads(c["bonus_json"]) if c["bonus_json"] else {}
    req_rows = conn.execute(
        """
        SELECT id, collection_id, req_type, req_id,
               min_class_ascend, min_class_elevate,
               min_ag_meld, min_ag_elevate, min_ag_spiritualize
        FROM collection_requirements
        WHERE collection_id=?
        ORDER BY req_type, req_id;
        """,
        (collection_id,),
    ).fetchall()

    reqs = [
        RequirementOut(
            id=r["id"],
            collection_id=r["collection_id"],
            req_type=r["req_type"],
            req_id=r["req_id"],
            min_class_ascend=int(r["min_class_ascend"]),
            min_class_elevate=int(r["min_class_elevate"]),
            min_ag_meld=int(r["min_ag_meld"]),
            min_ag_elevate=int(r["min_ag_elevate"]),
            min_ag_spiritualize=int(r["min_ag_spiritualize"]),
        )
        for r in req_rows
    ]

    return CollectionOut(id=c["id"], name=c["name"], bonus=bonus, requirements=reqs)

@app.get("/api/collections", response_model=List[CollectionOut])
def api_list_collections(conn: sqlite3.Connection = Depends(get_db)):
    ids = conn.execute("SELECT id FROM collections ORDER BY name;").fetchall()
    out = [_load_collection(conn, int(r["id"])) for r in ids]
    return out

@app.put("/api/collections/{collection_id}", response_model=CollectionOut)
def api_update_collection(collection_id: int, payload: CollectionCreate, conn: sqlite3.Connection = Depends(get_db)):
    name = normalize_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Collection name is empty")

    bonus_norm = normalize_bonus(payload.bonus)
    bonus_json = json.dumps(bonus_norm, ensure_ascii=False)

    exists = conn.execute("SELECT id FROM collections WHERE id=?;", (collection_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        conn.execute("UPDATE collections SET name=?, bonus_json=? WHERE id=?;", (name, bonus_json, collection_id))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Collection with this name already exists")

    conn.execute("DELETE FROM collection_requirements WHERE collection_id=?;", (collection_id,))

    for req in payload.requirements:
        if req.req_type == "class":
            x = conn.execute("SELECT 1 FROM classes WHERE id=?;", (req.req_id,)).fetchone()
            if not x:
                raise HTTPException(status_code=400, detail=f"Class id not found: {req.req_id}")
        else:
            x = conn.execute("SELECT 1 FROM agathions WHERE id=?;", (req.req_id,)).fetchone()
            if not x:
                raise HTTPException(status_code=400, detail=f"Agathion id not found: {req.req_id}")

        conn.execute(
            """
            INSERT INTO collection_requirements(collection_id, req_type, req_id, min_class_ascend, min_class_elevate, min_ag_meld, min_ag_elevate, min_ag_spiritualize)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (collection_id, req.req_type, req.req_id, int(req.min_class_ascend), int(req.min_class_elevate), int(req.min_ag_meld), int(req.min_ag_elevate), int(req.min_ag_spiritualize))
        )

    conn.commit()
    return _load_collection(conn, collection_id)

@app.post("/api/collections", response_model=CollectionOut)
def api_create_collection(payload: CollectionCreate, conn: sqlite3.Connection = Depends(get_db)):
    name = normalize_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Collection name is empty")

    # Validate & normalize bonus to store
    bonus_norm = normalize_bonus(payload.bonus)
    bonus_json = json.dumps(bonus_norm, ensure_ascii=False)

    try:
        conn.execute(
            "INSERT INTO collections(name, bonus_json) VALUES (?,?);",
            (name, bonus_json),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Collection with this name already exists")

    col = conn.execute("SELECT id FROM collections WHERE name=?;", (name,)).fetchone()
    col_id = int(col["id"])

    # Add requirements
    for req in payload.requirements:
        if req.req_type == "class":
            exists = conn.execute("SELECT 1 FROM classes WHERE id=?;", (req.req_id,)).fetchone()
            if not exists:
                raise HTTPException(status_code=400, detail=f"Class id not found: {req.req_id}")
        else:
            exists = conn.execute("SELECT 1 FROM agathions WHERE id=?;", (req.req_id,)).fetchone()
            if not exists:
                raise HTTPException(status_code=400, detail=f"Agathion id not found: {req.req_id}")

        conn.execute(
            """
            INSERT INTO collection_requirements(
              collection_id, req_type, req_id,
              min_class_ascend, min_class_elevate,
              min_ag_meld, min_ag_elevate, min_ag_spiritualize
            )
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(collection_id, req_type, req_id) DO UPDATE SET
              min_class_ascend=excluded.min_class_ascend,
              min_class_elevate=excluded.min_class_elevate,
              min_ag_meld=excluded.min_ag_meld,
              min_ag_elevate=excluded.min_ag_elevate,
              min_ag_spiritualize=excluded.min_ag_spiritualize;
            """,
            (
                col_id, req.req_type, req.req_id,
                int(req.min_class_ascend), int(req.min_class_elevate),
                int(req.min_ag_meld), int(req.min_ag_elevate), int(req.min_ag_spiritualize),
            )
        )

    conn.commit()
    out = _load_collection(conn, col_id)
    return out

# Delete a collection completely
@app.delete("/api/collections/{collection_id}", response_model=Dict[str, Any])
def api_delete_collection(collection_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM collections WHERE id=?;", (collection_id,))
    conn.commit()
    return {"ok": True}

@app.post("/api/collections/{collection_id}/requirements", response_model=RequirementOut)
def api_add_requirement(collection_id: int, req: RequirementIn, conn: sqlite3.Connection = Depends(get_db)):
    exists = conn.execute("SELECT 1 FROM collections WHERE id=?;", (collection_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Collection not found")

    if req.req_type == "class":
        x = conn.execute("SELECT 1 FROM classes WHERE id=?;", (req.req_id,)).fetchone()
        if not x:
            raise HTTPException(status_code=400, detail="Class not found")
    else:
        x = conn.execute("SELECT 1 FROM agathions WHERE id=?;", (req.req_id,)).fetchone()
        if not x:
            raise HTTPException(status_code=400, detail="Agathion not found")

    conn.execute(
        """
        INSERT INTO collection_requirements(
          collection_id, req_type, req_id,
          min_class_ascend, min_class_elevate,
          min_ag_meld, min_ag_elevate, min_ag_spiritualize
        )
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(collection_id, req_type, req_id) DO UPDATE SET
          min_class_ascend=excluded.min_class_ascend,
          min_class_elevate=excluded.min_class_elevate,
          min_ag_meld=excluded.min_ag_meld,
          min_ag_elevate=excluded.min_ag_elevate,
          min_ag_spiritualize=excluded.min_ag_spiritualize;
        """,
        (
            collection_id, req.req_type, req.req_id,
            int(req.min_class_ascend), int(req.min_class_elevate),
            int(req.min_ag_meld), int(req.min_ag_elevate), int(req.min_ag_spiritualize),
        ),
    )
    conn.commit()

    row = conn.execute(
        """
        SELECT id, collection_id, req_type, req_id,
               min_class_ascend, min_class_elevate,
               min_ag_meld, min_ag_elevate, min_ag_spiritualize
        FROM collection_requirements
        WHERE collection_id=? AND req_type=? AND req_id=?;
        """,
        (collection_id, req.req_type, req.req_id),
    ).fetchone()

    return RequirementOut(
        id=row["id"],
        collection_id=row["collection_id"],
        req_type=row["req_type"],
        req_id=row["req_id"],
        min_class_ascend=int(row["min_class_ascend"]),
        min_class_elevate=int(row["min_class_elevate"]),
        min_ag_meld=int(row["min_ag_meld"]),
        min_ag_elevate=int(row["min_ag_elevate"]),
        min_ag_spiritualize=int(row["min_ag_spiritualize"]),
    )

@app.delete("/api/requirements/{req_row_id}", response_model=Dict[str, Any])
def api_delete_requirement(req_row_id: int, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM collection_requirements WHERE id=?;", (req_row_id,))
    conn.commit()
    return {"ok": True}


# -----------------------------------------------------------------------------
# Routes: Owned (inventory)
# -----------------------------------------------------------------------------

# Fetch the user's current inventory from the personal database
@app.get("/api/owned", response_model=List[OwnedRowOut])
def api_list_owned(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """
        SELECT req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize
        FROM user_db.owned
        ORDER BY req_type, req_id;
        """
    ).fetchall()
    return [
        OwnedRowOut(
            req_type=r["req_type"],
            req_id=int(r["req_id"]),
            class_ascend=int(r["class_ascend"]),
            class_elevate=int(r["class_elevate"]),
            ag_meld=int(r["ag_meld"]),
            ag_elevate=int(r["ag_elevate"]),
            ag_spiritualize=int(r["ag_spiritualize"]),
        )
        for r in rows
    ]

# Toggle an item's owned state (add or remove from inventory)
@app.post("/api/owned/set", response_model=Dict[str, Any])
def api_owned_set(payload: OwnedSetIn, conn: sqlite3.Connection = Depends(get_db)):
    # Validate existence
    if payload.req_type == "class":
        ex = conn.execute("SELECT 1 FROM classes WHERE id=?;", (payload.req_id,)).fetchone()
        if not ex:
            raise HTTPException(status_code=400, detail="Class not found")
    else:
        ex = conn.execute("SELECT 1 FROM agathions WHERE id=?;", (payload.req_id,)).fetchone()
        if not ex:
            raise HTTPException(status_code=400, detail="Agathion not found")

    if payload.owned:
        conn.execute(
            """
            INSERT INTO user_db.owned(req_type, req_id)
            VALUES (?,?)
            ON CONFLICT(req_type, req_id) DO NOTHING;
            """,
            (payload.req_type, payload.req_id),
        )
    else:
        conn.execute(
            "DELETE FROM user_db.owned WHERE req_type=? AND req_id=?;",
            (payload.req_type, payload.req_id),
        )

    conn.commit()
    return {"ok": True}

# Toggle the ownership of all items of a specific rarity at once
@app.post("/api/owned/set_bulk", response_model=Dict[str, Any])
def api_owned_set_bulk(payload: OwnedSetBulkIn, conn: sqlite3.Connection = Depends(get_db)):
    if payload.req_type == "class":
        validate_class_rarity(payload.rarity)
        table = "classes"
    else:
        validate_agathion_rarity(payload.rarity)
        table = "agathions"

    rows = conn.execute(f"SELECT id FROM {table} WHERE rarity=?;", (payload.rarity,)).fetchall()

    if payload.owned:
        for r in rows:
            conn.execute(
                """
                INSERT INTO user_db.owned(req_type, req_id)
                VALUES (?,?)
                ON CONFLICT(req_type, req_id) DO NOTHING;
                """,
                (payload.req_type, r["id"]),
            )
    else:
        for r in rows:
            conn.execute(
                "DELETE FROM user_db.owned WHERE req_type=? AND req_id=?;",
                (payload.req_type, r["id"]),
            )

    conn.commit()
    return {"ok": True, "updated": len(rows)}

# Update the specific upgrade levels (ascend, elevate, etc.) of an owned item
@app.post("/api/owned/levels", response_model=Dict[str, Any])
def api_owned_levels(payload: OwnedLevelsIn, conn: sqlite3.Connection = Depends(get_db)):
    exists = conn.execute(
        "SELECT 1 FROM user_db.owned WHERE req_type=? AND req_id=?;",
        (payload.req_type, payload.req_id),
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=400, detail="Item is not owned (checkbox must be enabled)")

    # Store only relevant fields by type, but we can store all safely.
    conn.execute(
        """
        UPDATE user_db.owned SET
          class_ascend=?,
          class_elevate=?,
          ag_meld=?,
          ag_elevate=?,
          ag_spiritualize=?
        WHERE req_type=? AND req_id=?;
        """,
        (
            int(payload.class_ascend),
            int(payload.class_elevate),
            int(payload.ag_meld),
            int(payload.ag_elevate),
            int(payload.ag_spiritualize),
            payload.req_type,
            payload.req_id,
        ),
    )
    conn.commit()
    return {"ok": True}

@app.delete("/api/owned", response_model=Dict[str, Any])
def api_owned_clear(conn: sqlite3.Connection = Depends(get_db)):
    # Полностью очищаем инвентарь
    conn.execute("DELETE FROM user_db.owned;")
    conn.commit()
    return {"ok": True}


# -----------------------------------------------------------------------------
# Routes: Finder
# -----------------------------------------------------------------------------

RARITY_W = {"Common": 1, "Rare": 10, "Unique": 100, "Epic": 1500, "Legend": 15000, "Mythic": 150000, "Zenith": 1000000}
K_UP = {"Common": 0.2, "Rare": 0.3, "Unique": 0.5, "Epic": 0.8, "Legend": 0.4, "Mythic": 0.5, "Zenith": 0.6}
L_MULT = {1: 1.0, 2: 3.0, 3: 8.0}

def calc_upgrade_penalty(rarity: str, current_lvl: int, needed_lvl: int) -> float:
    w = RARITY_W.get(rarity, 1)
    k = K_UP.get(rarity, 0.5)
    penalty = 0.0
    for lvl in range(current_lvl + 1, needed_lvl + 1):
        # Если уровень > 3, делаем линейный рост множителя как страховку
        l_m = L_MULT.get(lvl, 8.0 + (lvl - 3) * 5.0)
        penalty += w * k * l_m
    return penalty

# Helper to fetch the actual name of an item based on its ID
def _name_by_req(conn: sqlite3.Connection, req_type: str, req_id: int) -> str:
    if req_type == "class":
        r = conn.execute("SELECT name FROM classes WHERE id=?;", (req_id,)).fetchone()
    else:
        r = conn.execute("SELECT name FROM agathions WHERE id=?;", (req_id,)).fetchone()
    return r["name"] if r else f"#{req_id}"

def _info_by_req(conn: sqlite3.Connection, req_type: str, req_id: int) -> tuple[str, str]:
    if req_type == "class":
        r = conn.execute("SELECT name, rarity FROM classes WHERE id=?;", (req_id,)).fetchone()
    else:
        r = conn.execute("SELECT name, rarity FROM agathions WHERE id=?;", (req_id,)).fetchone()
    return (r["name"], r["rarity"]) if r else (f"#{req_id}", "Common")

def _bonus_get(bonus: Dict[str, Any], stat: str) -> Optional[Any]:
    # stat key normalized
    return bonus.get(stat)

# Returns a unique list of all stats currently available in the database
@app.get("/api/stats", response_model=List[str])
def api_stats(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT bonus_json FROM collections;").fetchall()
    stats = set()
    for r in rows:
        if r["bonus_json"]:
            try:
                data = json.loads(r["bonus_json"])
                if isinstance(data, dict):
                    stats.update(data.keys())
            except Exception:
                pass
    return sorted(list(stats))

# Main endpoint for the Finder logic: calculates unlocked and missing items for a specific stat
@app.get("/api/finder", response_model=List[FinderResultOut])
def api_finder(stat: str = "", conn: sqlite3.Connection = Depends(get_db)):
    stat_key = normalize_name(stat)
    if not stat_key:
        raise HTTPException(status_code=400, detail="stat is required")

    collections = conn.execute("SELECT id, name, bonus_json FROM collections ORDER BY name;").fetchall()

    # Cache the user's inventory to quickly check against requirements
    owned_rows = conn.execute(
        """
        SELECT req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize
        FROM user_db.owned;
        """
    ).fetchall()
    owned_map: Dict[str, sqlite3.Row] = {f"{r['req_type']}:{r['req_id']}": r for r in owned_rows}

    out_scored: List[tuple[float, FinderResultOut]] = []

    # Iterate over all collections and see which ones provide the requested stat
    for c in collections:
        bonus = json.loads(c["bonus_json"]) if c["bonus_json"] else {}
        provides = _bonus_get(bonus, stat_key)
        if provides is None:
            continue

        reqs = conn.execute(
            """
            SELECT req_type, req_id,
                   min_class_ascend, min_class_elevate,
                   min_ag_meld, min_ag_elevate, min_ag_spiritualize
            FROM collection_requirements
            WHERE collection_id=?
            ORDER BY req_type, req_id;
            """,
            (c["id"],),
        ).fetchall()

        missing_list: List[FinderResultReq] = []
        unlocked = True
        score = 0

        for r in reqs:
            key = f"{r['req_type']}:{r['req_id']}"
            have = owned_map.get(key)

            have_ca = int(have["class_ascend"]) if have else 0
            have_ce = int(have["class_elevate"]) if have else 0
            have_am = int(have["ag_meld"]) if have else 0
            have_ae = int(have["ag_elevate"]) if have else 0
            have_as = int(have["ag_spiritualize"]) if have else 0

            need_ca = int(r["min_class_ascend"])
            need_ce = int(r["min_class_elevate"])
            need_am = int(r["min_ag_meld"])
            need_ae = int(r["min_ag_elevate"])
            need_as = int(r["min_ag_spiritualize"])

            # Evaluate if the user's current inventory meets the specific requirement
            ok = True
            if have is None:
                ok = False
            else:
                if r["req_type"] == "class":
                    if have_ca < need_ca or have_ce < need_ce:
                        ok = False
                else:
                    if have_am < need_am or have_ae < need_ae or have_as < need_as:
                        ok = False

            if not ok:
                unlocked = False
                req_name, req_rarity = _info_by_req(conn, r["req_type"], int(r["req_id"]))
                r_weight = RARITY_W.get(req_rarity, 1)
                
                if have is None:
                    score += r_weight * 10
                else:
                    if r["req_type"] == "class":
                        if have_ca < need_ca: score += calc_upgrade_penalty(req_rarity, have_ca, need_ca)
                        if have_ce < need_ce: score += calc_upgrade_penalty(req_rarity, have_ce, need_ce)
                    else:
                        if have_am < need_am: score += calc_upgrade_penalty(req_rarity, have_am, need_am)
                        if have_ae < need_ae: score += calc_upgrade_penalty(req_rarity, have_ae, need_ae)
                        if have_as < need_as: score += calc_upgrade_penalty(req_rarity, have_as, need_as)

                missing_list.append(
                    FinderResultReq(
                        req_type=r["req_type"],
                        req_id=int(r["req_id"]),
                        name=req_name,
                        rarity=req_rarity,
                        missing=(have is None),

                        need_class_ascend=need_ca,
                        need_class_elevate=need_ce,
                        need_ag_meld=need_am,
                        need_ag_elevate=need_ae,
                        need_ag_spiritualize=need_as,

                        have_class_ascend=have_ca,
                        have_class_elevate=have_ce,
                        have_ag_meld=have_am,
                        have_ag_elevate=have_ae,
                        have_ag_spiritualize=have_as,
                    )
                )

        out_scored.append((
            score,
            FinderResultOut(
                collection_id=int(c["id"]),
                collection_name=c["name"],
                provides=provides,
                unlocked=unlocked,
                missing=missing_list,
            )
        ))

    # Сортируем: сначала открытые коллекции (штраф 0), затем от самых легких к самым сложным
    out_scored.sort(key=lambda x: (x[0], x[1].collection_name))
    return [x[1] for x in out_scored]

@app.get("/api/recommend", response_model=List[FinderResultOut])
def api_recommend(conn: sqlite3.Connection = Depends(get_db)):
    collections = conn.execute("SELECT id, name, bonus_json FROM collections ORDER BY name;").fetchall()

    owned_rows = conn.execute(
        """
        SELECT req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize
        FROM user_db.owned;
        """
    ).fetchall()
    owned_map: Dict[str, sqlite3.Row] = {f"{r['req_type']}:{r['req_id']}": r for r in owned_rows}

    results = []

    for c in collections:
        bonus = json.loads(c["bonus_json"]) if c["bonus_json"] else {}
        
        reqs = conn.execute(
            """
            SELECT req_type, req_id,
                   min_class_ascend, min_class_elevate,
                   min_ag_meld, min_ag_elevate, min_ag_spiritualize
            FROM collection_requirements
            WHERE collection_id=?
            ORDER BY req_type, req_id;
            """,
            (c["id"],),
        ).fetchall()

        missing_list: List[FinderResultReq] = []
        unlocked = True
        score = 0

        for r in reqs:
            key = f"{r['req_type']}:{r['req_id']}"
            have = owned_map.get(key)
            req_name, req_rarity = _info_by_req(conn, r["req_type"], int(r["req_id"]))
            r_weight = RARITY_W.get(req_rarity, 1)

            have_ca = int(have["class_ascend"]) if have else 0
            have_ce = int(have["class_elevate"]) if have else 0
            have_am = int(have["ag_meld"]) if have else 0
            have_ae = int(have["ag_elevate"]) if have else 0
            have_as = int(have["ag_spiritualize"]) if have else 0

            need_ca = int(r["min_class_ascend"])
            need_ce = int(r["min_class_elevate"])
            need_am = int(r["min_ag_meld"])
            need_ae = int(r["min_ag_elevate"])
            need_as = int(r["min_ag_spiritualize"])

            item_ok = True
            if have is None:
                item_ok = False
                # Сильный штраф за отсутствие предмета
                score += r_weight * 10
            else:
                if r["req_type"] == "class":
                    if have_ca < need_ca or have_ce < need_ce:
                        item_ok = False
                        if have_ca < need_ca: score += calc_upgrade_penalty(req_rarity, have_ca, need_ca)
                        if have_ce < need_ce: score += calc_upgrade_penalty(req_rarity, have_ce, need_ce)
                else:
                    if have_am < need_am or have_ae < need_ae or have_as < need_as:
                        item_ok = False
                        if have_am < need_am: score += calc_upgrade_penalty(req_rarity, have_am, need_am)
                        if have_ae < need_ae: score += calc_upgrade_penalty(req_rarity, have_ae, need_ae)
                        if have_as < need_as: score += calc_upgrade_penalty(req_rarity, have_as, need_as)

            if not item_ok:
                unlocked = False
                # Добавляем в missing_list (так же, как в api_finder)
                missing_list.append(FinderResultReq(req_type=r["req_type"], req_id=int(r["req_id"]), name=req_name, rarity=req_rarity, missing=(have is None), need_class_ascend=need_ca, need_class_elevate=need_ce, need_ag_meld=need_am, need_ag_elevate=need_ae, need_ag_spiritualize=need_as, have_class_ascend=have_ca, have_class_elevate=have_ce, have_ag_meld=have_am, have_ag_elevate=have_ae, have_ag_spiritualize=have_as))
        
        if not unlocked and len(reqs) > 0:
            results.append((score, FinderResultOut(collection_id=int(c["id"]), collection_name=c["name"], provides=bonus, unlocked=False, missing=missing_list)))

    results.sort(key=lambda x: x[0])
    return [x[1] for x in results[:10]]

@app.get("/api/top_upgrades", response_model=List[TopUpgradeOut])
def api_top_upgrades(conn: sqlite3.Connection = Depends(get_db)):
    collections = conn.execute("SELECT id, name, bonus_json FROM collections ORDER BY name;").fetchall()
    
    owned_rows = conn.execute("SELECT req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize FROM user_db.owned;").fetchall()
    owned_map = {f"{r['req_type']}:{r['req_id']}": r for r in owned_rows}
    
    req_rows = conn.execute("SELECT collection_id, req_type, req_id, min_class_ascend, min_class_elevate, min_ag_meld, min_ag_elevate, min_ag_spiritualize FROM collection_requirements;").fetchall()
    
    col_reqs = {}
    for r in req_rows:
        cid = r["collection_id"]
        if cid not in col_reqs:
            col_reqs[cid] = []
        col_reqs[cid].append(r)
        
    upgrades = {}
    
    for c in collections:
        cid = c["id"]
        bonus = json.loads(c["bonus_json"]) if c["bonus_json"] else {}
        reqs = col_reqs.get(cid, [])
        
        total_dist = 0
        missing_step = None
        
        for r in reqs:
            key = f"{r['req_type']}:{r['req_id']}"
            have = owned_map.get(key)
            
            need_ca = int(r["min_class_ascend"])
            need_ce = int(r["min_class_elevate"])
            need_am = int(r["min_ag_meld"])
            need_ae = int(r["min_ag_elevate"])
            need_as = int(r["min_ag_spiritualize"])
            
            if not have:
                req_dist = 1 + need_ca + need_ce + need_am + need_ae + need_as
                total_dist += req_dist
                if req_dist == 1:
                    missing_step = (r["req_type"], int(r["req_id"]), "acquire")
            else:
                diff_ca = max(0, need_ca - int(have["class_ascend"]))
                diff_ce = max(0, need_ce - int(have["class_elevate"]))
                diff_am = max(0, need_am - int(have["ag_meld"]))
                diff_ae = max(0, need_ae - int(have["ag_elevate"]))
                diff_as = max(0, need_as - int(have["ag_spiritualize"]))
                
                req_dist = diff_ca + diff_ce + diff_am + diff_ae + diff_as
                total_dist += req_dist
                
                if req_dist == 1:
                    if diff_ca == 1: missing_step = (r["req_type"], int(r["req_id"]), "ascend")
                    elif diff_ce == 1: missing_step = (r["req_type"], int(r["req_id"]), "elevate")
                    elif diff_am == 1: missing_step = (r["req_type"], int(r["req_id"]), "meld")
                    elif diff_ae == 1: missing_step = (r["req_type"], int(r["req_id"]), "elevate_ag")
                    elif diff_as == 1: missing_step = (r["req_type"], int(r["req_id"]), "spiritualize")
        
        if total_dist == 1 and missing_step:
            sk = f"{missing_step[0]}:{missing_step[1]}:{missing_step[2]}"
            if sk not in upgrades:
                name, rarity = _info_by_req(conn, missing_step[0], missing_step[1])
                upgrades[sk] = {
                    "req_type": missing_step[0],
                    "req_id": missing_step[1],
                    "name": name,
                    "rarity": rarity,
                    "action": missing_step[2],
                    "collections_count": 0,
                    "bonuses": {}
                }
            
            upgrades[sk]["collections_count"] += 1
            
            for bk, bv in bonus.items():
                val = bv["value"] if isinstance(bv, dict) else bv
                typ = bv["type"] if isinstance(bv, dict) else "flat"
                if bk not in upgrades[sk]["bonuses"]:
                    upgrades[sk]["bonuses"][bk] = {"value": 0.0, "type": typ}
                upgrades[sk]["bonuses"][bk]["value"] += val
                
    sorted_upgrades = sorted(upgrades.values(), key=lambda x: (-x["collections_count"], -len(x["bonuses"]), x["name"]))
    return sorted_upgrades[:10]

# -----------------------------------------------------------------------------
# Import / Export
# -----------------------------------------------------------------------------

@app.get("/api/missing_translations")
def api_missing_translations(conn: sqlite3.Connection = Depends(get_db)):
    ru_path = STATIC_DIR / "ru.json"
    if not ru_path.exists():
        return {"error": "ru.json not found"}
    
    with open(ru_path, "r", encoding="utf-8") as f:
        try:
            ru_data = json.load(f)
        except Exception:
            return {"error": "Failed to parse ru.json"}

    classes = [r["name"] for r in conn.execute("SELECT name FROM classes;").fetchall()]
    agathions = [r["name"] for r in conn.execute("SELECT name FROM agathions;").fetchall()]
    collections = [r["name"] for r in conn.execute("SELECT name FROM collections;").fetchall()]
    
    stats = set()
    for r in conn.execute("SELECT bonus_json FROM collections;").fetchall():
        if r["bonus_json"]:
            try:
                data = json.loads(r["bonus_json"])
                if isinstance(data, dict):
                    stats.update(data.keys())
            except Exception:
                pass

    missing_classes = [c for c in classes if c not in ru_data]
    missing_agathions = [a for a in agathions if a not in ru_data]
    missing_collections = [c for c in collections if c not in ru_data]
    missing_stats = [s for s in stats if s not in ru_data]

    return {
        "Classes": missing_classes,
        "Agathions": missing_agathions,
        "Collections": missing_collections,
        "Stats": sorted(list(missing_stats))
    }

class ExportCollectionReq(BaseModel):
    req_type: Literal["class", "agathion"]
    name: str

    min_class_ascend: Optional[int] = None
    min_class_elevate: Optional[int] = None

    min_ag_meld: Optional[int] = None
    min_ag_elevate: Optional[int] = None
    min_ag_spiritualize: Optional[int] = None

class ExportCollection(BaseModel):
    name: str
    bonus: Dict[str, Any] = Field(default_factory=dict)
    requirements: List[ExportCollectionReq] = Field(default_factory=list)

class ExportOwned(BaseModel):
    req_type: Literal["class", "agathion"]
    name: str

    class_ascend: Optional[int] = None
    class_elevate: Optional[int] = None

    ag_meld: Optional[int] = None
    ag_elevate: Optional[int] = None
    ag_spiritualize: Optional[int] = None

class ExportPayload(BaseModel):
    version: int = 1
    classes: List[ClassIn] = Field(default_factory=list)
    agathions: List[AgathionIn] = Field(default_factory=list)
    collections: List[ExportCollection] = Field(default_factory=list)
    owned: List[ExportOwned] = Field(default_factory=list)

class ExportOwnedPayload(BaseModel):
    version: int = 1
    owned: List[ExportOwned] = Field(default_factory=list)

@app.get("/api/export", response_model=ExportPayload, response_model_exclude_none=True)
def api_export(conn: sqlite3.Connection = Depends(get_db)) -> ExportPayload:

    classes_rows = conn.execute(
        "SELECT name, rarity, can_ascend, can_elevate FROM classes ORDER BY name;"
    ).fetchall()
    ag_rows = conn.execute(
        "SELECT name, rarity, can_meld, can_elevate, can_spiritualize FROM agathions ORDER BY name;"
    ).fetchall()

    col_rows = conn.execute("SELECT id, name, bonus_json FROM collections ORDER BY name;").fetchall()
    export_cols: List[ExportCollection] = []

    for c in col_rows:
        req_rows = conn.execute(
            """
            SELECT req_type, req_id,
                   min_class_ascend, min_class_elevate,
                   min_ag_meld, min_ag_elevate, min_ag_spiritualize
            FROM collection_requirements
            WHERE collection_id=?
            ORDER BY req_type, req_id;
            """,
            (c["id"],)
        ).fetchall()

        reqs: List[ExportCollectionReq] = []
        for r in req_rows:
            kwargs = {
                "req_type": r["req_type"],
                "name": _name_by_req(conn, r["req_type"], int(r["req_id"]))
            }
            if r["req_type"] == "class":
                kwargs["min_class_ascend"] = int(r["min_class_ascend"])
                kwargs["min_class_elevate"] = int(r["min_class_elevate"])
            else:
                kwargs["min_ag_meld"] = int(r["min_ag_meld"])
                kwargs["min_ag_elevate"] = int(r["min_ag_elevate"])
                kwargs["min_ag_spiritualize"] = int(r["min_ag_spiritualize"])
            reqs.append(ExportCollectionReq(**kwargs))

        bonus = json.loads(c["bonus_json"]) if c["bonus_json"] else {}
        export_cols.append(ExportCollection(name=c["name"], bonus=bonus, requirements=reqs))

    owned_rows = conn.execute(
        """
        SELECT req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize
        FROM user_db.owned
        ORDER BY req_type, req_id;
        """
    ).fetchall()

    export_owned: List[ExportOwned] = []
    for r in owned_rows:
        kwargs = {
            "req_type": r["req_type"],
            "name": _name_by_req(conn, r["req_type"], int(r["req_id"]))
        }
        if r["req_type"] == "class":
            kwargs["class_ascend"] = int(r["class_ascend"])
            kwargs["class_elevate"] = int(r["class_elevate"])
        else:
            kwargs["ag_meld"] = int(r["ag_meld"])
            kwargs["ag_elevate"] = int(r["ag_elevate"])
            kwargs["ag_spiritualize"] = int(r["ag_spiritualize"])
        export_owned.append(ExportOwned(**kwargs))

    return ExportPayload(
        version=1,
        classes=[
            ClassIn(
                name=row["name"],
                rarity=row["rarity"],
                can_ascend=bool(row["can_ascend"]),
                can_elevate=bool(row["can_elevate"]),
            )
            for row in classes_rows
        ],
        agathions=[
            AgathionIn(
                name=row["name"],
                rarity=row["rarity"],
                can_meld=bool(row["can_meld"]),
                can_elevate=bool(row["can_elevate"]),
                can_spiritualize=bool(row["can_spiritualize"]),
            )
            for row in ag_rows
        ],
        collections=export_cols,
        owned=export_owned,
    )

# Full database import endpoint: recreates the DB structure based on provided JSON
@app.post("/api/import", response_model=Dict[str, Any])
def api_import(payload: ExportPayload, conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    if payload.version != 1:
        raise HTTPException(status_code=400, detail="Unsupported version")

    def upsert_class(c: ClassIn) -> int:
        name = normalize_name(c.name)
        validate_class_rarity(c.rarity)
        conn.execute(
            """
            INSERT INTO classes(name, rarity, can_ascend, can_elevate)
            VALUES (?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
              rarity=excluded.rarity,
              can_ascend=excluded.can_ascend,
              can_elevate=excluded.can_elevate;
            """,
            (name, c.rarity, int(c.can_ascend), int(c.can_elevate))
        )
        row = conn.execute("SELECT id FROM classes WHERE name=?;", (name,)).fetchone()
        return int(row["id"])

    def upsert_ag(a: AgathionIn) -> int:
        name = normalize_name(a.name)
        validate_agathion_rarity(a.rarity)
        conn.execute(
            """
            INSERT INTO agathions(name, rarity, can_meld, can_elevate, can_spiritualize)
            VALUES (?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
              rarity=excluded.rarity,
              can_meld=excluded.can_meld,
              can_elevate=excluded.can_elevate,
              can_spiritualize=excluded.can_spiritualize;
            """,
            (name, a.rarity, int(a.can_meld), int(a.can_elevate), int(a.can_spiritualize))
        )
        row = conn.execute("SELECT id FROM agathions WHERE name=?;", (name,)).fetchone()
        return int(row["id"])

    class_name_to_id: Dict[str, int] = {}
    ag_name_to_id: Dict[str, int] = {}

    for c in payload.classes:
        class_name_to_id[normalize_name(c.name)] = upsert_class(c)
    for a in payload.agathions:
        ag_name_to_id[normalize_name(a.name)] = upsert_ag(a)

    imported_cols = 0
    for col in payload.collections:
        col_name = normalize_name(col.name)
        bonus_json = json.dumps(normalize_bonus(col.bonus), ensure_ascii=False)

        conn.execute(
            """
            INSERT INTO collections(name, bonus_json)
            VALUES (?,?)
            ON CONFLICT(name) DO UPDATE SET bonus_json=excluded.bonus_json;
            """,
            (col_name, bonus_json)
        )
        col_id_row = conn.execute("SELECT id FROM collections WHERE name=?;", (col_name,)).fetchone()
        col_id = int(col_id_row["id"])

        conn.execute("DELETE FROM collection_requirements WHERE collection_id=?;", (col_id,))

        for r in col.requirements:
            req_name = normalize_name(r.name)

            if r.req_type == "class":
                rid = class_name_to_id.get(req_name)
                if rid is None:
                    rr = conn.execute("SELECT id FROM classes WHERE name=?;", (req_name,)).fetchone()
                    if not rr:
                        raise HTTPException(status_code=400, detail=f"Import error: class not found: {req_name}")
                    rid = int(rr["id"])
            else:
                rid = ag_name_to_id.get(req_name)
                if rid is None:
                    rr = conn.execute("SELECT id FROM agathions WHERE name=?;", (req_name,)).fetchone()
                    if not rr:
                        raise HTTPException(status_code=400, detail=f"Import error: agathion not found: {req_name}")
                    rid = int(rr["id"])

            conn.execute(
                """
                INSERT INTO collection_requirements(
                  collection_id, req_type, req_id,
                  min_class_ascend, min_class_elevate,
                  min_ag_meld, min_ag_elevate, min_ag_spiritualize
                ) VALUES (?,?,?,?,?,?,?,?);
                """,
                (
                    col_id, r.req_type, rid,
                    int(r.min_class_ascend or 0), int(r.min_class_elevate or 0),
                    int(r.min_ag_meld or 0), int(r.min_ag_elevate or 0), int(r.min_ag_spiritualize or 0)
                )
            )

        imported_cols += 1

    imported_owned = 0
    for o in payload.owned:
        item_name = normalize_name(o.name)

        if o.req_type == "class":
            rr = conn.execute("SELECT id FROM classes WHERE name=?;", (item_name,)).fetchone()
            if not rr:
                continue
            rid = int(rr["id"])
            conn.execute(
                """
                INSERT INTO user_db.owned(req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize)
                VALUES ('class', ?, ?, ?, 0, 0, 0)
                ON CONFLICT(req_type, req_id) DO UPDATE SET
                  class_ascend=excluded.class_ascend,
                  class_elevate=excluded.class_elevate;
                """,
                (rid, int(o.class_ascend or 0), int(o.class_elevate or 0))
            )
        else:
            rr = conn.execute("SELECT id FROM agathions WHERE name=?;", (item_name,)).fetchone()
            if not rr:
                continue
            rid = int(rr["id"])
            conn.execute(
                """
                INSERT INTO user_db.owned(req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize)
                VALUES ('agathion', ?, 0, 0, ?, ?, ?)
                ON CONFLICT(req_type, req_id) DO UPDATE SET
                  ag_meld=excluded.ag_meld,
                  ag_elevate=excluded.ag_elevate,
                  ag_spiritualize=excluded.ag_spiritualize;
                """,
                (rid, int(o.ag_meld or 0), int(o.ag_elevate or 0), int(o.ag_spiritualize or 0))
            )

        imported_owned += 1

    conn.commit()

    return {"ok": True, "imported_collections": imported_cols, "imported_owned": imported_owned}

@app.get("/api/export_owned", response_model=ExportOwnedPayload, response_model_exclude_none=True)
def api_export_owned(conn: sqlite3.Connection = Depends(get_db)) -> ExportOwnedPayload:
    owned_rows = conn.execute(
        """
        SELECT req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize
        FROM user_db.owned
        ORDER BY req_type, req_id;
        """
    ).fetchall()

    export_owned: List[ExportOwned] = []
    for r in owned_rows:
        kwargs = {
            "req_type": r["req_type"],
            "name": _name_by_req(conn, r["req_type"], int(r["req_id"]))
        }
        if r["req_type"] == "class":
            kwargs["class_ascend"] = int(r["class_ascend"])
            kwargs["class_elevate"] = int(r["class_elevate"])
        else:
            kwargs["ag_meld"] = int(r["ag_meld"])
            kwargs["ag_elevate"] = int(r["ag_elevate"])
            kwargs["ag_spiritualize"] = int(r["ag_spiritualize"])
        export_owned.append(ExportOwned(**kwargs))

    return ExportOwnedPayload(version=1, owned=export_owned)

@app.post("/api/import_owned", response_model=Dict[str, Any])
def api_import_owned(payload: ExportOwnedPayload, conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    if payload.version != 1:
        raise HTTPException(status_code=400, detail="Unsupported version")

    # Очищаем таблицу перед импортом
    conn.execute("DELETE FROM user_db.owned;")

    imported_owned = 0
    for o in payload.owned:
        item_name = normalize_name(o.name)
        if o.req_type == "class":
            rr = conn.execute("SELECT id FROM classes WHERE name=?;", (item_name,)).fetchone()
            if not rr:
                continue
            rid = int(rr["id"])
            conn.execute(
                "INSERT INTO user_db.owned(req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize) VALUES ('class', ?, ?, ?, 0, 0, 0)",
                (rid, int(o.class_ascend or 0), int(o.class_elevate or 0))
            )
        else:
            rr = conn.execute("SELECT id FROM agathions WHERE name=?;", (item_name,)).fetchone()
            if not rr:
                continue
            rid = int(rr["id"])
            conn.execute(
                "INSERT INTO user_db.owned(req_type, req_id, class_ascend, class_elevate, ag_meld, ag_elevate, ag_spiritualize) VALUES ('agathion', ?, 0, 0, ?, ?, ?)",
                (rid, int(o.ag_meld or 0), int(o.ag_elevate or 0), int(o.ag_spiritualize or 0))
            )
        imported_owned += 1

    conn.commit()
    return {"ok": True, "imported_owned": imported_owned}
