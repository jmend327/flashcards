"""flashcards.py — Single-file Tkinter flashcard application.

Architecture — three layers, each with one responsibility:

    ┌──────────────────────────────────────────────────────────┐
    │  TkView  (View layer)                                    │
    │  • Builds and updates Tkinter widgets                    │
    │  • Translates user events into controller calls          │
    │  • Manages navigation (which screen is visible)          │
    │  • Contains ZERO business rules                          │
    └──────────────────────────────┬───────────────────────────┘
                                   │ calls
    ┌──────────────────────────────▼───────────────────────────┐
    │  AppController  (Controller layer)                       │
    │  • Validates user input                                  │
    │  • Owns study-session state (index, flip, scored)        │
    │  • Converts storage tuples → clean dicts for the view    │
    │  • Returns plain Python values — never tkinter objects   │
    │  • Never imports tkinter                                 │
    └──────────────────────────────┬───────────────────────────┘
                                   │ calls
    ┌──────────────────────────────▼───────────────────────────┐
    │  DeckStorage / ScoreStore  (Storage layer)               │
    │  • Reads and writes JSON files                           │
    │  • No business logic, no GUI knowledge                   │
    └──────────────────────────────────────────────────────────┘

Swapping the GUI (e.g. replacing Tkinter with a browser frontend):
  1. Keep DeckStorage, ScoreStore, and AppController exactly as-is.
  2. Write a new view class that calls the same AppController methods.
  3. The controller API (method names and return shapes) is the stable
     contract between the frontend and the rest of the app.
"""

import tkinter as tk
from tkinter import messagebox, simpledialog
import json
import os
import re
import random


# ── Directory layout ──────────────────────────────────────────────────────────
# All paths are relative to the directory that contains this script.
# Using relative paths means the whole project folder can be moved or copied
# without breaking stored scores or breaking deck lookups.

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR  = os.path.join(BASE_DIR, "public_flashcards")   # bundled example decks
PRIVATE_DIR = os.path.join(BASE_DIR, "private_flashcards")  # user decks (gitignored)
LOCAL_DIR   = os.path.join(BASE_DIR, ".local")              # runtime state (gitignored)
SCORES_PATH = os.path.join(LOCAL_DIR, "scores.json")


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE LAYER
# ══════════════════════════════════════════════════════════════════════════════

