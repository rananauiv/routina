"""fortcore: headless logic for 'For Thy Lord' (constants, theme, db, names, dialogue, core, nemesis, selftest). No UI imports."""
from __future__ import annotations

import csv
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------------------------------- constants
PRICES = {"archer": 5, "wizard": 8, "rogue": 6}
MAX_OWNED_UNITS = 3000
LEGENDARY_COST = 1000
LEGENDARY_SACRIFICE = 100
UPGRADE_COST = {1: 4, 2: 8}
LEGENDARY_LEVEL = 4
SCOUT_COST = 1
MAX_DEPLOY = 10
MAX_ROUNDS = 4
FIELD_COLS, FIELD_ROWS = 12, 8
WORLD_W, WORLD_H = 5, 4
BOUNTY = {"goon": 1, "captain": 5, "lord": 20}
RIVAL_MULT = 3
RIVAL_VICTORIES = 2
HOUSE_RULE_TRAIT_MODS = False
N_CAPTAINS, N_GOONS = 6, 20
ROLES = {
    "archer": {"move": 2, "rng": 3, "intel": 0},
    "wizard": {"move": 2, "rng": 2, "intel": 1},
    "rogue": {"move": 3, "rng": 1, "intel": 1},
}
TRAITS = ["Boastful", "Coward", "Brutal", "Honorable", "Vengeful", "Greedy", "Fears Fire",
          "Fears Arrows", "Loyal", "Treacherous", "Proud", "Cunning", "Stubborn", "Merciless"]
TRAIT_WEAK = {"Fears Fire": "wizard", "Fears Arrows": "archer", "Coward": "rogue"}
TRAIT_STRONG = {"Brutal": "rogue", "Cunning": "wizard", "Honorable": "archer"}
DEFAULT_THEME = {"background": "#000000", "panel": "#161616", "text": "#f7f7f7",
                 "accent": "#20d20d", "button": "#101010"}
THEME_KEYS = ("background", "panel", "text", "accent", "button")
SECRET_KEY = "_secret_total_tasks_completed_all_time"
COPYRIGHT_TEXT = ("The Nemesis-style system in this game is inspired by the Nemesis System concept. "
                  "In that concept the player is a specific avatar; in this game the player avatar "
                  "does not exist. Made by madhav u.")


class GameError(Exception):
    """Raised for any rejected game action."""


def now() -> str:
    """Return the current local time as an ISO string."""
    return datetime.now().isoformat(timespec="seconds")


def effective_level(level: int, legendary) -> int:
    """Return the effective level (Legendary counts as 4)."""
    return LEGENDARY_LEVEL if legendary else int(level)


def win_chance(eff: int) -> int:
    """Return the win percentage for an effective level."""
    return min(100, 25 * eff)


def survive_chance(eff: int) -> int:
    """Return the survive-on-loss percentage for an effective level."""
    return min(90, 20 * eff)


def trait_modifier(traits, cls: str) -> int:
    """Return the optional house-rule win-point modifier for a class against traits."""
    if not HOUSE_RULE_TRAIT_MODS:
        return 0
    mod = 0
    for t in traits:
        if TRAIT_WEAK.get(t) == cls:
            mod += 10
        if TRAIT_STRONG.get(t) == cls:
            mod -= 10
    return mod


# ----------------------------------------------------------------------------- theme
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def valid_hex(v) -> bool:
    """Return True if v is a #rrggbb string."""
    return isinstance(v, str) and bool(_HEX.match(v))


class Theme:
    """Single shared colour theme with observers."""

    def __init__(self, colors=None, mute=False, reduce_motion=False):
        """Create a theme from optional colour overrides and flags."""
        self.colors = dict(DEFAULT_THEME)
        for k, v in (colors or {}).items():
            if k in THEME_KEYS and valid_hex(v):
                self.colors[k] = v.lower()
        self.mute = bool(mute)
        self.reduce_motion = bool(reduce_motion)
        self.palette_version = 0
        self._obs = []

    def __getattr__(self, k):
        """Expose colours as attributes (background, panel, text, accent, button)."""
        c = self.__dict__.get("colors")
        if c is not None and k in c:
            return c[k]
        raise AttributeError(k)

    def subscribe(self, cb) -> None:
        """Register an observer called with the theme on every change."""
        if cb not in self._obs:
            self._obs.append(cb)

    def unsubscribe(self, cb) -> None:
        """Remove an observer."""
        if cb in self._obs:
            self._obs.remove(cb)

    def _notify(self) -> None:
        """Call all observers, ignoring their failures."""
        for cb in list(self._obs):
            try:
                cb(self)
            except Exception:
                pass

    def set_color(self, key: str, hex_: str) -> bool:
        """Set one colour and notify; returns False for invalid input."""
        if key not in THEME_KEYS or not valid_hex(hex_):
            return False
        self.colors[key] = hex_.lower()
        self.palette_version += 1
        self._notify()
        return True

    def set_flag(self, name: str, value: bool) -> None:
        """Set mute or reduce_motion and notify."""
        if name in ("mute", "reduce_motion"):
            setattr(self, name, bool(value))
            self._notify()

    def reset(self) -> None:
        """Restore default colours."""
        self.colors = dict(DEFAULT_THEME)
        self.palette_version += 1
        self._notify()

    def to_json(self) -> str:
        """Serialize colours to JSON."""
        return json.dumps(self.colors)

    @classmethod
    def from_json(cls, s: str, mute=False, reduce_motion=False) -> "Theme":
        """Build a theme from JSON, tolerating bad data."""
        try:
            data = json.loads(s)
            if not isinstance(data, dict):
                data = {}
        except (TypeError, ValueError):
            data = {}
        return cls(data, mute, reduce_motion)