class ScoreStore:
    """Persists per-card correct/incorrect counts in .local/scores.json.

    Scores are intentionally kept separate from deck content so that:
      - Deck JSON files stay clean and shareable without personal stats baked in.
      - Scores survive deck renames (keys use relative forward-slash paths so
        the project folder can be moved without breaking anything).

    Internal JSON format:
        {
          "rel/path.json": {
            "card_local_id": [correct_count, incorrect_count]
          }
        }
    """

    def __init__(self, base_dir=BASE_DIR):
        # Derive the local-state directory and scores file path from base_dir
        # rather than from module-level constants, so that tests can pass a
        # temporary directory and never touch the real scores file.
        self._base_dir    = base_dir
        local_dir         = os.path.join(base_dir, ".local")
        self._scores_path = os.path.join(local_dir, "scores.json")

        os.makedirs(local_dir, exist_ok=True)
        self._data = {}
        if os.path.exists(self._scores_path):
            try:
                with open(self._scores_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (OSError, json.JSONDecodeError):
                # OSError:          file disappeared between the exists() check
                #                   and the open(), or permissions changed.
                # JSONDecodeError:  file exists but its contents are corrupt.
                # Either way, start with an empty store rather than crashing.
                pass

    def _rel(self, abs_path):
        """Convert an absolute deck path to a portable relative key.

        Forward slashes are used regardless of OS so the scores file can be
        shared across Windows/macOS/Linux without key mismatches.
        """
        return os.path.relpath(abs_path, self._base_dir).replace(os.sep, "/")

    def _flush(self):
        """Write the in-memory data dict to disk immediately."""
        with open(self._scores_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, deck_path, local_id):
        """Return (correct, incorrect) counts for a single card.

        Returns (0, 0) if the card has never been attempted.
        """
        pair = self._data.get(self._rel(deck_path), {}).get(str(local_id), [0, 0])
        return pair[0], pair[1]

    def record_correct(self, deck_path, local_id):
        """Increment the correct counter for a card and flush to disk."""
        rel = self._rel(deck_path)
        self._data.setdefault(rel, {}).setdefault(str(local_id), [0, 0])
        self._data[rel][str(local_id)][0] += 1
        self._flush()

    def record_incorrect(self, deck_path, local_id):
        """Increment the incorrect counter for a card and flush to disk."""
        rel = self._rel(deck_path)
        self._data.setdefault(rel, {}).setdefault(str(local_id), [0, 0])
        self._data[rel][str(local_id)][1] += 1
        self._flush()


class DeckStorage:
    """File-based storage layer.  Each deck is a .json file in either
    public_flashcards/ or private_flashcards/.

    Cards are returned as fixed-length tuples (indexed by the C_* constants
    defined below).  Callers identify cards using opaque session IDs — integers
    assigned at runtime — rather than raw file paths + per-deck local IDs.
    This keeps higher layers unaware of the on-disk representation.
    """

    def __init__(self, base_dir=BASE_DIR):
        # Derive all directory paths from base_dir so tests can point the
        # entire storage layer at a temporary directory without touching
        # the real deck files or scores.
        self._base_dir    = base_dir
        self._public_dir  = os.path.join(base_dir, "public_flashcards")
        self._private_dir = os.path.join(base_dir, "private_flashcards")

        os.makedirs(self._public_dir,  exist_ok=True)
        os.makedirs(self._private_dir, exist_ok=True)

        self.scores = ScoreStore(base_dir=base_dir)

        # Session-ID registry — maps a runtime integer to a (deck_path, local_id)
        # pair.  Session IDs are not persisted; they reset each run.  They exist
        # so higher layers can refer to cards without knowing file paths or
        # per-deck ID counters.
        self._registry = {}   # session_id → (deck_path, local_card_id)
        self._reverse  = {}   # (deck_path, local_card_id) → session_id
        self._next_sid = 1

        # Bootstrap example data on startup.
        self._seed_public_decks()

    # ── File helpers ──────────────────────────────────────────────────────────

    def _load(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _safe_name(self, name):
        """Strip characters that are illegal in filenames on common platforms."""
        return re.sub(r'[<>:"/\\|?*]', "", name).strip() or "deck"

    def _new_path(self, folder, name):
        """Return a non-conflicting file path for a new deck in folder."""
        base = self._safe_name(name)
        path = os.path.join(folder, base + ".json")
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{base}_{n}.json")
            n += 1
        return path

    # ── Session-ID registry ───────────────────────────────────────────────────

    def _get_sid(self, deck_path, local_id):
        """Return the session ID for a (deck_path, local_id) pair.

        Allocates a new ID on first access and caches it for subsequent calls.
        """
        key = (deck_path, local_id)
        if key not in self._reverse:
            sid = self._next_sid
            self._next_sid += 1
            self._registry[sid] = key
            self._reverse[key] = sid
        return self._reverse[key]

    def _resolve(self, session_id):
        """Look up the (deck_path, local_id) pair for a session ID."""
        return self._registry[session_id]

    # ── Public example deck seeding ───────────────────────────────────────────

    def _seed_public_decks(self):
        """Create the bundled example deck on first run if it doesn't exist yet."""
        target = os.path.join(self._public_dir, "Fun Trivia Mix.json")
        if os.path.exists(target):
            return
        cards = [
            {
                "id": 1, "front": "Which planet is closest to the Sun?",
                "back": "Mercury", "card_type": "mc",
                "choices": ["Venus", "Earth", "Mars"], "tags": [],
            },
            {
                "id": 2, "front": "What is the largest ocean on Earth?",
                "back": "Pacific Ocean", "card_type": "mc",
                "choices": ["Atlantic Ocean", "Indian Ocean", "Arctic Ocean"], "tags": [],
            },
            {
                "id": 3, "front": "How many sides does a pentagon have?",
                "back": "5", "card_type": "mc",
                "choices": ["4", "6", "8"], "tags": [],
            },
            {
                "id": 4,
                "front": "What is the most spoken language in the world by native speakers?",
                "back": "Mandarin Chinese", "card_type": "mc",
                "choices": ["English", "Spanish", "Hindi"], "tags": [],
            },
            {
                "id": 5, "front": "What is 15% of 200?",
                "back": "30", "card_type": "mc",
                "choices": ["25", "35", "45"], "tags": [],
            },
            {
                "id": 6, "front": "What year did World War II end?",
                "back": "1945", "card_type": "free", "choices": None, "tags": [],
            },
            {
                "id": 7, "front": "What gas do plants absorb during photosynthesis?",
                "back": "Carbon dioxide (CO2)", "card_type": "free", "choices": None, "tags": [],
            },
            {
                "id": 8, "front": "What is the square root of 64?",
                "back": "8", "card_type": "free", "choices": None, "tags": [],
            },
        ]
        self._save(target, {
            "name": "Fun Trivia Mix", "tags": [], "next_id": 9, "cards": cards,
        })

    # ── Folder queries ────────────────────────────────────────────────────────

    def get_decks_in_folder(self, folder):
        """Return [(deck_path, name), ...] sorted alphabetically by name."""
        if not os.path.isdir(folder):
            return []
        result = []
        for fname in os.listdir(folder):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(folder, fname)
            try:
                data = self._load(path)
                result.append((path, data.get("name", fname[:-5])))
            except (OSError, json.JSONDecodeError):
                # Skip any file that can't be read or parsed — it may be a
                # non-deck JSON file or a deck that was partially written.
                pass
        result.sort(key=lambda x: x[1].lower())
        return result

    # ── Deck CRUD ─────────────────────────────────────────────────────────────

    def create_deck(self, name, folder):
        path = self._new_path(folder, name)
        self._save(path, {"name": name, "tags": [], "next_id": 1, "cards": []})
        return path

    def rename_deck(self, deck_path, new_name):
        data = self._load(deck_path)
        data["name"] = new_name
        self._save(deck_path, data)

    def delete_deck(self, deck_path):
        if os.path.exists(deck_path):
            os.remove(deck_path)
        # Remove all session-ID registrations for cards in this deck.
        gone = [sid for sid, (p, _) in self._registry.items() if p == deck_path]
        for sid in gone:
            _, lid = self._registry.pop(sid)
            self._reverse.pop((deck_path, lid), None)

    def card_count(self, deck_path):
        try:
            return len(self._load(deck_path).get("cards", []))
        except (OSError, json.JSONDecodeError):
            return 0

    def get_deck_tags(self, deck_path):
        try:
            return self._load(deck_path).get("tags", [])
        except (OSError, json.JSONDecodeError):
            return []

    def set_deck_tags(self, deck_path, tags):
        data = self._load(deck_path)
        data["tags"] = [t.strip().lower() for t in tags if t.strip()]
        self._save(deck_path, data)

    # ── Card helpers ──────────────────────────────────────────────────────────

    def _to_tuple(self, deck_path, card):
        """Convert a card dict (loaded from JSON) to the internal tuple format.

        Choices are stored as a JSON string inside the tuple so the tuple
        stays flat and fully serialisable without nested containers.
        """
        sid              = self._get_sid(deck_path, card["id"])
        correct, incorrect = self.scores.get(deck_path, card["id"])
        choices_json     = json.dumps(card["choices"]) if card.get("choices") else None
        return (
            sid,
            card["front"],
            card["back"],
            correct,
            incorrect,
            card.get("card_type", "free"),
            choices_json,
        )

    def _find(self, data, local_id):
        """Find a card by local ID within a loaded deck dict.

        Returns (index, card_dict), or (None, None) if not found.
        """
        for i, c in enumerate(data.get("cards", [])):
            if c["id"] == local_id:
                return i, c
        return None, None

    # ── Card CRUD ─────────────────────────────────────────────────────────────

    def get_cards(self, deck_path):
        data = self._load(deck_path)
        return [self._to_tuple(deck_path, c) for c in data.get("cards", [])]

    def create_card(self, deck_path, front, back, card_type="free", choices=None):
        data     = self._load(deck_path)
        local_id = data.get("next_id", 1)
        data["cards"].append({
            "id":        local_id,
            "front":     front,
            "back":      back,
            "card_type": card_type,
            "choices":   choices,
            "tags":      [],
        })
        data["next_id"] = local_id + 1
        self._save(deck_path, data)
        return self._get_sid(deck_path, local_id)

    def update_card(self, session_id, front, back, card_type="free", choices=None):
        deck_path, local_id = self._resolve(session_id)
        data = self._load(deck_path)
        idx, card = self._find(data, local_id)
        if card is not None:
            card.update({"front": front, "back": back,
                         "card_type": card_type, "choices": choices})
            data["cards"][idx] = card
            self._save(deck_path, data)

    def get_card_by_id(self, session_id):
        try:
            deck_path, local_id = self._resolve(session_id)
            data = self._load(deck_path)
            _, card = self._find(data, local_id)
            if card:
                return self._to_tuple(deck_path, card)
        except (KeyError, OSError, json.JSONDecodeError):
            # KeyError:       session_id not in the registry (stale ID).
            # OSError:        deck file is unreadable.
            # JSONDecodeError: deck file is corrupt.
            pass
        return None

    def delete_card(self, session_id):
        deck_path, local_id = self._resolve(session_id)
        data = self._load(deck_path)
        data["cards"] = [c for c in data["cards"] if c["id"] != local_id]
        self._save(deck_path, data)
        self._reverse.pop((deck_path, local_id), None)
        self._registry.pop(session_id, None)

    def record_correct(self, session_id):
        deck_path, local_id = self._resolve(session_id)
        self.scores.record_correct(deck_path, local_id)

    def record_incorrect(self, session_id):
        deck_path, local_id = self._resolve(session_id)
        self.scores.record_incorrect(deck_path, local_id)

    # ── Card tags ─────────────────────────────────────────────────────────────

    def get_card_tags(self, session_id):
        try:
            deck_path, local_id = self._resolve(session_id)
            data = self._load(deck_path)
            _, card = self._find(data, local_id)
            return card.get("tags", []) if card else []
        except (KeyError, OSError, json.JSONDecodeError):
            return []

    def set_card_tags(self, session_id, tags):
        deck_path, local_id = self._resolve(session_id)
        data = self._load(deck_path)
        idx, card = self._find(data, local_id)
        if card is not None:
            card["tags"] = [t.strip().lower() for t in tags if t.strip()]
            data["cards"][idx] = card
            self._save(deck_path, data)

    # ── Tag queries across all decks ──────────────────────────────────────────

    def _all_deck_paths(self):
        """Return file paths for every deck in both public and private folders."""
        paths = []
        for folder in (self._public_dir, self._private_dir):
            for path, _ in self.get_decks_in_folder(folder):
                paths.append(path)
        return paths

    def get_all_tags_with_counts(self):
        """Return [(tag_name, card_count, deck_count), ...] sorted by name."""
        card_counts, deck_counts = {}, {}
        for deck_path in self._all_deck_paths():
            try:
                data = self._load(deck_path)
            except (OSError, json.JSONDecodeError):
                continue
            for t in data.get("tags", []):
                deck_counts[t] = deck_counts.get(t, 0) + 1
            for card in data.get("cards", []):
                for t in card.get("tags", []):
                    card_counts[t] = card_counts.get(t, 0) + 1
        all_tags = set(card_counts) | set(deck_counts)
        return sorted(
            [(t, card_counts.get(t, 0), deck_counts.get(t, 0)) for t in all_tags]
        )

    def get_cards_by_tag(self, tag_name):
        """Return all cards whose own card-level tags include tag_name."""
        result = []
        for deck_path in self._all_deck_paths():
            try:
                data = self._load(deck_path)
            except (OSError, json.JSONDecodeError):
                continue
            for card in data.get("cards", []):
                if tag_name in card.get("tags", []):
                    result.append(self._to_tuple(deck_path, card))
        return result

    def get_cards_by_deck_tag(self, tag_name):
        """Return all cards in decks whose deck-level tags include tag_name."""
        result = []
        for deck_path in self._all_deck_paths():
            try:
                data = self._load(deck_path)
            except (OSError, json.JSONDecodeError):
                continue
            if tag_name in data.get("tags", []):
                for card in data.get("cards", []):
                    result.append(self._to_tuple(deck_path, card))
        return result

    def close(self):
        pass  # Nothing to close for file-based storage.


# Card tuple field indices.
# Used only inside DeckStorage and AppController — the view never sees raw tuples.
C_ID, C_FRONT, C_BACK, C_CORRECT, C_INCORRECT, C_TYPE, C_CHOICES = range(7)


# ══════════════════════════════════════════════════════════════════════════════
# CONTROLLER LAYER
# ══════════════════════════════════════════════════════════════════════════════

class AppController:
    """Business-logic layer between the GUI and the storage layer.

    Responsibilities:
      - Validating user input (e.g. "MC cards need ≥ 1 wrong choice")
      - Parsing raw user strings (e.g. comma-separated tag input)
      - Owning study-session state (current index, flip state, scored flag)
      - Converting DeckStorage's internal tuple format into clean dicts that
        the view can render without understanding storage internals
      - Returning plain Python values — never tkinter objects

    The view (TkView) contains zero business rules.  Examples of things that must
    NOT appear in TkView:
      - Validation:       if len(wrong_choices) < 1 → lives in save_card()
      - Deduplication:    seen_ids = set()           → lives in build_study_cards_for_tags()
      - Shuffling:        random.shuffle(cards)       → lives in start_study()
      - Score mutations:  card["correct"] += 1        → lives in mark_correct() etc.

    To replace Tkinter with a different frontend: rewrite TkView and leave
    AppController, DeckStorage, and ScoreStore completely unchanged.
    """

    def __init__(self, base_dir=BASE_DIR):
        # Pass base_dir through to the storage layer so the whole stack can be
        # redirected to a temporary directory for testing.  Production code
        # calls AppController() with no arguments and gets the real directories.
        self._private_dir = os.path.join(base_dir, "private_flashcards")
        self._public_dir  = os.path.join(base_dir, "public_flashcards")
        self.db = DeckStorage(base_dir=base_dir)

        # ── Study session state ───────────────────────────────────────────────
        # These fields live here (not in the GUI) so any future frontend can
        # reuse the same session without reimplementing its logic.

        self._study_cards          = []       # list of card dicts, in current display order
        self._study_original_cards = []       # same cards in the order they were passed in
        self._study_index          = 0        # index of the currently displayed card
        self._study_showing_front  = True     # False once the user has flipped the card
        self._study_scored         = False    # True once the user has answered this card
        self._study_title          = ""       # display title for the study session
        self._study_order          = "Random" # current sort mode

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _tuple_to_card(self, tup):
        """Convert a DeckStorage tuple to a plain dict for the view.

        The view always receives dicts, never raw tuples or C_* indices.
        The JSON-string encoding of MC choices is parsed here so the view
        always gets a plain Python list (empty list for free-response cards).
        """
        return {
            "id":        tup[C_ID],
            "front":     tup[C_FRONT],
            "back":      tup[C_BACK],
            "correct":   tup[C_CORRECT],
            "incorrect": tup[C_INCORRECT],
            "type":      tup[C_TYPE],
            # Parse the JSON-encoded choices string into a list.
            # Free-response cards have None stored; we normalise to [].
            "choices":   json.loads(tup[C_CHOICES]) if tup[C_CHOICES] else [],
        }

    # ── Home view ─────────────────────────────────────────────────────────────

    def get_home_data(self):
        """Return all data required to render the home screen.

        Returns:
            {
                "public_decks":  [{"path", "name", "card_count", "tags"}, ...],
                "private_decks": [{"path", "name", "card_count", "tags"}, ...],
            }
        """
        def _info(folder):
            return [
                {
                    "path":       path,
                    "name":       name,
                    "card_count": self.db.card_count(path),
                    "tags":       self.db.get_deck_tags(path),
                }
                for path, name in self.db.get_decks_in_folder(folder)
            ]
        return {
            "public_decks":  _info(self._public_dir),
            "private_decks": _info(self._private_dir),
        }

    def create_deck(self, name):
        """Validate and create a new private deck.

        Returns:
            (True,  deck_path)      on success
            (False, error_message)  on validation failure
        """
        name = (name or "").strip()
        if not name:
            return False, "Deck name cannot be empty."
        path = self.db.create_deck(name, self._private_dir)
        return True, path

    def rename_deck(self, deck_path, new_name):
        """Validate and rename a deck.

        Returns:
            (True,  None)           on success
            (False, error_message)  on validation failure
        """
        new_name = (new_name or "").strip()
        if not new_name:
            return False, "Name cannot be empty."
        self.db.rename_deck(deck_path, new_name)
        return True, None

    def delete_deck(self, deck_path):
        """Delete a deck (no validation required)."""
        self.db.delete_deck(deck_path)

    def get_deck_tags_str(self, deck_path):
        """Return the deck's tags as a comma-separated string for display/editing."""
        return ", ".join(self.db.get_deck_tags(deck_path))

    def set_deck_tags_from_str(self, deck_path, raw):
        """Parse a comma-separated tag string and persist it to the deck."""
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        self.db.set_deck_tags(deck_path, tags)

    # ── Tag picker view ───────────────────────────────────────────────────────

    def get_all_tags(self):
        """Return all tags with usage counts.

        Returns:
            [{"name", "card_count", "deck_count"}, ...]
        """
        return [
            {"name": name, "card_count": cc, "deck_count": dc}
            for name, cc, dc in self.db.get_all_tags_with_counts()
        ]

    def build_study_cards_for_tags(self, tag_names):
        """Collect and de-duplicate cards that match any of the given tag names.

        Checks both card-level tags and deck-level tags.  A card that matches
        multiple selected tags is included only once (de-duplicated by session ID).

        Returns:
            (cards, title)         on success  — cards is a list of card dicts
            (None,  error_message) if no cards were found for the given tags
        """
        seen_ids = set()
        cards    = []

        for tag in tag_names:
            # Cards whose own card-level tag matches.
            for tup in self.db.get_cards_by_tag(tag):
                if tup[C_ID] not in seen_ids:
                    seen_ids.add(tup[C_ID])
                    cards.append(self._tuple_to_card(tup))
            # Cards in decks whose deck-level tag matches.
            for tup in self.db.get_cards_by_deck_tag(tag):
                if tup[C_ID] not in seen_ids:
                    seen_ids.add(tup[C_ID])
                    cards.append(self._tuple_to_card(tup))

        if not cards:
            tag_list = ", ".join(f"'{t}'" for t in tag_names)
            return None, f"No cards found for tag(s) {tag_list}."

        title = (
            f"Tag: {tag_names[0]}"
            if len(tag_names) == 1
            else f"Tags: {', '.join(tag_names)}"
        )
        return cards, title

    # ── Deck view ─────────────────────────────────────────────────────────────

    def get_deck_cards(self, deck_path):
        """Return all cards in a deck as dicts with tags included.

        Returns:
            [{"id", "front", "back", "type", "choices",
              "correct", "incorrect", "tags"}, ...]
        """
        result = []
        for tup in self.db.get_cards(deck_path):
            card = self._tuple_to_card(tup)
            # Tags are stored per-card in the file but not in the tuple;
            # fetch them separately and attach them to the dict.
            card["tags"] = self.db.get_card_tags(tup[C_ID])
            result.append(card)
        return result

    def get_deck_tags(self, deck_path):
        """Return the deck-level tag list."""
        return self.db.get_deck_tags(deck_path)

    def delete_card(self, card_id):
        """Delete a card by session ID."""
        self.db.delete_card(card_id)

    # ── Card form ─────────────────────────────────────────────────────────────

    def get_card_for_editing(self, card_id):
        """Fetch a card's current data for pre-populating the edit form.

        Returns a card dict (with "tags" included), or None if not found.
        """
        tup = self.db.get_card_by_id(card_id)
        if tup is None:
            return None
        card         = self._tuple_to_card(tup)
        card["tags"] = self.db.get_card_tags(card_id)
        return card

    def save_card(self, deck_path, card_id, front, back, card_type, wrong_choices, tags_str):
        """Validate and persist a card (create or update).

        Args:
            deck_path:     Path to the deck file; only used when creating a new card.
                           Pass None when editing an existing card from the study view.
            card_id:       Existing session ID when editing; None when creating.
            front:         Question text (should already be stripped).
            back:          Answer / correct-answer text (should already be stripped).
            card_type:     "free" or "mc".
            wrong_choices: List of wrong-answer strings (MC only).
            tags_str:      Raw comma-separated tag input from the user.

        Returns:
            (True,  saved_card_id)  on success
            (False, error_message)  on validation failure
        """
        if not front or not back:
            return False, "Front and answer are required."

        if card_type == "mc":
            if not wrong_choices:
                return False, "Add at least 1 wrong choice for multiple choice."
            choices = wrong_choices
        else:
            choices = None  # Free-response cards have no choices.

        tags = [t.strip() for t in tags_str.split(",") if t.strip()]

        if card_id is not None:
            # Editing an existing card — deck_path is not needed.
            self.db.update_card(card_id, front, back, card_type, choices)
            self.db.set_card_tags(card_id, tags)
            return True, card_id
        else:
            # Creating a new card — deck_path is required.
            new_id = self.db.create_card(deck_path, front, back, card_type, choices)
            self.db.set_card_tags(new_id, tags)
            return True, new_id

    # ── Study session ─────────────────────────────────────────────────────────

    def start_study(self, cards, title):
        """Initialise a new study session.

        Saves the original card order before shuffling so "Original" order
        mode can restore it later.  After this call, get_study_state()
        reflects the shuffled deck.
        """
        # Snapshot the pre-shuffle order so it can be restored on demand.
        self._study_original_cards = list(cards)
        random.shuffle(cards)
        self._study_cards          = cards
        self._study_title          = title
        self._study_index          = 0
        self._study_showing_front  = True
        self._study_scored         = False
        self._study_order          = "Random"

    def get_study_state(self):
        """Return a snapshot of the current study session for the view to render.

        The view should call this method to get data and then render it.
        It should never read _study_* fields directly.

        Returns:
            {
                "title":         "Studying: Deck Name",
                "card":          {card dict},
                "index":         2,     # 0-based position in the shuffled list
                "total":         10,
                "showing_front": True,
                "scored":        False,
            }
        """
        return {
            "title":         self._study_title,
            "card":          self._study_cards[self._study_index],
            "index":         self._study_index,
            "total":         len(self._study_cards),
            "showing_front": self._study_showing_front,
            "scored":        self._study_scored,
            # Included so the view can initialise the Order dropdown to the
            # correct value when rebuilding the study UI (e.g. after editing
            # a card mid-session).
            "order":         self._study_order,
        }

    def flip_card(self):
        """Flip the current free-response card from front to back.

        Has no effect on MC cards (they never flip; choices are always visible).

        Returns:
            Updated study state dict if the flip happened, None if card is MC.
        """
        card = self._study_cards[self._study_index]
        if card["type"] == "mc":
            return None  # MC cards don't flip.
        if self._study_showing_front:
            self._study_showing_front = False
        return self.get_study_state()

    def submit_mc_answer(self, chosen):
        """Record the result of a multiple-choice selection.

        Args:
            chosen: The answer text the user clicked.

        Returns:
            {
                "is_correct":     True / False,
                "correct_answer": "Mercury",
                "state":          {updated study state},
            }
            Returns None if the card has already been scored (prevents double-scoring).
        """
        if self._study_scored:
            return None  # Ignore clicks after the card is already answered.

        card       = self._study_cards[self._study_index]
        is_correct = (chosen == card["back"])

        # Record to disk and bump the in-memory counter so the score label
        # updates immediately without re-loading from disk.
        if is_correct:
            self.db.record_correct(card["id"])
            card = {**card, "correct": card["correct"] + 1}
        else:
            self.db.record_incorrect(card["id"])
            card = {**card, "incorrect": card["incorrect"] + 1}

        self._study_cards[self._study_index] = card
        self._study_scored = True

        return {
            "is_correct":     is_correct,
            "correct_answer": card["back"],
            "state":          self.get_study_state(),
        }

    def mark_correct(self):
        """Record the current free-response card as correctly answered.

        Returns the updated study state for the view to render.
        """
        card = self._study_cards[self._study_index]
        self.db.record_correct(card["id"])
        self._study_cards[self._study_index] = {**card, "correct": card["correct"] + 1}
        self._study_scored = True
        return self.get_study_state()

    def mark_incorrect(self):
        """Record the current free-response card as incorrectly answered.

        Returns the updated study state for the view to render.
        """
        card = self._study_cards[self._study_index]
        self.db.record_incorrect(card["id"])
        self._study_cards[self._study_index] = {**card, "incorrect": card["incorrect"] + 1}
        self._study_scored = True
        return self.get_study_state()

    def next_card(self):
        """Advance to the next card (wraps around to the first).

        Resets flip and scored state so the new card starts fresh.
        Returns the updated study state.
        """
        self._study_index         = (self._study_index + 1) % len(self._study_cards)
        self._study_showing_front = True
        self._study_scored        = False
        return self.get_study_state()

    def prev_card(self):
        """Go back to the previous card (wraps around to the last).

        Resets flip and scored state so the card starts fresh.
        Returns the updated study state.
        """
        self._study_index         = (self._study_index - 1) % len(self._study_cards)
        self._study_showing_front = True
        self._study_scored        = False
        return self.get_study_state()

    def set_study_order(self, mode):
        """Re-sort the active study list and restart from card 0.

        Args:
            mode: one of "Random", "Original", or "Lowest-scored"

        "Original" restores the order the caller passed to start_study.
        "Random" re-shuffles in place (different shuffle from the first one).
        "Lowest-scored" puts cards with the fewest correct answers first;
            cards with no attempts are treated as score -1 so they appear first.

        Resets index, flip, and scored state.
        Returns the updated study state.
        """
        self._study_order = mode
        if mode == "Original":
            # Build a rank map from the snapshot taken at session start.
            id_rank = {c["id"]: i for i, c in enumerate(self._study_original_cards)}
            self._study_cards = sorted(self._study_cards, key=lambda c: id_rank[c["id"]])
        elif mode == "Random":
            random.shuffle(self._study_cards)
        else:  # "Lowest-scored"
            def score_key(c):
                total = c["correct"] + c["incorrect"]
                # No attempts → treat as score -1 so those cards sort first.
                return c["correct"] / total if total > 0 else -1.0
            self._study_cards = sorted(self._study_cards, key=score_key)
        self._study_index         = 0
        self._study_showing_front = True
        self._study_scored        = False
        return self.get_study_state()

    def get_study_deck_cards(self, deck_path, deck_name):
        """Build the card list for studying an entire deck.

        Returns:
            (cards, title)         on success
            (None,  error_message) if the deck is empty
        """
        tuples = self.db.get_cards(deck_path)
        if not tuples:
            return None, "This deck has no cards to study."
        cards = [self._tuple_to_card(t) for t in tuples]
        return cards, f"Studying: {deck_name}"

    def refresh_current_study_card(self):
        """Re-fetch the current study card from disk after it has been edited.

        Called after the user saves changes in the card form during a study
        session.  Resets flip/scored state so the updated card is shown fresh.

        Returns the updated study state.
        """
        card = self._study_cards[self._study_index]
        refreshed_tup = self.db.get_card_by_id(card["id"])
        if refreshed_tup:
            refreshed         = self._tuple_to_card(refreshed_tup)
            # _tuple_to_card doesn't include tags; fetch and attach them.
            refreshed["tags"] = self.db.get_card_tags(card["id"])
            self._study_cards[self._study_index] = refreshed
        # Always reset to front/unscored after an edit.
        self._study_showing_front = True
        self._study_scored        = False
        return self.get_study_state()

    def close(self):
        """Release storage resources."""
        self.db.close()


# ══════════════════════════════════════════════════════════════════════════════
# VIEW LAYER  (Tkinter GUI)
# ══════════════════════════════════════════════════════════════════════════════

class TkView:
    """Tkinter view layer.

    Responsibilities:
      - Build and update widgets in response to controller data
      - Translate user events (clicks, list selections, dialog input) into
        controller method calls
      - Manage navigation: decide which view to show next
      - Display controller results (success messages, error dialogs)

    This class must NOT contain business rules.  If you find yourself writing
    an 'if' that checks data validity (not widget state), move it to the
    controller.

    To replace Tkinter with a different GUI toolkit: rewrite this class and
    leave everything above it unchanged.  The controller's method signatures
    are the stable API boundary.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Flashcards")
        self.root.geometry("600x550")
        self.root.minsize(400, 400)

        # The controller is the only object the view talks to directly.
        # Never access self.ctrl.db from inside TkView.
        self.ctrl = AppController()

        self.container = tk.Frame(root)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.show_home()

    def _clear(self):
        """Destroy all widgets in the container, preparing for a new view."""
        for widget in self.container.winfo_children():
            widget.destroy()

    def _add_back_button(self, command):
        """Render the top-left ← navigation button.

        The command callback is provided by the caller, keeping navigation
        decisions in the view rather than hardcoded into a helper.

        Returns the top_bar Frame so callers can pack additional widgets
        (e.g. the Order dropdown in the study view) into the same row.
        """
        top_bar = tk.Frame(self.container)
        top_bar.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Button(
            top_bar,
            text="\u2190",
            font=("Arial", 14),
            command=command,
            bd=0,
            relief=tk.FLAT,
            cursor="hand2",
        ).pack(side=tk.LEFT)
        return top_bar

    # ── Home view ─────────────────────────────────────────────────────────────

    def show_home(self):
        """Render the home screen: section-grouped deck list + action buttons."""
        self._clear()

        tk.Label(
            self.container, text="Flashcards", font=("Arial", 24, "bold")
        ).pack(pady=(20, 10))

        list_frame = tk.Frame(self.container)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.deck_listbox = tk.Listbox(
            list_frame, font=("Arial", 14), yscrollcommand=scrollbar.set
        )
        self.deck_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.deck_listbox.yview)

        # deck_list_entries[i] is None for section-header rows, or a deck info
        # dict for selectable rows.  The parallel list lets _selected_deck()
        # map a listbox selection index back to structured data without
        # string-parsing the display text.
        self.deck_list_entries = []

        data = self.ctrl.get_home_data()

        def add_section(label, decks):
            """Insert a non-selectable section header followed by deck rows."""
            self.deck_listbox.insert(tk.END, f"  \u2500\u2500 {label} ")
            self.deck_list_entries.append(None)
            idx = len(self.deck_list_entries) - 1
            self.deck_listbox.itemconfigure(
                idx, fg="gray",
                selectbackground="#e8e8e8", selectforeground="gray",
            )
            for deck in decks:
                tag_str = f"  [{', '.join(deck['tags'])}]" if deck["tags"] else ""
                self.deck_listbox.insert(
                    tk.END,
                    f"    {deck['name']}  ({deck['card_count']} cards){tag_str}",
                )
                self.deck_list_entries.append(deck)

        add_section("Example Sets", data["public_decks"])
        add_section("My Sets",      data["private_decks"])

        self.deck_listbox.bind("<Double-Button-1>", lambda e: self._open_deck())

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 5))

        tk.Button(btn_frame, text="New Deck", command=self._new_deck,    width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Open",     command=self._open_deck,   width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Rename",   command=self._rename_deck, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete",   command=self._delete_deck, width=12).pack(side=tk.LEFT, padx=5)

        btn_frame2 = tk.Frame(self.container)
        btn_frame2.pack(pady=(0, 20))

        tk.Button(btn_frame2, text="Deck Tags",    command=self._edit_deck_tags,  width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame2, text="Study by Tag", command=self.show_tag_picker,  width=12).pack(side=tk.LEFT, padx=5)

    def _selected_deck(self):
        """Return the selected deck info dict, or None with a warning dialog."""
        sel = self.deck_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a deck.")
            return None
        entry = self.deck_list_entries[sel[0]]
        if entry is None:
            # User clicked a section header row, which is not a valid deck.
            messagebox.showwarning("No Selection", "Please select a deck.")
            return None
        return entry

    def _new_deck(self):
        name = simpledialog.askstring("New Deck", "Deck name:")
        if name is None:
            return  # User cancelled the dialog.
        ok, result = self.ctrl.create_deck(name)
        if not ok:
            messagebox.showwarning("Invalid Name", result)
            return
        self.show_home()

    def _rename_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        new_name = simpledialog.askstring(
            "Rename Deck", "New name:", initialvalue=deck["name"]
        )
        if new_name is None:
            return  # User cancelled.
        ok, err = self.ctrl.rename_deck(deck["path"], new_name)
        if not ok:
            messagebox.showwarning("Invalid Name", err)
            return
        self.show_home()

    def _delete_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        if messagebox.askyesno(
            "Delete Deck", f"Delete '{deck['name']}' and all its cards?"
        ):
            self.ctrl.delete_deck(deck["path"])
            self.show_home()

    def _open_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        self.show_deck(deck["path"], deck["name"])

    def _edit_deck_tags(self):
        deck = self._selected_deck()
        if not deck:
            return
        current_str = self.ctrl.get_deck_tags_str(deck["path"])
        result = simpledialog.askstring(
            "Deck Tags",
            f"Tags for '{deck['name']}' (comma-separated):",
            initialvalue=current_str,
        )
        if result is not None:
            self.ctrl.set_deck_tags_from_str(deck["path"], result)
            self.show_home()

    # ── Tag picker view ───────────────────────────────────────────────────────

    def show_tag_picker(self):
        """Render the tag list for 'Study by Tag'."""
        tag_data = self.ctrl.get_all_tags()
        if not tag_data:
            messagebox.showinfo("No Tags", "No tags have been created yet.")
            return

        self._clear()
        self._add_back_button(self.show_home)

        tk.Label(
            self.container, text="Study by Tag", font=("Arial", 20, "bold")
        ).pack(pady=(20, 10))

        tk.Label(
            self.container,
            text="Select one or more tags to study (Ctrl/Shift to multi-select):",
            font=("Arial", 11),
        ).pack()

        list_frame = tk.Frame(self.container)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._tag_listbox = tk.Listbox(
            list_frame,
            font=("Arial", 14),
            yscrollcommand=scrollbar.set,
            selectmode=tk.EXTENDED,  # Allows Ctrl/Shift multi-select.
        )
        self._tag_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._tag_listbox.yview)

        # Keep tag_data in sync with listbox rows so selections can be resolved
        # back to tag name strings without parsing the display text.
        self._tag_data = tag_data

        for tag in tag_data:
            parts = []
            if tag["card_count"]:
                parts.append(f"{tag['card_count']} cards")
            if tag["deck_count"]:
                parts.append(f"{tag['deck_count']} decks")
            info = ", ".join(parts) if parts else "unused"
            self._tag_listbox.insert(tk.END, f"{tag['name']}  ({info})")

        self._tag_listbox.bind(
            "<Double-Button-1>", lambda e: self._study_selected_tags()
        )

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        tk.Button(
            btn_frame, text="Study", command=self._study_selected_tags, width=12
        ).pack(side=tk.LEFT, padx=5)

    def _study_selected_tags(self):
        """Start a study session for whichever tag(s) are selected."""
        sel = self._tag_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a tag.")
            return

        tag_names = [self._tag_data[i]["name"] for i in sel]

        # The controller handles de-duplication, combining card-level and
        # deck-level tag matches, and building the title string.
        cards, result = self.ctrl.build_study_cards_for_tags(tag_names)

        if cards is None:
            # result is the error message when cards is None.
            messagebox.showinfo("No Cards", result)
            return

        # result is the session title when cards is not None.
        self._start_study(cards, result, self.show_tag_picker)

    # ── Deck view ─────────────────────────────────────────────────────────────

    def show_deck(self, deck_path, deck_name):
        """Render the card list for a single deck."""
        self._clear()
        self._add_back_button(self.show_home)

        tk.Label(
            self.container, text=deck_name, font=("Arial", 20, "bold")
        ).pack(pady=(20, 5))

        dtags = self.ctrl.get_deck_tags(deck_path)
        if dtags:
            tk.Label(
                self.container,
                text=f"Tags: {', '.join(dtags)}",
                font=("Arial", 10),
                fg="gray",
            ).pack()

        list_frame = tk.Frame(self.container)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.card_listbox = tk.Listbox(
            list_frame, font=("Arial", 12), yscrollcommand=scrollbar.set
        )
        self.card_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.card_listbox.yview)

        # Parallel list of card dicts — avoids re-parsing display strings
        # when the user selects a card for editing or deletion.
        self.cards = self.ctrl.get_deck_cards(deck_path)

        for card in self.cards:
            prefix    = "[MC] " if card["type"] == "mc" else ""
            tag_str   = f"  [{', '.join(card['tags'])}]" if card["tags"] else ""
            total     = card["correct"] + card["incorrect"]
            score_str = (
                f"  {card['correct']}/{total} — {round(card['correct'] / total * 100)}%"
                if total > 0 else ""
            )
            self.card_listbox.insert(
                tk.END, f"{prefix}{card['front']}{tag_str}{score_str}"
            )

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 5))

        tk.Button(
            btn_frame, text="Add Card",
            command=lambda: self.show_card_form(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="Edit",
            command=lambda: self._edit_card(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="Delete",
            command=lambda: self._delete_card(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

        btn_frame2 = tk.Frame(self.container)
        btn_frame2.pack(pady=(0, 20))

        tk.Button(
            btn_frame2, text="Study",
            command=lambda: self._study_deck(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

    def _edit_card(self, deck_path, deck_name):
        sel = self.card_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a card.")
            return
        card = self.cards[sel[0]]
        self.show_card_form(deck_path, deck_name, card=card)

    def _delete_card(self, deck_path, deck_name):
        sel = self.card_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a card.")
            return
        card = self.cards[sel[0]]
        if messagebox.askyesno("Delete Card", f"Delete this card?\n\n{card['front']}"):
            self.ctrl.delete_card(card["id"])
            self.show_deck(deck_path, deck_name)

    def _study_deck(self, deck_path, deck_name):
        cards, result = self.ctrl.get_study_deck_cards(deck_path, deck_name)
        if cards is None:
            messagebox.showinfo("No Cards", result)
            return
        self._start_study(cards, result, lambda: self.show_deck(deck_path, deck_name))

    # ── Card form view ────────────────────────────────────────────────────────

    def show_card_form(self, deck_path, deck_name, card=None, on_done=None):
        """Render the add/edit card form.

        Args:
            deck_path: Deck to add the new card to.  Pass None when editing
                       an existing card from within the study view.
            deck_name: Display name used for the default back-navigation.
                       Pass None when editing from study.
            card:      Card dict to pre-populate when editing; None when adding.
            on_done:   Callback invoked after Save or Cancel.  Overrides the
                       default navigation back to the deck view.
        """
        self._clear()
        editing = card is not None

        # Default: navigate back to the deck view after save/cancel.
        # Callers can override this (e.g. study view provides its own on_done).
        navigate_back = on_done or (lambda: self.show_deck(deck_path, deck_name))

        tk.Label(
            self.container,
            text="Edit Card" if editing else "Add Card",
            font=("Arial", 20, "bold"),
        ).pack(pady=(20, 10))

        # ── Scrollable form ───────────────────────────────────────────────────
        # The form can be taller than the window (especially with many MC
        # choices), so we wrap it in a Canvas + Scrollbar.

        canvas       = tk.Canvas(self.container)
        form_scrollbar = tk.Scrollbar(
            self.container, orient=tk.VERTICAL, command=canvas.yview
        )
        form_outer   = tk.Frame(canvas)

        form_outer.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=form_outer, anchor=tk.NW)
        canvas.configure(yscrollcommand=form_scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(40, 0), pady=10)
        form_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 40), pady=10)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        form = form_outer

        # ── Card type selector ────────────────────────────────────────────────
        tk.Label(form, text="Card Type:", font=("Arial", 12)).pack(anchor=tk.W)
        type_var   = tk.StringVar(value="free")
        type_frame = tk.Frame(form)
        type_frame.pack(anchor=tk.W, pady=(0, 10))

        tk.Radiobutton(
            type_frame, text="Free Response", variable=type_var, value="free",
            font=("Arial", 11), command=lambda: _toggle_type(),
        ).pack(side=tk.LEFT, padx=(0, 15))
        tk.Radiobutton(
            type_frame, text="Multiple Choice", variable=type_var, value="mc",
            font=("Arial", 11), command=lambda: _toggle_type(),
        ).pack(side=tk.LEFT)

        # ── Front / back text fields ──────────────────────────────────────────
        tk.Label(form, text="Front (Question):", font=("Arial", 12)).pack(anchor=tk.W)
        front_text = tk.Text(form, height=3, font=("Arial", 12), wrap=tk.WORD)
        front_text.pack(fill=tk.X, pady=(0, 10))

        # Label text changes based on card type (Answer vs Correct Answer).
        self._back_label = tk.Label(form, text="Back (Answer):", font=("Arial", 12))
        self._back_label.pack(anchor=tk.W)
        back_text = tk.Text(form, height=3, font=("Arial", 12), wrap=tk.WORD)
        back_text.pack(fill=tk.X, pady=(0, 10))

        # ── Multiple-choice wrong-choices section ─────────────────────────────
        # Hidden for Free Response, shown for MC.
        self._mc_frame   = tk.Frame(form)
        self._mc_entries = []  # One Entry widget per wrong choice.

        tk.Label(self._mc_frame, text="Wrong Choices:", font=("Arial", 12)).pack(anchor=tk.W)

        self._mc_entries_frame = tk.Frame(self._mc_frame)
        self._mc_entries_frame.pack(fill=tk.X)

        mc_btn_frame = tk.Frame(self._mc_frame)
        mc_btn_frame.pack(anchor=tk.W, pady=(5, 10))
        tk.Button(mc_btn_frame, text="+ Add Choice",   command=lambda: _add_choice_entry()).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(mc_btn_frame, text="- Remove Last",  command=lambda: _remove_choice_entry()).pack(side=tk.LEFT)

        # ── Tags ──────────────────────────────────────────────────────────────
        tk.Label(form, text="Tags (comma-separated):", font=("Arial", 12)).pack(anchor=tk.W)
        tags_entry = tk.Entry(form, font=("Arial", 12))
        tags_entry.pack(fill=tk.X, pady=(0, 10))

        # ── Wrong-choice helpers ──────────────────────────────────────────────

        def _add_choice_entry(value=""):
            """Append one wrong-choice Entry widget to the MC section."""
            entry = tk.Entry(self._mc_entries_frame, font=("Arial", 12))
            entry.pack(fill=tk.X, pady=2)
            if value:
                entry.insert(0, value)
            self._mc_entries.append(entry)

        def _remove_choice_entry():
            """Remove the last wrong-choice Entry widget."""
            if self._mc_entries:
                self._mc_entries[-1].destroy()
                self._mc_entries.pop()

        def _toggle_type():
            """Show/hide the MC section and update the back-field label."""
            if type_var.get() == "mc":
                self._back_label.config(text="Correct Answer:")
                self._mc_frame.pack(fill=tk.X, after=back_text)
                if not self._mc_entries:
                    # Default to 3 blank wrong-choice slots.
                    for _ in range(3):
                        _add_choice_entry()
            else:
                self._back_label.config(text="Back (Answer):")
                self._mc_frame.pack_forget()

        # ── Pre-populate when editing ─────────────────────────────────────────
        if editing:
            front_text.insert("1.0", card["front"])
            back_text.insert("1.0",  card["back"])
            type_var.set(card["type"])
            for wc in card["choices"]:
                _add_choice_entry(wc)
            _toggle_type()
            tags_entry.insert(0, ", ".join(card.get("tags", [])))

        # ── Save handler ──────────────────────────────────────────────────────

        def save():
            """Collect form values and delegate validation + persistence to the controller."""
            front     = front_text.get("1.0", tk.END).strip()
            back      = back_text.get("1.0",  tk.END).strip()
            card_type = type_var.get()
            wrong     = [e.get().strip() for e in self._mc_entries if e.get().strip()]
            tags_str  = tags_entry.get()
            card_id   = card["id"] if editing else None

            ok, result = self.ctrl.save_card(
                deck_path, card_id, front, back, card_type, wrong, tags_str
            )
            if not ok:
                # result is the validation error message.
                messagebox.showwarning("Missing Fields", result)
                return

            # Unbind the mousewheel before navigating away so the binding
            # doesn't leak into subsequent views.
            canvas.unbind_all("<MouseWheel>")
            navigate_back()

        # ── Buttons ───────────────────────────────────────────────────────────

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save",   command=save,  width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="Cancel",
            command=lambda: (canvas.unbind_all("<MouseWheel>"), navigate_back()),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

    # ── Study view ────────────────────────────────────────────────────────────

    def _start_study(self, cards, title, back_callback):
        """Initialise a study session and render the study view.

        Hands the card list and title to the controller (which shuffles and
        stores them), then builds the study UI.

        Args:
            cards:         List of card dicts returned by the controller.
            title:         Display title (e.g. "Studying: My Deck").
            back_callback: Called when the user presses ← to leave the session.
                           Navigation is a view concern, so it lives here rather
                           than inside the controller.
        """
        self.ctrl.start_study(cards, title)
        # The back destination is navigation state — it belongs in the view.
        self._study_back_callback = back_callback
        self._build_study_view()

    def _build_study_view(self):
        """Construct all study-view widgets from scratch.

        Called both when entering a new session (_start_study) and when
        resuming after editing a card mid-session.  Having a single method
        eliminates the duplication that previously existed between the
        _start_study and _resume_study methods.
        """
        self._clear()
        top_bar = self._add_back_button(self._study_back_callback)

        state = self.ctrl.get_study_state()

        # Order dropdown lives in the same top bar row as the back button so it
        # doesn't consume vertical space from the card area.
        self._add_order_menu(top_bar, state["order"])

        tk.Label(
            self.container, text=state["title"], font=("Arial", 16)
        ).pack(pady=(20, 5))

        # Progress counter label (e.g. "Card 3 of 10").
        self._study_counter = tk.Label(self.container, text="", font=("Arial", 11))
        self._study_counter.pack()

        # Historical score label (e.g. "Score: 7/10 (70%)").
        self._study_score_label = tk.Label(
            self.container, text="", font=("Arial", 10), fg="gray"
        )
        self._study_score_label.pack()

        # Grooved frame acts as the visual "card face".
        self._study_card_frame = tk.Frame(self.container, bd=2, relief=tk.GROOVE)
        self._study_card_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=15)

        # "FRONT" / "BACK" / "MULTIPLE CHOICE" indicator.
        self._study_side_label = tk.Label(
            self._study_card_frame, text="FRONT", font=("Arial", 10), fg="gray"
        )
        self._study_side_label.pack(pady=(10, 0))

        # Main card text.
        self._study_label = tk.Label(
            self._study_card_frame,
            text="",
            font=("Arial", 16),
            wraplength=400,
            justify=tk.CENTER,
        )
        self._study_label.pack(expand=True, padx=20, pady=(10, 5))

        # Container for MC choice buttons (empty / unused for FR cards).
        self._study_mc_frame = tk.Frame(self._study_card_frame)
        self._study_mc_frame.pack(fill=tk.X, padx=20, pady=(0, 15))
        self._mc_choice_btns = []  # Populated by _render_study_state for MC cards.

        # Feedback text shown after answering ("Correct!", "Incorrect! Answer: …").
        self._study_feedback = tk.Label(
            self._study_card_frame, text="", font=("Arial", 11)
        )
        self._study_feedback.pack(pady=(0, 10))

        # Clicking anywhere on the card face calls _on_flip_click.
        # For MC cards the controller's flip_card() returns None (no-op).
        self._study_card_frame.bind("<Button-1>", lambda e: self._on_flip_click())
        self._study_label.bind(     "<Button-1>", lambda e: self._on_flip_click())
        self._study_side_label.bind("<Button-1>", lambda e: self._on_flip_click())

        nav_frame = tk.Frame(self.container)
        nav_frame.pack(pady=(0, 5))

        self._prev_btn = tk.Button(
            nav_frame, text="Previous", command=self._on_prev, width=12
        )
        self._prev_btn.pack(side=tk.LEFT, padx=5)

        self._next_btn = tk.Button(
            nav_frame, text="Next", command=self._on_next, width=12
        )
        self._next_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            nav_frame, text="Edit", command=self._edit_study_card, width=12
        ).pack(side=tk.LEFT, padx=5)

        # Action buttons (Flip / Correct / Incorrect) live in a separate frame
        # so _render_study_state can swap them out without rebuilding everything.
        self._action_frame = tk.Frame(self.container)
        self._action_frame.pack(pady=(0, 20))

        # Populate all labels and buttons for the current card.
        self._render_study_state(state)

    # ── Study event handlers ──────────────────────────────────────────────────
    # Each handler calls exactly one controller method, then passes the
    # returned state to _render_study_state.  No logic lives in these handlers.

    def _on_flip_click(self):
        """User clicked the card face — flip it (FR only; MC is a no-op)."""
        state = self.ctrl.flip_card()
        if state:  # None means the card is MC; nothing to do.
            self._render_study_state(state)

    def _on_prev(self):
        self._render_study_state(self.ctrl.prev_card())

    def _on_next(self):
        self._render_study_state(self.ctrl.next_card())

    def _on_mc_select(self, chosen):
        """User clicked a multiple-choice button."""
        result = self.ctrl.submit_mc_answer(chosen)
        if result is None:
            return  # Card was already scored; ignore stray clicks.

        # Colour the buttons: green for the correct answer, red for the wrong pick.
        for btn in self._mc_choice_btns:
            if btn["text"] == result["correct_answer"]:
                btn.config(bg="green", fg="white")
            elif btn["text"] == chosen and not result["is_correct"]:
                btn.config(bg="red", fg="white")
            btn.config(state=tk.DISABLED)

        # Show feedback text below the choices.
        if result["is_correct"]:
            self._study_feedback.config(text="Correct!", fg="green")
        else:
            self._study_feedback.config(
                text=f"Incorrect! Answer: {result['correct_answer']}", fg="red"
            )

        self._render_study_state(result["state"])

    def _on_mark_correct(self):
        self._render_study_state(self.ctrl.mark_correct())

    def _on_mark_incorrect(self):
        self._render_study_state(self.ctrl.mark_incorrect())

    def _edit_study_card(self):
        """Open the card form for the current study card, then resume the session."""
        card = self.ctrl.get_study_state()["card"]

        def after_edit():
            # Tell the controller to re-fetch the edited card from disk,
            # then rebuild the study UI so the changes are visible.
            self.ctrl.refresh_current_study_card()
            self._build_study_view()

        # Pass deck_path=None and deck_name=None because we're editing from
        # the study view; on_done overrides the default back-navigation.
        self.show_card_form(None, None, card=card, on_done=after_edit)

    def _render_study_state(self, state):
        """Update all study-view widgets to reflect a state snapshot.

        This is the single place where state data is translated into widget
        updates.  All decisions about *what* to show (correct answer, score,
        which buttons) come from the state dict returned by the controller.
        The view just renders whatever it receives.

        Args:
            state: Dict returned by any AppController study method.
        """
        card          = state["card"]
        is_mc         = card["type"] == "mc"
        showing_front = state["showing_front"]
        scored        = state["scored"]

        # ── Card text ─────────────────────────────────────────────────────────
        if is_mc or showing_front:
            self._study_label.config(text=card["front"])
        else:
            self._study_label.config(text=card["back"])

        # ── Side indicator ────────────────────────────────────────────────────
        if is_mc:
            self._study_side_label.config(text="MULTIPLE CHOICE")
        elif showing_front:
            self._study_side_label.config(text="FRONT")
        else:
            self._study_side_label.config(text="BACK")

        # ── Progress counter ──────────────────────────────────────────────────
        self._study_counter.config(
            text=f"Card {state['index'] + 1} of {state['total']}"
        )

        # ── Historical score ──────────────────────────────────────────────────
        correct, incorrect = card["correct"], card["incorrect"]
        total = correct + incorrect
        if total > 0:
            pct = round(correct / total * 100)
            self._study_score_label.config(text=f"Score: {correct}/{total} ({pct}%)")
        else:
            self._study_score_label.config(text="Score: no attempts yet")

        # ── Feedback text ─────────────────────────────────────────────────────
        # Clear feedback when navigating to a new (unscored) card.
        # Preserve it when re-rendering after scoring (e.g. after mark_correct).
        if not scored:
            self._study_feedback.config(text="")

        # ── MC choice buttons ─────────────────────────────────────────────────
        for widget in self._study_mc_frame.winfo_children():
            widget.destroy()
        self._mc_choice_btns = []

        if is_mc and not scored:
            # Shuffle the choices fresh each time the card is shown so the
            # correct answer isn't always in the same position.
            all_choices = [card["back"]] + card["choices"]
            random.shuffle(all_choices)
            for choice in all_choices:
                btn = tk.Button(
                    self._study_mc_frame,
                    text=choice,
                    font=("Arial", 12),
                    anchor=tk.W,
                    command=lambda c=choice: self._on_mc_select(c),
                )
                btn.pack(fill=tk.X, pady=2)
                self._mc_choice_btns.append(btn)

        # ── Action buttons ────────────────────────────────────────────────────
        # The action frame is cleared and repopulated each render so the right
        # buttons appear for the current card type and state.
        for widget in self._action_frame.winfo_children():
            widget.destroy()

        if is_mc:
            pass  # MC cards use choice buttons above; no action buttons needed.
        elif showing_front:
            tk.Button(
                self._action_frame, text="Flip",
                command=self._on_flip_click, width=12,
            ).pack(side=tk.LEFT, padx=5)
        elif not scored:
            tk.Button(
                self._action_frame, text="Correct",
                command=self._on_mark_correct, width=12, fg="green",
            ).pack(side=tk.LEFT, padx=5)
            tk.Button(
                self._action_frame, text="Incorrect",
                command=self._on_mark_incorrect, width=12, fg="red",
            ).pack(side=tk.LEFT, padx=5)
        else:
            tk.Label(
                self._action_frame, text="Scored!", font=("Arial", 11), fg="gray"
            ).pack(side=tk.LEFT, padx=5)

    def _add_order_menu(self, top_bar, current_order):
        """Add the card-order OptionMenu to the right side of top_bar.

        The dropdown lets the user re-sort the study deck without leaving the
        session.  It packs to the right so it doesn't crowd the ← button.

        Args:
            top_bar:       The Frame returned by _add_back_button.
            current_order: String matching one of the ORDER_OPTIONS entries,
                           used to pre-select the current mode on rebuild.
        """
        ORDER_OPTIONS = ["Random", "Original", "Lowest-scored"]
        self._order_var = tk.StringVar(value=current_order)
        tk.OptionMenu(
            top_bar,
            self._order_var,
            *ORDER_OPTIONS,
            command=self._on_study_order_change,
        ).pack(side=tk.RIGHT, padx=4)
        tk.Label(top_bar, text="Order:", font=("Arial", 10)).pack(side=tk.RIGHT)

    def _on_study_order_change(self, mode):
        """Called when the user picks a new order from the dropdown.

        Delegates to the controller (which re-sorts and resets the index),
        then re-renders the study view to reflect the new first card.
        """
        state = self.ctrl.set_study_order(mode)
        self._render_study_state(state)

    def on_close(self):
        self.ctrl.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    app  = TkView(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