# ----------------------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tokens(id INTEGER PRIMARY KEY CHECK(id=1), balance INT, total_earned INT, total_spent INT);
CREATE TABLE IF NOT EXISTS awarded_tasks(task_key TEXT PRIMARY KEY, awarded_at TEXT);
CREATE TABLE IF NOT EXISTS campaign(id INTEGER PRIMARY KEY, seed INT, created_at TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS regions(id INTEGER PRIMARY KEY, campaign_id INT, name TEXT, gx INT, gy INT,
  state TEXT CHECK(state IN ('hidden','hostile','conquered')), fortress_id INT);
CREATE TABLE IF NOT EXISTS fortresses(id INTEGER PRIMARY KEY, region_id INT, name TEXT, raids INT DEFAULT 0, conquered INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY, name TEXT UNIQUE,
  class TEXT CHECK(class IN ('archer','wizard','rogue')), level INT CHECK(level BETWEEN 1 AND 3),
  legendary INT DEFAULT 0, origin TEXT DEFAULT 'bought',
  status TEXT DEFAULT 'ready' CHECK(status IN ('ready','dead','sacrificed')), kills INT DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS enemies(id INTEGER PRIMARY KEY, name TEXT, epithet TEXT, title TEXT,
  rank TEXT CHECK(rank IN ('lord','captain','goon')), level INT, fortress_id INT, traits_json TEXT,
  victories INT DEFAULT 0, intel INT DEFAULT 0, rival INT DEFAULT 0,
  status TEXT CHECK(status IN ('active','dead','defected','exiled')));
CREATE TABLE IF NOT EXISTS history_log(id INTEGER PRIMARY KEY, ts TEXT, event_type TEXT, enemy_id INT, unit_id INT, fortress_id INT, details TEXT);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS task_completions(task_id INT NOT NULL, completion_date TEXT NOT NULL, PRIMARY KEY(task_id, completion_date));
CREATE INDEX IF NOT EXISTS ix_units ON units(status, class, level);
CREATE INDEX IF NOT EXISTS ix_enemies ON enemies(fortress_id, status);
CREATE INDEX IF NOT EXISTS ix_hist ON history_log(enemy_id);
"""
DB_NAME = "routina_data.sqlite3"
BOOTSTRAP_NAME = "routina_bootstrap.json"
_CORRUPT_WORDS = ("malformed", "not a database", "integrity", "disk image", "corrupt")


class Database:
    """SQLite wrapper: WAL, explicit transactions, backup recovery."""

    VISIBLE_KEYS = ("chart_type", "mute", "reduce_motion", "theme_json", "data_path_note")

    def __init__(self, path, rng=None):
        """Open (and if needed recover) the database at path."""
        self.path = str(path)
        self.rng = rng or random.Random()
        self.last_warning = None
        self._depth = 0
        self.conn = self._open_with_recovery()
        self._init_schema()
        self.backup()

    def _connect(self, path=None):
        """Open one connection and verify integrity."""
        c = sqlite3.connect(path or self.path, timeout=5, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            r = c.execute("PRAGMA integrity_check").fetchone()
            if r[0] != "ok":
                raise sqlite3.DatabaseError("integrity check failed")
        except Exception:
            c.close()
            raise
        return c

    def _open_with_recovery(self):
        """Connect; on corruption restore the backup copy, on lock use a backup copy; warn."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connect()
        except sqlite3.Error as exc:
            msg = str(exc).lower()
            bak = self.path + ".bak"
            if "locked" in msg and os.path.exists(bak):
                alt = self.path + ".locked-copy.sqlite3"
                shutil.copy2(bak, alt)
                self.path = alt
                self.last_warning = "Database is locked; working on a backup copy instead: " + alt
                return self._connect()
            if any(w in msg for w in _CORRUPT_WORDS) and os.path.exists(bak):
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                for suf in ("", "-wal", "-shm"):
                    if os.path.exists(self.path + suf):
                        try:
                            os.replace(self.path + suf, self.path + ".corrupt-" + stamp + suf)
                        except OSError:
                            pass
                shutil.copy2(bak, self.path)
                self.last_warning = "Database was corrupt; restored the latest backup copy."
                return self._connect()
            raise GameError("Cannot open database: %s" % exc)

    def _init_schema(self):
        """Create tables and seed rows."""
        with self.tx() as c:
            for stmt in SCHEMA.split(";\n"):
                if stmt.strip():
                    c.execute(stmt)
            c.execute("INSERT OR IGNORE INTO tokens(id,balance,total_earned,total_spent) VALUES(1,0,0,0)")
            c.execute("INSERT OR IGNORE INTO config(key,value) VALUES(?,?)", (SECRET_KEY, "0"))
            c.execute("INSERT OR IGNORE INTO config(key,value) VALUES('chart_type','bar')")
            c.execute("INSERT OR IGNORE INTO task_completions(task_id,completion_date) "
                      "SELECT id, substr(created_at,1,10) FROM tasks WHERE completed=1 AND id NOT IN "
                      "(SELECT task_id FROM task_completions)")

    @contextmanager
    def tx(self):
        """Run a block inside one transaction (re-entrant)."""
        if self._depth > 0:
            self._depth += 1
            try:
                yield self.conn
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except BaseException:
            try:
                self.conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            self._depth = 0

    def get_config(self, key, default=None):
        """Read a config value."""
        r = self.conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_config(self, key, value) -> None:
        """Write a config value."""
        with self.tx() as c:
            c.execute("INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    def visible_config(self):
        """Return config rows from the explicit whitelist only."""
        q = ",".join("?" for _ in self.VISIBLE_KEYS)
        return [tuple(r) for r in self.conn.execute(
            "SELECT key,value FROM config WHERE key IN (%s) ORDER BY key" % q, self.VISIBLE_KEYS)]

    def secret_total(self) -> int:
        """Return the hidden all-time completion counter."""
        return int(self.get_config(SECRET_KEY, "0") or 0)

    def award_task(self, task_key: str) -> bool:
        """Award +1 token once per task_key; returns False for duplicates."""
        with self.tx() as c:
            cur = c.execute("INSERT OR IGNORE INTO awarded_tasks(task_key,awarded_at) VALUES(?,?)", (task_key, now()))
            if cur.rowcount == 0:
                return False
            c.execute("UPDATE config SET value=CAST(COALESCE(value,'0') AS INTEGER)+1 WHERE key=?", (SECRET_KEY,))
            c.execute("UPDATE tokens SET balance=balance+1,total_earned=total_earned+1 WHERE id=1")
        return True

    def add_tokens(self, n: int) -> None:
        """Add tokens (counted as earned)."""
        with self.tx() as c:
            c.execute("UPDATE tokens SET balance=balance+?,total_earned=total_earned+? WHERE id=1", (n, n))

    def balance(self) -> dict:
        """Return the token row as a dict."""
        return dict(self.conn.execute("SELECT balance,total_earned,total_spent FROM tokens WHERE id=1").fetchone())

    def spend(self, amount: int) -> bool:
        """Spend tokens atomically; False if insufficient."""
        with self.tx() as c:
            bal = c.execute("SELECT balance FROM tokens WHERE id=1").fetchone()[0]
            if bal < amount:
                return False
            c.execute("UPDATE tokens SET balance=balance-?,total_spent=total_spent+? WHERE id=1", (amount, amount))
        return True

    def log(self, event_type, enemy_id=None, unit_id=None, fortress_id=None, details="") -> None:
        """Append a history_log row."""
        with self.tx() as c:
            c.execute("INSERT INTO history_log(ts,event_type,enemy_id,unit_id,fortress_id,details) VALUES(?,?,?,?,?,?)",
                      (now(), event_type, enemy_id, unit_id, fortress_id, details))

    def save_theme(self, theme: Theme) -> None:
        """Persist theme colours and flags."""
        with self.tx():
            self.set_config("theme_json", theme.to_json())
            self.set_config("mute", int(theme.mute))
            self.set_config("reduce_motion", int(theme.reduce_motion))

    def load_theme(self) -> Theme:
        """Restore the saved theme (defaults if none)."""
        return Theme.from_json(self.get_config("theme_json", ""), self.get_config("mute", "0") == "1",
                               self.get_config("reduce_motion", "0") == "1")

    def backup(self):
        """Write a .bak copy via the SQLite backup API; returns its path or None."""
        dst = None
        try:
            bak = self.path + ".bak"
            dst = sqlite3.connect(bak)
            self.conn.backup(dst)
            return bak
        except Exception:
            return None
        finally:
            if dst is not None:
                dst.close()

    def close(self) -> None:
        """Back up and close."""
        try:
            self.backup()
            self.conn.close()
        except Exception:
            pass


def db_file(directory) -> Path:
    """Return the database file path inside a directory."""
    return Path(directory) / DB_NAME


def load_bootstrap(app_dir):
    """Read the stored data path from the bootstrap JSON (or None)."""
    try:
        with open(Path(app_dir) / BOOTSTRAP_NAME, "r", encoding="utf-8") as f:
            p = json.load(f).get("data_path")
        return p if isinstance(p, str) and p else None
    except (OSError, ValueError, AttributeError):
        return None


def save_bootstrap(app_dir, data_path) -> bool:
    """Store only the data path in the bootstrap JSON; False if not writable."""
    try:
        with open(Path(app_dir) / BOOTSTRAP_NAME, "w", encoding="utf-8") as f:
            json.dump({"data_path": str(data_path)}, f)
        return True
    except OSError:
        return False


def validate_data_path(p) -> tuple:
    """Return (ok, message) for a candidate data folder."""
    try:
        if not p or not str(p).strip():
            return False, "path is empty"
        d = Path(str(p).strip())
        if not d.is_dir():
            return False, "folder does not exist"
        probe = d / (".write_test_%d" % os.getpid())
        with open(probe, "w") as f:
            f.write("x")
        probe.unlink()
        return True, "ok"
    except OSError as exc:
        return False, "not writable (%s)" % exc


def migrate_data(old_dir, new_dir) -> str:
    """Copy the database from old_dir to new_dir (existing target is kept as .bak)."""
    src, dst = db_file(old_dir), db_file(new_dir)
    if not src.exists() or src.resolve() == dst.resolve():
        return "nothing to migrate"
    if dst.exists():
        shutil.copy2(dst, str(dst) + ".premigrate.bak")
        dst.unlink()
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    return "migrated"


def open_database(app_dir, rng=None) -> Database:
    """Open the database at the bootstrap path, falling back to the app folder with a warning."""
    warn = None
    folder = str(app_dir)
    p = load_bootstrap(app_dir)
    if p:
        ok, msg = validate_data_path(p)
        if ok:
            folder = p
        else:
            warn = "Data path '%s' is invalid (%s); using the default location." % (p, msg)
    try:
        db = Database(db_file(folder), rng)
    except GameError:
        if folder == str(app_dir):
            raise
        db = Database(db_file(app_dir), rng)
        warn = (warn or "") + " Could not open the database at '%s'; using default." % folder
    if warn:
        db.last_warning = (warn + " " + (db.last_warning or "")).strip()
    return db


DATASETS = ("Tasks", "Completions", "Config")


def viewer_rows(db: Database, dataset: str):
    """Return (columns, rows) for the data viewer; config uses the whitelist only."""
    if dataset == "Tasks":
        cols = ["id", "name", "completed", "created_at"]
        rows = [tuple(r) for r in db.conn.execute("SELECT id,name,completed,created_at FROM tasks ORDER BY id")]
    elif dataset == "Completions":
        cols = ["task_id", "task", "completion_date"]
        rows = [tuple(r) for r in db.conn.execute(
            "SELECT c.task_id,t.name,c.completion_date FROM task_completions c "
            "LEFT JOIN tasks t ON t.id=c.task_id ORDER BY c.completion_date,c.task_id")]
    else:
        cols = ["key", "value"]
        rows = [r for r in db.visible_config() if not str(r[0]).startswith("_secret_")]
    return cols, rows


def export_csv(db: Database, dataset: str, path) -> int:
    """Write the viewer dataset to CSV; returns the row count."""
    cols, rows = viewer_rows(db, dataset)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return len(rows)


def completion_series(db: Database, days: int = 30):
    """Return [(date, count)] of task completions for charts."""
    return [tuple(r) for r in db.conn.execute(
        "SELECT completion_date,COUNT(*) FROM task_completions GROUP BY completion_date "
        "ORDER BY completion_date DESC LIMIT ?", (days,))][::-1]


# ----------------------------------------------------------------------------- names
def roman(n: int) -> str:
    """Return n as a Roman numeral."""
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
                 (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += s
            n -= v
    return out


class NameGenerator:
    """Unique name factory (>=50,000 combinations plus Roman-numeral fallback)."""

    ONS = ["b", "br", "d", "dr", "g", "gr", "k", "kr", "l", "m", "n", "r", "s", "sh", "t", "th", "v", "z"]
    NUC = ["a", "e", "i", "o", "u", "ar", "or", "ek"]
    COD = ["", "n", "k", "th", "s", "r"]
    EPITHETS = ["the Grim", "Ironhand", "the Pale", "Bonecleaver", "the Red", "Oathbreaker", "the Cruel",
                "Stormborn", "the Lame", "Ashmouth", "the Hollow", "Blackbrow", "the Hungry", "Wolfbane"]
    POWER = ["the Unbroken", "the Merciless", "Warbringer", "the Terrible", "Skullsplitter", "the Undying",
             "Doomcaller", "the Conqueror"]
    PRE = ["Ash", "Black", "Cinder", "Dread", "Frost", "Grim", "Iron", "Raven", "Storm", "Thorn", "Wolf", "Ember"]
    SUF = ["moor", "fell", "hold", "vale", "reach", "marsh", "crag", "wood", "barrow", "mere"]
    FORT = ["Keep", "Citadel", "Bastion", "Hold", "Redoubt"]

    def __init__(self, rng, taken=None):
        """Create a generator avoiding the names in taken."""
        self.rng = rng
        self.taken = set(taken or ())

    def capacity(self) -> int:
        """Return the number of distinct base names."""
        s = len(self.ONS) * len(self.NUC)
        return (s * s + s ** 3) * len(self.COD)

    def _base(self, syl: int) -> str:
        """Build one base name."""
        r = self.rng
        return ("".join(r.choice(self.ONS) + r.choice(self.NUC) for _ in range(syl)) + r.choice(self.COD)).capitalize()

    def _unique(self, choices) -> str:
        """Return a name not yet taken, using Roman numerals if needed."""
        for _ in range(40):
            n = self._base(self.rng.choice(choices))
            if n not in self.taken:
                self.taken.add(n)
                return n
        base, k = self._base(2), 2
        while True:
            n = "%s %s" % (base, roman(k))
            if n not in self.taken:
                self.taken.add(n)
                return n
            k += 1

    def unit_name(self) -> str:
        """Generate a unique unit name."""
        return self._unique((2, 2, 3))

    def enemy_name(self) -> str:
        """Generate a unique enemy name."""
        return self._unique((2, 3))

    def reserve(self, name) -> None:
        """Mark a name as used."""
        self.taken.add(name)

    def epithet(self, power=False) -> str:
        """Pick an epithet."""
        return self.rng.choice(self.POWER if power else self.EPITHETS)

    def region_name(self, used=()) -> str:
        """Generate a region name not in used."""
        for _ in range(60):
            n = self.rng.choice(self.PRE) + self.rng.choice(self.SUF)
            if n not in used:
                return n
        return self.rng.choice(self.PRE) + self.rng.choice(self.SUF) + " " + roman(len(used) + 1)

    def fortress_name(self, region: str) -> str:
        """Generate a fortress name for a region."""
        return "%s %s" % (region, self.rng.choice(self.FORT))


# ----------------------------------------------------------------------------- dialogue
TEMPLATES = {
    "pre_fight": [
        (None, "So {unit} the {class} dares face {enemy}?"),
        (None, "Another {class}. {enemy} has broken a hundred of your kind."),
        (None, "Hold your ground, {unit}. It will not save you."),
        (None, "The walls hear every fool who comes. Name yourself, {class}."),
        ("Boastful", "{unit}? A {class} sent to face {enemy}? Go on, I'll count the seconds."),
        ("Boastful", "Sing of {enemy} when you fall, {unit}!"),
        ("Coward", "Stay back, {class}! I will not be blamed for what happens."),
        ("Coward", "Surely we can talk, {unit}? Surely?"),
        ("Brutal", "I will break you slowly, {unit}."),
        ("Honorable", "Face me fairly, {unit}. {enemy} fears no honest blade."),
        ("Vengeful", "{unit}... your army owes {enemy} a debt."),
        ("Greedy", "Gold or steel, {unit}, {enemy} will take both."),
        ("Fears Fire", "Keep your flames away, {class}!"),
        ("Fears Arrows", "Keep that bow away from me, {class}. I know what it did to my cousins."),
        ("Loyal", "Not one step past me, {unit}. The Lord is behind these walls."),
        ("Treacherous", "Come closer, {unit}. {enemy} will not bite. Much."),
        ("Proud", "Kneel, {class}. You stand before {enemy}."),
        ("Cunning", "I read your army like a book, {unit}."),
    ],
    "victory_taunt": [
        (None, "{unit} falls. {enemy} remembers."),
        (None, "Hear it said: {title}!"),
        (None, "Tell the rest of your army that {unit} fell to {enemy}."),
        ("Boastful", "Too easy, {unit}. Bring ten more!"),
        ("Cunning", "Too easy, {unit}. Whoever sent you counted on luck."),
        ("Brutal", "Crushed, {unit}. Like the others."),
        ("Vengeful", "One more debt paid, {unit}."),
        ("Greedy", "I'll take your boots, {unit}."),
        ("Proud", "{unit} was never my equal."),
        ("Treacherous", "Did you really think I would fight fair, {unit}?"),
        ("Honorable", "A good fight, {unit}. {enemy} will not forget you."),
        ("Coward", "I won? Did you see that? I actually won!"),
    ],
    "defeat_line": [
        (None, "Impossible... {unit} bested {enemy}."),
        (None, "Remember my name, {class}."),
        ("Honorable", "Well fought, {unit}. Do with {enemy} what you will."),
        ("Boastful", "This... this does not count!"),
        ("Coward", "Mercy, {unit}! I'll serve anyone!"),
        ("Brutal", "You will pay for this..."),
        ("Treacherous", "Spare me and {enemy} will make it worth your while."),
        ("Proud", "A {class}... defeated {enemy}... shameful."),
        ("Greedy", "Take my purse, {unit}, take it all!"),
        ("Loyal", "Forgive me, my lord..."),
    ],
    "recruit_line": [
        (None, "{enemy} joins your banner. {title} serves now."),
        (None, "I once crushed {victim}; now I stand with you."),
        (None, "Point me at the walls, {unit}. I know where the cracks are."),
        ("Vengeful", "My grudge now wears your colours."),
        ("Greedy", "Pay well, and {enemy} fights well."),
        ("Loyal", "A new banner, the same oath: I do not break it."),
        ("Treacherous", "I have changed sides before. This time I mean it."),
    ],
    "rival_return": [
        (None, "The army that slew {victim} returns. {title} remembers every face."),
        (None, "{victim} was only the beginning, {unit}."),
        (None, "A {class} again... like {victim}. I remember how that ended."),
        ("Boastful", "Ah, {victim}'s friend! Did {victim} send you?"),
        ("Brutal", "I broke {victim}. You are next, {unit}."),
        ("Cunning", "I studied how {victim} died. You will fare no better."),
        ("Proud", "{title} stands before you, {unit}. Bow."),
        ("Honorable", "{victim} fought well. Show me you can match them."),
    ],
    "promotion": [
        (None, "From the ranks I rose, and {title} is my name now. Fear it."),
        (None, "A captain's cloak fits {enemy} well."),
        (None, "{enemy} was a goon yesterday. Today, a captain."),
        ("Boastful", "Behold! {enemy} the Captain!"),
        ("Proud", "At last the others kneel to {enemy}."),
        ("Loyal", "I will hold this post until the end."),
        ("Brutal", "Captain now. More heads to break."),
        ("Cunning", "Every rank is a step toward the throne."),
    ],
}
SLOT_DEFAULTS = {"enemy": "the enemy", "unit": "you", "class": "soldier", "victim": "the fallen",
                 "title": "the Nameless"}


class _Safe(dict):
    """format_map helper that tolerates missing slots."""

    def __missing__(self, k):
        """Return a default for an unknown slot."""
        return SLOT_DEFAULTS.get(k, "someone")


class DialogueBook:
    """Template picker that never repeats a template until its pool is exhausted."""

    def __init__(self, rng):
        """Create a book with an injectable RNG."""
        self.rng = rng
        self.used = {}

    def template_count(self) -> int:
        """Return the total number of templates."""
        return sum(len(v) for v in TEMPLATES.values())

    def _pool(self, situation, traits):
        """Return (index, trait, text) rows usable for these traits."""
        return [(i, tr, tx) for i, (tr, tx) in enumerate(TEMPLATES[situation]) if tr is None or tr in traits]

    def remaining(self, situation) -> int:
        """Return how many templates are unused in a situation."""
        return len(TEMPLATES[situation]) - len(self.used.get(situation, ()))

    def line(self, situation: str, traits=(), **slots) -> str:
        """Return a formatted line for the situation."""
        pool = self._pool(situation, traits)
        used = self.used.setdefault(situation, set())
        fresh = [p for p in pool if p[0] not in used]
        if not fresh:
            used.clear()
            fresh = pool
        spec = [p for p in fresh if p[1] is not None]
        pick = self.rng.choice(spec if spec and self.rng.random() < 0.6 else fresh)
        used.add(pick[0])
        return pick[2].format_map(_Safe(slots))


# ----------------------------------------------------------------------------- nemesis
def _edict(row) -> dict:
    """Convert an enemy row to a dict with parsed traits."""
    d = dict(row)
    try:
        tj = json.loads(d.get("traits_json") or "{}")
    except ValueError:
        tj = {}
    d["traits"] = tj.get("traits", [])
    d["scars"] = tj.get("scars", 0)
    d["victims"] = tj.get("victims", [])
    return d


class Nemesis:
    """Persistent enemy memory, hierarchy, rivals, intel and exile rules."""

    def __init__(self, db, rng, names, book):
        """Bind the database, RNG, name generator and dialogue book."""
        self.db, self.rng, self.names, self.book = db, rng, names, book

    def _new_enemy(self, fid, rank, level, epithet=""):
        """Insert one fresh enemy and return its id."""
        traits = self.rng.sample(TRAITS, self.rng.choice((2, 3)))
        tj = json.dumps({"traits": traits, "scars": 0, "victims": []})
        cur = self.db.conn.execute(
            "INSERT INTO enemies(name,epithet,title,rank,level,fortress_id,traits_json,victories,intel,rival,status) "
            "VALUES(?,?,?,?,?,?,?,0,0,0,'active')",
            (self.names.enemy_name(), epithet, "", rank, level, fid, tj))
        return cur.lastrowid

    def generate_fortress(self, fid: int) -> None:
        """Create 1 Lord (L3), 6 Captains and 20 Goons."""
        with self.db.tx():
            self._new_enemy(fid, "lord", 3, self.names.epithet())
            for _ in range(N_CAPTAINS):
                self._new_enemy(fid, "captain", self.rng.randint(1, 3))
            for _ in range(N_GOONS):
                self._new_enemy(fid, "goon", self.rng.randint(1, 3))

    def members(self, fid) -> list:
        """Return the living members of a fortress."""
        return [_edict(r) for r in self.db.conn.execute(
            "SELECT * FROM enemies WHERE fortress_id=? AND status IN ('active','exiled') ORDER BY id", (fid,))]

    def get(self, eid) -> dict:
        """Return one enemy dict."""
        r = self.db.conn.execute("SELECT * FROM enemies WHERE id=?", (eid,)).fetchone()
        if r is None:
            raise GameError("unknown enemy")
        return _edict(r)

    def _save_tj(self, e: dict) -> None:
        """Persist the traits/scars/victims JSON of an enemy dict."""
        self.db.conn.execute("UPDATE enemies SET traits_json=? WHERE id=?",
                             (json.dumps({"traits": e["traits"], "scars": e["scars"], "victims": e["victims"]}), e["id"]))

    def raise_intel(self, eid, n=1) -> None:
        """Raise intel (max 3)."""
        with self.db.tx() as c:
            c.execute("UPDATE enemies SET intel=MIN(3,intel+?) WHERE id=?", (n, eid))

    def record_duel(self, eid, unit_id, enemy_won: bool) -> None:
        """Record a duel result; a win stores the victim, title, scar and Rival status."""
        with self.db.tx() as c:
            e = self.get(eid)
            u = c.execute("SELECT name,class FROM units WHERE id=?", (unit_id,)).fetchone()
            if enemy_won and u is not None:
                e["victims"] = (e["victims"] + [{"name": u["name"], "class": u["class"]}])[-30:]
                e["scars"] += 1
                vic = e["victories"] + 1
                c.execute("UPDATE enemies SET victories=?,title=?,rival=CASE WHEN ?>=? THEN 1 ELSE rival END WHERE id=?",
                          (vic, "Slayer of " + u["name"], vic, RIVAL_VICTORIES, eid))
                self._save_tj(e)
                self.db.log("enemy_victory", eid, unit_id, e["fortress_id"], "slew " + u["name"])
            elif u is not None:
                self.db.log("enemy_defeat", eid, unit_id, e["fortress_id"], "beaten by " + u["name"])

    def flag_rivals(self) -> None:
        """Flag every enemy with enough victories as Rival."""
        with self.db.tx() as c:
            c.execute("UPDATE enemies SET rival=1 WHERE victories>=? AND rival=0", (RIVAL_VICTORIES,))

    def run_promotions(self, fid: int) -> list:
        """Fill vacant ranks, grant epithets and revenge levels; returns event strings."""
        ev = []
        with self.db.tx() as c:
            mem = self.members(fid)
            caps = [m for m in mem if m["rank"] == "captain"]
            goons = [m for m in mem if m["rank"] == "goon"]
            while len(caps) < N_CAPTAINS and goons:
                best = max(goons, key=lambda g: (g["victories"], g["level"], self.rng.random()))
                goons.remove(best)
                c.execute("UPDATE enemies SET rank='captain' WHERE id=?", (best["id"],))
                best["rank"] = "captain"
                caps.append(best)
                line = self.book.line("promotion", best["traits"], enemy=best["name"],
                                      title=best["title"] or best["name"])
                ev.append("%s is promoted to Captain: \"%s\"" % (best["name"], line))
                self.db.log("promotion", best["id"], None, fid, line)
            for _ in range(N_GOONS - len(goons)):
                self._new_enemy(fid, "goon", self.rng.randint(1, 3))
            for m in caps + [x for x in mem if x["rank"] == "lord"]:
                if m["victories"] >= 3 and not m["epithet"]:
                    ep = self.names.epithet(True)
                    c.execute("UPDATE enemies SET epithet=? WHERE id=?", (ep, m["id"]))
                    ev.append("%s earns the epithet %s" % (m["name"], ep))
                    self.db.log("epithet", m["id"], None, fid, ep)
            for m in mem:
                if m["victories"] >= 2 and m["rank"] != "lord":
                    lvl = min(3, max(m["level"], 1 + m["victories"] // 2))
                    if lvl > m["level"]:
                        c.execute("UPDATE enemies SET level=? WHERE id=?", (lvl, m["id"]))
                        ev.append("%s grows stronger (level %d)" % (m["name"], lvl))
                        self.db.log("revenge_level", m["id"], None, fid, "level %d" % lvl)
            self.flag_rivals()
        return ev

    def _targets(self, fid):
        """Return fortress ids ordered by distance from fortress fid (hostile first, then hidden)."""
        c = self.db.conn
        me = c.execute("SELECT r.gx,r.gy,r.campaign_id,r.id FROM regions r WHERE r.fortress_id=?", (fid,)).fetchone()
        if me is None:
            return []
        for state in ("hostile", "hidden"):
            rows = c.execute("SELECT fortress_id,gx,gy FROM regions WHERE campaign_id=? AND state=? AND id!=?",
                             (me["campaign_id"], state, me["id"])).fetchall()
            if rows:
                dist = [(abs(r["gx"] - me["gx"]) + abs(r["gy"] - me["gy"]), self.rng.random(), r["fortress_id"]) for r in rows]
                return [d[2] for d in sorted(dist)]
        return []

    def exile_captains(self, fid: int) -> list:
        """Surviving Captains flee to the nearest hostile fortress, displacing its weakest."""
        ev, touched = [], set()
        with self.db.tx() as c:
            fled = [m for m in self.members(fid) if m["rank"] == "captain"]
            for cap in fled:
                targets = self._targets(fid)
                if not targets:
                    c.execute("UPDATE enemies SET fortress_id=NULL,status='exiled' WHERE id=?", (cap["id"],))
                    ev.append("%s flees into the wilds" % cap["name"])
                    continue
                tid = targets[0]
                tm = self.members(tid)
                tcaps = sorted([m for m in tm if m["rank"] == "captain"], key=lambda m: (m["victories"], self.rng.random()))
                demoted = None
                if tcaps:
                    demoted = tcaps[0]
                    c.execute("UPDATE enemies SET rank='goon' WHERE id=?", (demoted["id"],))
                tgoons = sorted([m for m in tm if m["rank"] == "goon" and (demoted is None or m["id"] != demoted["id"])],
                                key=lambda m: (m["victories"], self.rng.random()))
                if tgoons:
                    c.execute("UPDATE enemies SET fortress_id=NULL,status='exiled' WHERE id=?", (tgoons[0]["id"],))
                c.execute("UPDATE enemies SET fortress_id=?,status='exiled' WHERE id=?", (tid, cap["id"]))
                touched.add(tid)
                ev.append("%s, exiled, takes a captaincy in another fortress%s" % (
                    cap["name"], (" (%s demoted)" % demoted["name"]) if demoted else ""))
                self.db.log("exile", cap["id"], None, tid, "fled from fortress %d" % fid)
            for t in touched:
                ev.extend(self.run_promotions(t))
        return ev

    def known_view(self, eid) -> dict:
        """Return only the information the current intel level reveals."""
        e = self.get(eid)
        i = e["intel"]
        v = {"id": eid, "intel": i, "rank": e["rank"], "name": "???", "rival": bool(e["rival"]), "status": e["status"]}
        if i >= 1:
            v.update(name=e["name"], epithet=e["epithet"], title=e["title"], scars=e["scars"])
        if i >= 2:
            v.update(traits=e["traits"], level=e["level"], victories=e["victories"])
        if i >= 3:
            v["history"] = [tuple(r) for r in self.db.conn.execute(
                "SELECT ts,event_type,details FROM history_log WHERE enemy_id=? ORDER BY id DESC LIMIT 12", (eid,))]
        return v

    def wanted_board(self, limit=12) -> list:
        """Return known enemies, Rivals first."""
        rows = self.db.conn.execute(
            "SELECT id FROM enemies WHERE status IN ('active','exiled') AND (rival=1 OR intel>0) "
            "ORDER BY rival DESC, victories DESC, intel DESC LIMIT ?", (limit,)).fetchall()
        return [self.known_view(r[0]) for r in rows]

    def dialogue_for(self, eid, situation, unit=None) -> str:
        """Return a context-aware line (revenge/rival lines override pre_fight)."""
        e = self.get(eid)
        vic = e["victims"]
        victim = vic[-1]["name"] if vic else "many foes"
        if situation == "pre_fight" and vic and unit is not None:
            same = [v for v in vic if v["class"] == unit.get("class")]
            if same or e["rival"]:
                situation = "rival_return"
                victim = (same or vic)[-1]["name"]
        slots = {"enemy": e["name"], "unit": unit["name"] if unit else "you", "class": unit["class"] if unit else "soldier",
                 "victim": victim, "title": e["title"] or e["name"]}
        return self.book.line(situation, e["traits"], **slots)


# ----------------------------------------------------------------------------- game core
class RaidState:
    """In-memory state of one raid (all outcomes are persisted as they happen)."""

    def __init__(self, region, fid):
        """Create an empty raid for a region."""
        self.region, self.fid = region, fid
        self.enemies, self.units = {}, {}
        self.phase, self.round = "scout", 1
        self.pending = None
        self.bounty = self.kills = self.turned = self.losses = 0
        self.lord_down = self.done = False
        self.log, self.dead_units, self.summary = [], [], None


def _cheb(a, b) -> int:
    """Chebyshev distance between two (col,row) pairs."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class GameCore:
    """Economy, inventory, world and raid rules."""

    def __init__(self, db: Database, rng=None):
        """Create the core; makes a campaign if none exists."""
        self.db = db
        self.rng = rng or random.Random()
        taken = {r[0] for r in db.conn.execute("SELECT name FROM units")}
        taken |= {r[0] for r in db.conn.execute("SELECT name FROM enemies")}
        self.names = NameGenerator(self.rng, taken)
        self.book = DialogueBook(self.rng)
        self.nem = Nemesis(db, self.rng, self.names, self.book)
        if self.active_campaign() is None:
            self.new_campaign()

    # ---- units
    def owned_count(self) -> int:
        """Return the number of ready units."""
        return self.db.conn.execute("SELECT COUNT(*) FROM units WHERE status='ready'").fetchone()[0]

    def _add_unit(self, name, cls, level, origin, legendary=0) -> dict:
        """Insert a unit, enforcing the owned cap."""
        if self.owned_count() >= MAX_OWNED_UNITS:
            raise GameError("Army is full (%d/%d)" % (MAX_OWNED_UNITS, MAX_OWNED_UNITS))
        self.names.reserve(name)
        cur = self.db.conn.execute(
            "INSERT INTO units(name,class,level,legendary,origin,status,kills,created_at) VALUES(?,?,?,?,?,'ready',0,?)",
            (name, cls, level, legendary, origin, now()))
        return self.unit(cur.lastrowid)

    def unit(self, uid) -> dict:
        """Return one unit dict."""
        r = self.db.conn.execute("SELECT * FROM units WHERE id=?", (uid,)).fetchone()
        if r is None:
            raise GameError("unknown unit")
        return dict(r)

    def buy_unit(self, cls: str) -> dict:
        """Buy a level-1 unit."""
        if cls not in PRICES:
            raise GameError("unknown class")
        with self.db.tx():
            if self.owned_count() >= MAX_OWNED_UNITS:
                raise GameError("Army is full (%d/%d)" % (MAX_OWNED_UNITS, MAX_OWNED_UNITS))
            if not self.db.spend(PRICES[cls]):
                raise GameError("Not enough tokens")
            u = self._add_unit(self.names.unit_name(), cls, 1, "bought")
            self.db.log("recruit", None, u["id"], None, "bought " + u["name"])
        return u

    def upgrade_unit(self, uid: int) -> dict:
        """Raise a unit one level (1-3)."""
        with self.db.tx() as c:
            u = self.unit(uid)
            if u["status"] != "ready" or u["legendary"] or u["level"] >= 3:
                raise GameError("This unit cannot be upgraded")
            if not self.db.spend(UPGRADE_COST[u["level"]]):
                raise GameError("Not enough tokens")
            c.execute("UPDATE units SET level=level+1 WHERE id=?", (uid,))
            self.db.log("upgrade", None, uid, None, "to level %d" % (u["level"] + 1))
        return self.unit(uid)

    def make_legendary_tokens(self, uid: int) -> dict:
        """Make a unit Legendary for LEGENDARY_COST tokens."""
        with self.db.tx() as c:
            u = self.unit(uid)
            if u["status"] != "ready" or u["legendary"]:
                raise GameError("This unit cannot become Legendary")
            if not self.db.spend(LEGENDARY_COST):
                raise GameError("Not enough tokens")
            c.execute("UPDATE units SET legendary=1 WHERE id=?", (uid,))
            self.db.log("legendary", None, uid, None, "paid tokens")
        return self.unit(uid)

    def make_legendary_sacrifice(self, uid: int, sacrifice_ids) -> dict:
        """Make a unit Legendary by sacrificing exactly 100 other non-legendary ready units."""
        ids = list(dict.fromkeys(sacrifice_ids))
        if len(ids) != LEGENDARY_SACRIFICE or uid in ids:
            raise GameError("Choose exactly %d other units" % LEGENDARY_SACRIFICE)
        with self.db.tx() as c:
            u = self.unit(uid)
            if u["status"] != "ready" or u["legendary"]:
                raise GameError("This unit cannot become Legendary")
            q = ",".join("?" for _ in ids)
            n = c.execute("SELECT COUNT(*) FROM units WHERE id IN (%s) AND status='ready' AND legendary=0" % q, ids).fetchone()[0]
            if n != len(ids):
                raise GameError("Sacrifices must be ready, non-legendary units")
            c.execute("UPDATE units SET status='sacrificed' WHERE id IN (%s)" % q, ids)
            c.execute("UPDATE units SET legendary=1 WHERE id=?", (uid,))
            self.db.log("legendary", None, uid, None, "sacrificed %d units" % len(ids))
        return self.unit(uid)

    def _filter(self, cls, level, status):
        """Build the WHERE clause for inventory filters."""
        w, a = [], []
        if cls:
            w.append("u.class=?")
            a.append(cls)
        if level:
            if int(level) == LEGENDARY_LEVEL:
                w.append("u.legendary=1")
            else:
                w.append("u.level=? AND u.legendary=0")
                a.append(int(level))
        if status:
            w.append("u.status=?")
            a.append(status)
        return (" WHERE " + " AND ".join(w)) if w else "", a

    def count_units(self, cls=None, level=None, status=None) -> int:
        """Count units matching filters."""
        w, a = self._filter(cls, level, status)
        return self.db.conn.execute("SELECT COUNT(*) FROM units u" + w, a).fetchone()[0]

    def list_units(self, cls=None, level=None, status=None, offset=0, limit=100) -> list:
        """Return one page of units (with any remembered enemy title)."""
        w, a = self._filter(cls, level, status)
        q = ("SELECT u.*, (SELECT e.title FROM enemies e WHERE e.name=u.name AND e.status='defected' LIMIT 1) AS title "
             "FROM units u" + w + " ORDER BY u.legendary DESC,u.level DESC,u.kills DESC,u.id LIMIT ? OFFSET ?")
        return [dict(r) for r in self.db.conn.execute(q, a + [limit, offset])]

    # ---- world
    def active_campaign(self):
        """Return the active campaign row (or None)."""
        r = self.db.conn.execute("SELECT * FROM campaign WHERE status IN ('active','won') ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def new_campaign(self, keep_units=True) -> int:
        """Regenerate regions and enemies; units and tokens are kept."""
        with self.db.tx() as c:
            c.execute("UPDATE enemies SET fortress_id=NULL WHERE status='defected'")
            c.execute("DELETE FROM enemies WHERE status!='defected'")
            c.execute("DELETE FROM fortresses")
            c.execute("DELETE FROM regions")
            c.execute("UPDATE campaign SET status='replaced' WHERE status IN ('active','won')")
            seed = self.rng.randrange(2 ** 31)
            cid = c.execute("INSERT INTO campaign(seed,created_at,status) VALUES(?,?,'active')", (seed, now())).lastrowid
            used = set()
            for gy in range(WORLD_H):
                for gx in range(WORLD_W):
                    nm = self.names.region_name(used)
                    used.add(nm)
                    rid = c.execute("INSERT INTO regions(campaign_id,name,gx,gy,state) VALUES(?,?,?,?,'hidden')",
                                    (cid, nm, gx, gy)).lastrowid
                    fid = c.execute("INSERT INTO fortresses(region_id,name) VALUES(?,?)",
                                    (rid, self.names.fortress_name(nm))).lastrowid
                    c.execute("UPDATE regions SET fortress_id=? WHERE id=?", (fid, rid))
                    self.nem.generate_fortress(fid)
            border = [r[0] for r in c.execute(
                "SELECT id FROM regions WHERE campaign_id=? AND (gx IN (0,?) OR gy IN (0,?))",
                (cid, WORLD_W - 1, WORLD_H - 1))]
            c.execute("UPDATE regions SET state='hostile' WHERE id=?", (self.rng.choice(border),))
            self.db.log("campaign", None, None, None, "new campaign %d" % cid)
        return cid

    def world(self) -> list:
        """Return all regions of the active campaign."""
        cp = self.active_campaign()
        if cp is None:
            return []
        return [dict(r) for r in self.db.conn.execute(
            "SELECT r.*,f.name AS fname,f.raids AS raids,f.conquered AS conquered FROM regions r "
            "LEFT JOIN fortresses f ON f.id=r.fortress_id WHERE r.campaign_id=? ORDER BY r.gy,r.gx", (cp["id"],))]

    def campaign_won(self) -> bool:
        """Return True if every region is conquered."""
        w = self.world()
        return bool(w) and all(r["state"] == "conquered" for r in w)

    # ---- raid
    def start_raid(self, region_id: int) -> RaidState:
        """Begin a raid on a hostile region."""
        r = self.db.conn.execute("SELECT * FROM regions WHERE id=?", (region_id,)).fetchone()
        if r is None or r["state"] != "hostile":
            raise GameError("That region cannot be raided")
        raid = RaidState(dict(r), r["fortress_id"])
        mem = self.nem.members(r["fortress_id"])
        lords = [m for m in mem if m["rank"] == "lord"]
        caps = [m for m in mem if m["rank"] == "captain"]
        goons = [m for m in mem if m["rank"] == "goon"]
        if not lords:
            raise GameError("This fortress has no Lord")
        allc = [(c, rr) for c in range(8, FIELD_COLS) for rr in range(FIELD_ROWS)]
        lp = (FIELD_COLS - 1, self.rng.randint(2, 5))
        cc = [p for p in allc if p[0] in (9, 10)]
        self.rng.shuffle(cc)
        caps_pos = cc[:len(caps)]
        left = [p for p in allc if p != lp and p not in caps_pos]
        front = [p for p in left if p[0] == 8]
        rest = [p for p in left if p[0] != 8]
        self.rng.shuffle(front)
        self.rng.shuffle(rest)
        order = front + rest
        for e, p in zip(lords, [lp]):
            e["col"], e["row"] = p
        for e, p in zip(caps, caps_pos):
            e["col"], e["row"] = p
        for e, p in zip(goons, order):
            e["col"], e["row"] = p
        for e in lords + caps + goons:
            if "col" in e:
                raid.enemies[e["id"]] = e
        raid.log.append("Raid on %s begins." % r["name"])
        return raid

    def occupied(self, raid, col, row):
        """Return ('unit'|'enemy', id) occupying a cell, or None."""
        for uid, u in raid.units.items():
            if not u["spent"] and (u["col"], u["row"]) == (col, row):
                return ("unit", uid)
        for eid, e in raid.enemies.items():
            if (e["col"], e["row"]) == (col, row):
                return ("enemy", eid)
        return None

    def refresh_enemy(self, raid, eid) -> None:
        """Reload an enemy from the database keeping its position."""
        old = raid.enemies.get(eid)
        if old is None:
            return
        e = self.nem.get(eid)
        e["col"], e["row"] = old["col"], old["row"]
        raid.enemies[eid] = e

    def scout(self, raid) -> list:
        """Spend SCOUT_COST to raise Intel on the Lord and one random Captain."""
        if raid.phase != "scout":
            raise GameError("Scouting is only possible before deployment")
        lord = [e for e in raid.enemies.values() if e["rank"] == "lord"]
        caps = [e for e in raid.enemies.values() if e["rank"] == "captain"]
        with self.db.tx():
            if not self.db.spend(SCOUT_COST):
                raise GameError("Not enough tokens")
            ids = [e["id"] for e in lord] + ([self.rng.choice(caps)["id"]] if caps else [])
            for i in ids:
                self.nem.raise_intel(i, 1)
            self.db.log("scout", None, None, raid.fid, "scouted %s" % ids)
        for i in ids:
            self.refresh_enemy(raid, i)
        raid.log.append("Scouts report back.")
        return ids

    def to_deploy(self, raid) -> None:
        """Move from scouting to deployment."""
        if raid.phase in ("scout", "deploy"):
            raid.phase = "deploy"

    def deploy(self, raid, uid: int, col: int, row: int) -> bool:
        """Place a ready unit in columns 0-2."""
        if raid.phase not in ("scout", "deploy"):
            raise GameError("Deployment is closed")
        raid.phase = "deploy"
        if not (0 <= col <= 2 and 0 <= row < FIELD_ROWS):
            raise GameError("Deploy only in columns 1-3")
        if uid in raid.units:
            raise GameError("Unit already deployed")
        if len(raid.units) >= MAX_DEPLOY:
            raise GameError("At most %d units" % MAX_DEPLOY)
        u = self.unit(uid)
        if u["status"] != "ready":
            raise GameError("Unit is not ready")
        if self.occupied(raid, col, row):
            raise GameError("Cell is occupied")
        u.update(col=col, row=row, moved=False, attacked=False, spent=False)
        raid.units[uid] = u
        return True

    def undeploy(self, raid, uid: int) -> None:
        """Remove a unit from the field during deployment."""
        if raid.phase == "deploy":
            raid.units.pop(uid, None)

    def start_battle(self, raid) -> None:
        """Begin the battle phase."""
        if not raid.units:
            raise GameError("Deploy at least one unit")
        raid.phase, raid.round = "battle", 1
        raid.log.append("Battle begins.")

    def move(self, raid, uid: int, col: int, row: int) -> bool:
        """Move a unit (once per round, before attacking)."""
        u = raid.units.get(uid)
        if raid.phase != "battle" or u is None or u["spent"]:
            raise GameError("Unit cannot move")
        if u["moved"] or u["attacked"] or raid.pending:
            raise GameError("Unit already acted")
        if not (0 <= col < FIELD_COLS and 0 <= row < FIELD_ROWS) or self.occupied(raid, col, row):
            raise GameError("Invalid destination")
        if _cheb((u["col"], u["row"]), (col, row)) > ROLES[u["class"]]["move"]:
            raise GameError("Too far")
        u["col"], u["row"], u["moved"] = col, row, True
        return True

    def win_chance_for(self, u: dict, e: dict) -> int:
        """Return the win percentage of unit u against enemy e."""
        base = win_chance(effective_level(u["level"], u["legendary"]))
        return max(0, min(100, base + trait_modifier(e["traits"], u["class"])))

    def attack(self, raid, uid: int, eid: int, rolls=None) -> dict:
        """Resolve one attack; rolls=(attack_roll, survive_roll) may be forced for tests."""
        u = raid.units.get(uid)
        if u is None or raid.phase != "battle":
            raise GameError("Only deployed units can attack during battle")
        e = raid.enemies.get(eid)
        if u["spent"] or u["attacked"] or raid.pending or e is None:
            raise GameError("Attack not possible")
        if _cheb((u["col"], u["row"]), (e["col"], e["row"])) > ROLES[u["class"]]["rng"]:
            raise GameError("Target out of range")
        eff = effective_level(u["level"], u["legendary"])
        chance = self.win_chance_for(u, e)
        roll = rolls[0] if rolls else self.rng.randint(1, 100)
        win = roll <= chance
        d = {"unit_id": uid, "enemy_id": eid, "chance": chance, "roll": roll, "win": win, "survive_chance": None,
             "survive_roll": None, "survived": None, "pre": self.nem.dialogue_for(eid, "pre_fight", u), "line": ""}
        with self.db.tx() as c:
            u["attacked"] = True
            self.nem.raise_intel(eid, 1 + ROLES[u["class"]]["intel"])
            if win:
                c.execute("UPDATE units SET kills=kills+1 WHERE id=?", (uid,))
                self.nem.record_duel(eid, uid, False)
                raid.pending = d
                d["line"] = self.nem.dialogue_for(eid, "defeat_line", u)
            else:
                sc = survive_chance(eff)
                sr = rolls[1] if rolls and len(rolls) > 1 else self.rng.randint(1, 100)
                survived = bool(u["legendary"]) or sr <= sc
                d.update(survive_chance=sc, survive_roll=sr, survived=survived)
                u["spent"] = True
                raid.losses += 1
                if not survived:
                    c.execute("UPDATE units SET status='dead' WHERE id=?", (uid,))
                    raid.dead_units.append(u["name"])
                self.nem.record_duel(eid, uid, True)
                d["line"] = self.nem.dialogue_for(eid, "victory_taunt", u)
            self.db.log("duel", eid, uid, raid.fid, "win" if win else ("loss/survived" if d["survived"] else "loss/died"))
        self.refresh_enemy(raid, eid)
        raid.log.append(("%s defeats %s" if win else "%s falls to %s") % (u["name"], e["name"]))
        return d

    def resolve_win(self, raid, choice: str, step_in: bool = False) -> dict:
        """After a win: 'turn' recruits the enemy, 'kill' removes it (optionally stepping in)."""
        d = raid.pending
        if d is None:
            raise GameError("No pending victory")
        if choice not in ("turn", "kill"):
            raise GameError("Choose turn or kill")
        e = raid.enemies[d["enemy_id"]]
        u = raid.units[d["unit_id"]]
        line = ""
        with self.db.tx() as c:
            if choice == "turn":
                if self.owned_count() >= MAX_OWNED_UNITS:
                    raise GameError("Army is full; kill the enemy instead")
                cls = self.rng.choice(sorted(ROLES))
                c.execute("UPDATE enemies SET status='defected' WHERE id=?", (e["id"],))
                self._add_unit(e["name"], cls, max(1, min(3, e["level"])), "defected")
                line = self.nem.dialogue_for(e["id"], "recruit_line", {"name": e["name"], "class": cls})
                raid.turned += 1
            else:
                c.execute("UPDATE enemies SET status='dead' WHERE id=?", (e["id"],))
                raid.kills += 1
            bounty = BOUNTY[e["rank"]] * (RIVAL_MULT if e["rival"] else 1)
            self.db.add_tokens(bounty)
            raid.bounty += bounty
            self.db.log("turn" if choice == "turn" else "kill", e["id"], u["id"], raid.fid, "bounty %d" % bounty)
            if e["rank"] == "lord":
                raid.lord_down = True
        pos = (e["col"], e["row"])
        del raid.enemies[e["id"]]
        if step_in and choice == "kill":
            u["col"], u["row"] = pos
        raid.pending = None
        raid.log.append("%s %s. +%d tokens" % (e["name"], "turned" if choice == "turn" else "slain", bounty))
        return {"bounty": bounty, "line": line, "enemy": e}

    def active_units(self, raid) -> list:
        """Return deployed units still on the field."""
        return [u for u in raid.units.values() if not u["spent"]]

    def raid_over(self, raid) -> bool:
        """Return True if the Lord fell or no unit remains on the field."""
        return raid.lord_down or (raid.phase == "battle" and not self.active_units(raid) and not raid.pending)

    def next_round(self, raid) -> bool:
        """Advance a round; False when MAX_ROUNDS has been reached."""
        if raid.pending:
            raise GameError("Resolve the victory first")
        if raid.round >= MAX_ROUNDS:
            return False
        raid.round += 1
        for u in raid.units.values():
            u["moved"] = u["attacked"] = False
        return True

    def end_raid(self, raid) -> dict:
        """Finish a raid: persist fortress change, promotions, conquest and exiles."""
        if raid.done:
            return raid.summary
        raid.done, raid.phase = True, "done"
        events = []
        with self.db.tx() as c:
            c.execute("UPDATE fortresses SET raids=raids+1 WHERE id=?", (raid.fid,))
            self.db.log("raid_end", None, None, raid.fid, "lord down" if raid.lord_down else "retreat")
            if raid.lord_down:
                reg = raid.region
                c.execute("UPDATE regions SET state='conquered' WHERE id=?", (reg["id"],))
                c.execute("UPDATE fortresses SET conquered=1 WHERE id=?", (raid.fid,))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    c.execute("UPDATE regions SET state='hostile' WHERE campaign_id=? AND gx=? AND gy=? AND state='hidden'",
                              (reg["campaign_id"], reg["gx"] + dx, reg["gy"] + dy))
                events.append("%s has fallen!" % reg["name"])
                events.extend(self.nem.exile_captains(raid.fid))
                if self.campaign_won():
                    c.execute("UPDATE campaign SET status='won' WHERE id=?", (reg["campaign_id"],))
                    events.append("Every region is conquered. The realm is yours!")
            else:
                events.extend(self.nem.run_promotions(raid.fid))
            self.nem.flag_rivals()
        self.db.backup()
        raid.summary = {"bounty": raid.bounty, "kills": raid.kills, "turned": raid.turned, "losses": raid.losses,
                        "dead": list(raid.dead_units), "lord_down": raid.lord_down, "events": events,
                        "won": raid.lord_down and self.campaign_won() or False}
        return raid.summary


# ----------------------------------------------------------------------------- selftest
def run_all(seed: int = 1234) -> bool:
    """Run all headless checks and print PASS/FAIL per check."""
    results = []

    def check(name, fn):
        """Run one check function and print its result."""
        try:
            ok = bool(fn())
            err = ""
        except Exception as exc:
            ok, err = False, " (%s: %s)" % (type(exc).__name__, exc)
        results.append(ok)
        print("%s - %s%s" % ("PASS" if ok else "FAIL", name, err))

    tmp = tempfile.mkdtemp(prefix="ftl_test_")
    try:
        def fresh(name):
            """Create a fresh database and core."""
            db = Database(os.path.join(tmp, name + ".sqlite3"))
            return db, GameCore(db, random.Random(seed))

        db, core = fresh("main")
        db.add_tokens(5000)

        check("win chance levels 1-4 = 25/50/75/100",
              lambda: [win_chance(effective_level(l, 0)) for l in (1, 2, 3)] + [win_chance(effective_level(1, 1))] == [25, 50, 75, 100])

        def fort():
            """Check the fortress composition."""
            fid = core.world()[0]["fortress_id"]
            m = core.nem.members(fid)
            lords = [e for e in m if e["rank"] == "lord"]
            caps = [e for e in m if e["rank"] == "captain"]
            goons = [e for e in m if e["rank"] == "goon"]
            return (len(lords) == 1 and lords[0]["level"] == 3 and len(caps) == 6 and len(goons) == 20
                    and all(1 <= e["level"] <= 3 for e in caps + goons))
        check("fortress = 1 Lord(L3) + 6 Captains + 20 Goons, levels 1-3", fort)

        def cap():
            """Check the owned cap."""
            d2, c2 = fresh("cap")
            d2.add_tokens(100)
            with d2.tx() as c:
                c.executemany("INSERT INTO units(name,class,level,created_at) VALUES(?,?,?,?)",
                              [("Cap%d" % i, "archer", 1, now()) for i in range(MAX_OWNED_UNITS)])
            try:
                c2.buy_unit("archer")
                return False
            except GameError:
                return c2.owned_count() == MAX_OWNED_UNITS
        check("3000 owned cap enforced", cap)

        def leg():
            """Check both Legendary paths."""
            a = core.buy_unit("archer")
            core.make_legendary_tokens(a["id"])
            ok1 = core.unit(a["id"])["legendary"] == 1
            b = core.buy_unit("wizard")
            with db.tx() as c:
                ids = [c.execute("INSERT INTO units(name,class,level,created_at) VALUES(?,?,?,?)",
                                 ("Fodder%d" % i, "rogue", 1, now())).lastrowid for i in range(100)]
            core.make_legendary_sacrifice(b["id"], ids)
            ok2 = core.unit(b["id"])["legendary"] == 1 and core.unit(ids[0])["status"] == "sacrificed"
            return ok1 and ok2
        check("both Legendary paths work", leg)

        cw = core.world()
        reg = next(r for r in cw if r["state"] == "hostile")
        raid = core.start_raid(reg["id"])
        core.to_deploy(raid)
        legu = core.list_units(level=4)[0]
        core.deploy(raid, legu["id"], 0, 0)
        core.start_battle(raid)
        target = next(iter(raid.enemies.values()))
        raid.units[legu["id"]].update(col=target["col"] - 1, row=target["row"])

        def legret():
            """Check a defeated Legendary returns."""
            d = core.attack(raid, legu["id"], target["id"], rolls=(101, 100))
            u = core.unit(legu["id"])
            return (not d["win"]) and d["survived"] and u["status"] == "ready" and u["legendary"] == 1
        check("defeated Legendary returns to inventory", legret)

        def undeployed():
            """Check undeployed attackers are rejected."""
            other = core.buy_unit("archer")
            try:
                core.attack(raid, other["id"], target["id"])
                return False
            except GameError:
                return True
        check("attacking with an undeployed unit is rejected", undeployed)

        def names():
            """Check name uniqueness."""
            g = NameGenerator(random.Random(5), set())
            n = [g.unit_name() for _ in range(3000)]
            return len(set(n)) == 3000 and g.capacity() >= 50000
        check("3000 generated names are unique", names)

        def award():
            """Check task idempotency."""
            d2, _ = fresh("award")
            a = d2.award_task("1:2026-01-01")
            b = d2.award_task("1:2026-01-01")
            return a and not b and d2.secret_total() == 1 and d2.balance()["balance"] == 1 and d2.balance()["total_earned"] == 1
        check("same task_key twice gives +1 only", award)

        def hidden():
            """Check the secret key never leaks."""
            if db.get_config(SECRET_KEY) is None:
                return False
            for ds in DATASETS:
                cols, rows = viewer_rows(db, ds)
                if any("_secret_" in str(x) for r in rows for x in r):
                    return False
                p = os.path.join(tmp, ds + ".csv")
                export_csv(db, ds, p)
                with open(p, encoding="utf-8") as f:
                    if "_secret_" in f.read():
                        return False
            return True
        check("hidden config key absent from viewer and CSV", hidden)

        def persist():
            """Check promotion, titles and rivals survive reopening."""
            d2, c2 = fresh("persist")
            rg = next(r for r in c2.world() if r["state"] == "hostile")
            fid = rg["fortress_id"]
            mem = c2.nem.members(fid)
            cap = next(m for m in mem if m["rank"] == "captain")
            goon = next(m for m in mem if m["rank"] == "goon")
            d2.conn.execute("UPDATE enemies SET victories=5 WHERE id=?", (goon["id"],))
            d2.conn.execute("UPDATE enemies SET status='dead' WHERE id=?", (cap["id"],))
            c2.nem.run_promotions(fid)
            for i in range(2):
                uu = c2._add_unit("Victim%d" % i, "archer", 1, "bought")
                c2.nem.record_duel(cap["id"] if False else goon["id"], uu["id"], True)
            c2.nem.run_promotions(fid)
            path = d2.path
            d2.close()
            d3 = Database(path)
            e = Nemesis(d3, random.Random(1), NameGenerator(random.Random(1)), DialogueBook(random.Random(1))).get(goon["id"])
            caps = [m for m in Nemesis(d3, random.Random(1), NameGenerator(random.Random(1)), DialogueBook(random.Random(1))).members(fid)
                    if m["rank"] == "captain"]
            ok = (e["rank"] == "captain" and e["title"].startswith("Slayer of Victim") and e["rival"] == 1
                  and len(caps) == 6 and e["victories"] >= 7)
            d3.close()
            return ok
        check("promotion, titles and Rival flags survive reopening", persist)

        def dlg():
            """Check 40 draws never repeat."""
            b = DialogueBook(random.Random(seed))
            sits = list(TEMPLATES)
            out = [b.line(sits[i % len(sits)], TRAITS, enemy="E", unit="U", victim="V", title="T") for i in range(40)]
            return len(set(out)) == 40 and b.template_count() >= 40
        check("40 dialogue draws produce no repeats", dlg)
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if all(results) else "SOME CHECKS FAILED")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
