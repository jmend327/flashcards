import tkinter as tk
from tkinter import messagebox, simpledialog
import json
import os
import re
import random

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public_flashcards")
PRIVATE_DIR = os.path.join(BASE_DIR, "private_flashcards")
LOCAL_DIR = os.path.join(BASE_DIR, ".local")
SCORES_PATH = os.path.join(LOCAL_DIR, "scores.json")
LEGACY_DB = os.path.join(BASE_DIR, "flashcards.db")


class ScoreStore:
    """Stores card scores in .local/scores.json, separate from deck content.

    Keys use forward-slash relative paths so the file is portable if the
    whole project folder is moved.  Deck files are never touched.
    """

    def __init__(self):
        os.makedirs(LOCAL_DIR, exist_ok=True)
        # { "rel/path.json": { "card_local_id": [correct, incorrect] } }
        self._data = {}
        if os.path.exists(SCORES_PATH):
            try:
                with open(SCORES_PATH, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                pass

    def _rel(self, abs_path):
        return os.path.relpath(abs_path, BASE_DIR).replace(os.sep, "/")

    def _flush(self):
        with open(SCORES_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, deck_path, local_id):
        """Return (correct, incorrect) for a card."""
        pair = self._data.get(self._rel(deck_path), {}).get(str(local_id), [0, 0])
        return pair[0], pair[1]

    def record_correct(self, deck_path, local_id):
        rel = self._rel(deck_path)
        self._data.setdefault(rel, {}).setdefault(str(local_id), [0, 0])
        self._data[rel][str(local_id)][0] += 1
        self._flush()

    def record_incorrect(self, deck_path, local_id):
        rel = self._rel(deck_path)
        self._data.setdefault(rel, {}).setdefault(str(local_id), [0, 0])
        self._data[rel][str(local_id)][1] += 1
        self._flush()

    def absorb(self, deck_path, local_id, correct, incorrect):
        """Pull scores already baked into a deck file into the store."""
        if correct == 0 and incorrect == 0:
            return
        rel = self._rel(deck_path)
        existing = self._data.get(rel, {}).get(str(local_id), [0, 0])
        self._data.setdefault(rel, {})[str(local_id)] = [
            existing[0] + correct,
            existing[1] + incorrect,
        ]
        self._flush()


class DeckStorage:
    """File-based storage. Each deck is a .json file inside either
    public_flashcards/ or private_flashcards/."""

    def __init__(self):
        os.makedirs(PUBLIC_DIR, exist_ok=True)
        os.makedirs(PRIVATE_DIR, exist_ok=True)

        self.scores = ScoreStore()

        # session_id (int) → (deck_path, local_card_id)
        self._registry = {}
        # (deck_path, local_card_id) → session_id
        self._reverse = {}
        self._next_sid = 1

        self._migrate_from_sqlite()
        self._migrate_scores_from_decks()
        self._seed_public_decks()

    # ── File helpers ─────────────────────────────────────────────

    def _load(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _safe_name(self, name):
        return re.sub(r'[<>:"/\\|?*]', "", name).strip() or "deck"

    def _new_path(self, folder, name):
        base = self._safe_name(name)
        path = os.path.join(folder, base + ".json")
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{base}_{n}.json")
            n += 1
        return path

    # ── Session-ID registry ──────────────────────────────────────

    def _get_sid(self, deck_path, local_id):
        key = (deck_path, local_id)
        if key not in self._reverse:
            sid = self._next_sid
            self._next_sid += 1
            self._registry[sid] = key
            self._reverse[key] = sid
        return self._reverse[key]

    def _resolve(self, session_id):
        return self._registry[session_id]  # (deck_path, local_id)

    # ── Migration from old SQLite DB ─────────────────────────────

    def _migrate_from_sqlite(self):
        if not os.path.exists(LEGACY_DB):
            return
        try:
            import sqlite3
            conn = sqlite3.connect(LEGACY_DB)
            decks = conn.execute("SELECT id, name FROM decks").fetchall()
            for deck_id, deck_name in decks:
                PUBLIC_NAMES = {"Light Trivia", "Fun Trivia Mix"}
                folder = PUBLIC_DIR if deck_name in PUBLIC_NAMES else PRIVATE_DIR
                safe = self._safe_name(deck_name)
                target = os.path.join(folder, safe + ".json")
                if os.path.exists(target):
                    continue

                rows = conn.execute(
                    "SELECT id, front, back, correct_count, incorrect_count,"
                    " card_type, choices FROM cards WHERE deck_id = ?"
                    " ORDER BY created_at",
                    (deck_id,),
                ).fetchall()

                deck_tags = [
                    r[0] for r in conn.execute(
                        "SELECT t.name FROM tags t"
                        " JOIN deck_tags dt ON t.id = dt.tag_id"
                        " WHERE dt.deck_id = ?",
                        (deck_id,),
                    ).fetchall()
                ]

                cards = []
                for i, row in enumerate(rows, 1):
                    old_id, front, back, correct, incorrect, ctype, choices_json = row
                    ctags = [
                        r[0] for r in conn.execute(
                            "SELECT t.name FROM tags t"
                            " JOIN card_tags ct ON t.id = ct.tag_id"
                            " WHERE ct.card_id = ?",
                            (old_id,),
                        ).fetchall()
                    ]
                    cards.append({
                        "id": i,
                        "front": front,
                        "back": back,
                        "card_type": ctype,
                        "choices": json.loads(choices_json) if choices_json else None,
                        "tags": ctags,
                    })
                    self.scores.absorb(target, i, correct, incorrect)

                self._save(target, {
                    "name": deck_name,
                    "tags": deck_tags,
                    "next_id": len(cards) + 1,
                    "cards": cards,
                })

            conn.close()
            os.rename(LEGACY_DB, LEGACY_DB + ".migrated")
        except Exception as e:
            print(f"Migration warning: {e}")

    # ── Score migration from deck files ──────────────────────────

    def _migrate_scores_from_decks(self):
        """If any deck JSON files still have correct_count/incorrect_count baked
        in (from before scores were separated), absorb them into ScoreStore and
        remove the fields from the file so deck files stay score-free."""
        for folder in (PUBLIC_DIR, PRIVATE_DIR):
            for deck_path, _ in self.get_decks_in_folder(folder):
                try:
                    data = self._load(deck_path)
                except Exception:
                    continue
                dirty = False
                for card in data.get("cards", []):
                    correct = card.pop("correct_count", None)
                    incorrect = card.pop("incorrect_count", None)
                    if correct is not None or incorrect is not None:
                        dirty = True
                        self.scores.absorb(deck_path, card["id"],
                                           correct or 0, incorrect or 0)
                if dirty:
                    self._save(deck_path, data)

    # ── Public example deck seeding ──────────────────────────────

    def _seed_public_decks(self):
        target = os.path.join(PUBLIC_DIR, "Fun Trivia Mix.json")
        if os.path.exists(target):
            return
        cards = [
            {
                "id": 1,
                "front": "Which planet is closest to the Sun?",
                "back": "Mercury",
                "card_type": "mc",
                "choices": ["Venus", "Earth", "Mars"],
                "tags": [],
            },
            {
                "id": 2,
                "front": "What is the largest ocean on Earth?",
                "back": "Pacific Ocean",
                "card_type": "mc",
                "choices": ["Atlantic Ocean", "Indian Ocean", "Arctic Ocean"],
                "tags": [],
            },
            {
                "id": 3,
                "front": "How many sides does a pentagon have?",
                "back": "5",
                "card_type": "mc",
                "choices": ["4", "6", "8"],
                "tags": [],
            },
            {
                "id": 4,
                "front": "What is the most spoken language in the world by native speakers?",
                "back": "Mandarin Chinese",
                "card_type": "mc",
                "choices": ["English", "Spanish", "Hindi"],
                "tags": [],
            },
            {
                "id": 5,
                "front": "What is 15% of 200?",
                "back": "30",
                "card_type": "mc",
                "choices": ["25", "35", "45"],
                "tags": [],
            },
            {
                "id": 6,
                "front": "What year did World War II end?",
                "back": "1945",
                "card_type": "free",
                "choices": None,
                "tags": [],
            },
            {
                "id": 7,
                "front": "What gas do plants absorb during photosynthesis?",
                "back": "Carbon dioxide (CO2)",
                "card_type": "free",
                "choices": None,
                "tags": [],
            },
            {
                "id": 8,
                "front": "What is the square root of 64?",
                "back": "8",
                "card_type": "free",
                "choices": None,
                "tags": [],
            },
        ]
        self._save(target, {
            "name": "Fun Trivia Mix",
            "tags": [],
            "next_id": 9,
            "cards": cards,
        })

    # ── Folder queries ───────────────────────────────────────────

    def get_decks_in_folder(self, folder):
        """Return list of (deck_path, name) sorted by name."""
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
            except Exception:
                pass
        result.sort(key=lambda x: x[1].lower())
        return result

    # ── Deck CRUD ────────────────────────────────────────────────

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
        gone = [sid for sid, (p, _) in self._registry.items() if p == deck_path]
        for sid in gone:
            _, lid = self._registry.pop(sid)
            self._reverse.pop((deck_path, lid), None)

    def card_count(self, deck_path):
        try:
            return len(self._load(deck_path).get("cards", []))
        except Exception:
            return 0

    def get_deck_tags(self, deck_path):
        try:
            return self._load(deck_path).get("tags", [])
        except Exception:
            return []

    def set_deck_tags(self, deck_path, tags):
        data = self._load(deck_path)
        data["tags"] = [t.strip().lower() for t in tags if t.strip()]
        self._save(deck_path, data)

    # ── Card helpers ─────────────────────────────────────────────

    def _to_tuple(self, deck_path, card):
        sid = self._get_sid(deck_path, card["id"])
        correct, incorrect = self.scores.get(deck_path, card["id"])
        choices_json = json.dumps(card["choices"]) if card.get("choices") else None
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
        for i, c in enumerate(data.get("cards", [])):
            if c["id"] == local_id:
                return i, c
        return None, None

    # ── Card CRUD ────────────────────────────────────────────────

    def get_cards(self, deck_path):
        data = self._load(deck_path)
        return [self._to_tuple(deck_path, c) for c in data.get("cards", [])]

    def create_card(self, deck_path, front, back, card_type="free", choices=None):
        data = self._load(deck_path)
        local_id = data.get("next_id", 1)
        data["cards"].append({
            "id": local_id,
            "front": front,
            "back": back,
            "card_type": card_type,
            "choices": choices,
            "tags": [],
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
        except Exception:
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

    # ── Card tags ────────────────────────────────────────────────

    def get_card_tags(self, session_id):
        try:
            deck_path, local_id = self._resolve(session_id)
            data = self._load(deck_path)
            _, card = self._find(data, local_id)
            return card.get("tags", []) if card else []
        except Exception:
            return []

    def set_card_tags(self, session_id, tags):
        deck_path, local_id = self._resolve(session_id)
        data = self._load(deck_path)
        idx, card = self._find(data, local_id)
        if card is not None:
            card["tags"] = [t.strip().lower() for t in tags if t.strip()]
            data["cards"][idx] = card
            self._save(deck_path, data)

    # ── Tag queries across all decks ─────────────────────────────

    def _all_deck_paths(self):
        paths = []
        for folder in (PUBLIC_DIR, PRIVATE_DIR):
            for path, _ in self.get_decks_in_folder(folder):
                paths.append(path)
        return paths

    def get_all_tags_with_counts(self):
        card_counts, deck_counts = {}, {}
        for deck_path in self._all_deck_paths():
            try:
                data = self._load(deck_path)
            except Exception:
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
        result = []
        for deck_path in self._all_deck_paths():
            try:
                data = self._load(deck_path)
            except Exception:
                continue
            for card in data.get("cards", []):
                if tag_name in card.get("tags", []):
                    result.append(self._to_tuple(deck_path, card))
        return result

    def get_cards_by_deck_tag(self, tag_name):
        result = []
        for deck_path in self._all_deck_paths():
            try:
                data = self._load(deck_path)
            except Exception:
                continue
            if tag_name in data.get("tags", []):
                for card in data.get("cards", []):
                    result.append(self._to_tuple(deck_path, card))
        return result

    def close(self):
        pass  # nothing to close for file-based storage


# Card tuple indices
C_ID, C_FRONT, C_BACK, C_CORRECT, C_INCORRECT, C_TYPE, C_CHOICES = range(7)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Flashcards")
        self.root.geometry("600x550")
        self.root.minsize(400, 400)
        self.db = DeckStorage()

        self.container = tk.Frame(root)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.show_home()

    def _clear(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    # ── Home View ──────────────────────────────────────────────

    def show_home(self):
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

        # Each entry is None (section header) or (deck_path, name)
        self.deck_list_entries = []

        def add_section(label, folder):
            self.deck_listbox.insert(tk.END, f"  \u2500\u2500 {label} ")
            self.deck_list_entries.append(None)
            idx = len(self.deck_list_entries) - 1
            self.deck_listbox.itemconfigure(
                idx, fg="gray",
                selectbackground="#e8e8e8", selectforeground="gray"
            )
            for deck_path, name in self.db.get_decks_in_folder(folder):
                count = self.db.card_count(deck_path)
                dtags = self.db.get_deck_tags(deck_path)
                tag_str = f"  [{', '.join(dtags)}]" if dtags else ""
                self.deck_listbox.insert(
                    tk.END, f"    {name}  ({count} cards){tag_str}"
                )
                self.deck_list_entries.append((deck_path, name))

        add_section("Example Sets", PUBLIC_DIR)
        add_section("My Sets", PRIVATE_DIR)

        self.deck_listbox.bind("<Double-Button-1>", lambda e: self._open_deck())

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 5))

        tk.Button(btn_frame, text="New Deck", command=self._new_deck, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Open", command=self._open_deck, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(
            btn_frame, text="Rename", command=self._rename_deck, width=12
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="Delete", command=self._delete_deck, width=12
        ).pack(side=tk.LEFT, padx=5)

        btn_frame2 = tk.Frame(self.container)
        btn_frame2.pack(pady=(0, 20))

        tk.Button(
            btn_frame2, text="Deck Tags", command=self._edit_deck_tags, width=12
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame2, text="Study by Tag", command=self.show_tag_picker, width=12
        ).pack(side=tk.LEFT, padx=5)

    def _selected_deck(self):
        sel = self.deck_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a deck.")
            return None
        entry = self.deck_list_entries[sel[0]]
        if entry is None:
            messagebox.showwarning("No Selection", "Please select a deck.")
            return None
        return entry  # (deck_path, name)

    def _new_deck(self):
        name = simpledialog.askstring("New Deck", "Deck name:")
        if name and name.strip():
            self.db.create_deck(name.strip(), PRIVATE_DIR)
            self.show_home()

    def _rename_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        deck_path, deck_name = deck
        name = simpledialog.askstring(
            "Rename Deck", "New name:", initialvalue=deck_name
        )
        if name and name.strip():
            self.db.rename_deck(deck_path, name.strip())
            self.show_home()

    def _delete_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        deck_path, deck_name = deck
        if messagebox.askyesno(
            "Delete Deck", f"Delete '{deck_name}' and all its cards?"
        ):
            self.db.delete_deck(deck_path)
            self.show_home()

    def _open_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        deck_path, deck_name = deck
        self.show_deck(deck_path, deck_name)

    def _edit_deck_tags(self):
        deck = self._selected_deck()
        if not deck:
            return
        deck_path, deck_name = deck
        current = self.db.get_deck_tags(deck_path)
        result = simpledialog.askstring(
            "Deck Tags",
            f"Tags for '{deck_name}' (comma-separated):",
            initialvalue=", ".join(current),
        )
        if result is not None:
            tags = [t.strip() for t in result.split(",") if t.strip()]
            self.db.set_deck_tags(deck_path, tags)
            self.show_home()

    # ── Tag Picker View ────────────────────────────────────────

    def show_tag_picker(self):
        tag_data = self.db.get_all_tags_with_counts()
        if not tag_data:
            messagebox.showinfo("No Tags", "No tags have been created yet.")
            return

        self._clear()

        tk.Label(
            self.container, text="Study by Tag", font=("Arial", 20, "bold")
        ).pack(pady=(20, 10))

        tk.Label(
            self.container,
            text="Select a tag to study all matching cards:",
            font=("Arial", 11),
        ).pack()

        list_frame = tk.Frame(self.container)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._tag_listbox = tk.Listbox(
            list_frame, font=("Arial", 14), yscrollcommand=scrollbar.set
        )
        self._tag_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._tag_listbox.yview)

        self._tag_data = tag_data
        for tag_name, card_count, deck_count in tag_data:
            parts = []
            if card_count:
                parts.append(f"{card_count} cards")
            if deck_count:
                parts.append(f"{deck_count} decks")
            info = ", ".join(parts) if parts else "unused"
            self._tag_listbox.insert(tk.END, f"{tag_name}  ({info})")

        self._tag_listbox.bind(
            "<Double-Button-1>", lambda e: self._study_selected_tag()
        )

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        tk.Button(
            btn_frame, text="Study", command=self._study_selected_tag, width=12
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="Back", command=self.show_home, width=12
        ).pack(side=tk.LEFT, padx=5)

    def _study_selected_tag(self):
        sel = self._tag_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a tag.")
            return
        tag_name = self._tag_data[sel[0]][0]

        card_ids_seen = set()
        cards = []
        for card in self.db.get_cards_by_tag(tag_name):
            if card[C_ID] not in card_ids_seen:
                card_ids_seen.add(card[C_ID])
                cards.append(card)
        for card in self.db.get_cards_by_deck_tag(tag_name):
            if card[C_ID] not in card_ids_seen:
                card_ids_seen.add(card[C_ID])
                cards.append(card)

        if not cards:
            messagebox.showinfo(
                "No Cards", f"No cards found for tag '{tag_name}'."
            )
            return

        self._start_study(cards, f"Tag: {tag_name}", self.show_tag_picker)

    # ── Deck View ──────────────────────────────────────────────

    def show_deck(self, deck_path, deck_name):
        self._clear()

        tk.Label(
            self.container, text=deck_name, font=("Arial", 20, "bold")
        ).pack(pady=(20, 5))

        dtags = self.db.get_deck_tags(deck_path)
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

        self.cards = self.db.get_cards(deck_path)
        for card in self.cards:
            front = card[C_FRONT]
            correct, incorrect = card[C_CORRECT], card[C_INCORRECT]
            card_type = card[C_TYPE]
            ctags = self.db.get_card_tags(card[C_ID])

            prefix = "[MC] " if card_type == "mc" else ""
            tag_str = f"  [{', '.join(ctags)}]" if ctags else ""
            total = correct + incorrect
            if total > 0:
                pct = round(correct / total * 100)
                score_str = f"  {correct}/{total} — {pct}%"
            else:
                score_str = ""
            self.card_listbox.insert(
                tk.END, f"{prefix}{front}{tag_str}{score_str}"
            )

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 5))

        tk.Button(
            btn_frame,
            text="Add Card",
            command=lambda: self.show_card_form(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame,
            text="Edit",
            command=lambda: self._edit_card(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame,
            text="Delete",
            command=lambda: self._delete_card(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

        btn_frame2 = tk.Frame(self.container)
        btn_frame2.pack(pady=(0, 20))

        tk.Button(
            btn_frame2,
            text="Study",
            command=lambda: self._study_deck(deck_path, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame2, text="Back", command=self.show_home, width=12
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
        if messagebox.askyesno(
            "Delete Card", f"Delete this card?\n\n{card[C_FRONT]}"
        ):
            self.db.delete_card(card[C_ID])
            self.show_deck(deck_path, deck_name)

    def _study_deck(self, deck_path, deck_name):
        cards = self.db.get_cards(deck_path)
        if not cards:
            messagebox.showinfo("No Cards", "This deck has no cards to study.")
            return
        self._start_study(
            cards,
            f"Studying: {deck_name}",
            lambda: self.show_deck(deck_path, deck_name),
        )

    # ── Card Form View ─────────────────────────────────────────

    def show_card_form(self, deck_path, deck_name, card=None, on_done=None):
        self._clear()
        editing = card is not None
        title = "Edit Card" if editing else "Add Card"
        _navigate_back = on_done or (lambda: self.show_deck(deck_path, deck_name))

        tk.Label(
            self.container, text=title, font=("Arial", 20, "bold")
        ).pack(pady=(20, 10))

        canvas = tk.Canvas(self.container)
        form_scrollbar = tk.Scrollbar(
            self.container, orient=tk.VERTICAL, command=canvas.yview
        )
        form_outer = tk.Frame(canvas)

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

        tk.Label(form, text="Card Type:", font=("Arial", 12)).pack(anchor=tk.W)
        type_var = tk.StringVar(value="free")
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

        tk.Label(form, text="Front (Question):", font=("Arial", 12)).pack(anchor=tk.W)
        front_text = tk.Text(form, height=3, font=("Arial", 12), wrap=tk.WORD)
        front_text.pack(fill=tk.X, pady=(0, 10))

        self._back_label = tk.Label(form, text="Back (Answer):", font=("Arial", 12))
        self._back_label.pack(anchor=tk.W)
        back_text = tk.Text(form, height=3, font=("Arial", 12), wrap=tk.WORD)
        back_text.pack(fill=tk.X, pady=(0, 10))

        self._mc_frame = tk.Frame(form)
        self._mc_entries = []

        tk.Label(
            self._mc_frame, text="Wrong Choices:", font=("Arial", 12)
        ).pack(anchor=tk.W)

        self._mc_entries_frame = tk.Frame(self._mc_frame)
        self._mc_entries_frame.pack(fill=tk.X)

        mc_btn_frame = tk.Frame(self._mc_frame)
        mc_btn_frame.pack(anchor=tk.W, pady=(5, 10))
        tk.Button(
            mc_btn_frame, text="+ Add Choice", command=lambda: _add_choice_entry()
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(
            mc_btn_frame, text="- Remove Last", command=lambda: _remove_choice_entry()
        ).pack(side=tk.LEFT)

        tk.Label(form, text="Tags (comma-separated):", font=("Arial", 12)).pack(
            anchor=tk.W
        )
        tags_entry = tk.Entry(form, font=("Arial", 12))
        tags_entry.pack(fill=tk.X, pady=(0, 10))

        def _add_choice_entry(value=""):
            entry = tk.Entry(self._mc_entries_frame, font=("Arial", 12))
            entry.pack(fill=tk.X, pady=2)
            if value:
                entry.insert(0, value)
            self._mc_entries.append(entry)

        def _remove_choice_entry():
            if self._mc_entries:
                self._mc_entries[-1].destroy()
                self._mc_entries.pop()

        def _toggle_type():
            if type_var.get() == "mc":
                self._back_label.config(text="Correct Answer:")
                self._mc_frame.pack(fill=tk.X, after=back_text)
                if not self._mc_entries:
                    for _ in range(3):
                        _add_choice_entry()
            else:
                self._back_label.config(text="Back (Answer):")
                self._mc_frame.pack_forget()

        if editing:
            front_text.insert("1.0", card[C_FRONT])
            back_text.insert("1.0", card[C_BACK])
            type_var.set(card[C_TYPE])
            if card[C_TYPE] == "mc" and card[C_CHOICES]:
                for wc in json.loads(card[C_CHOICES]):
                    _add_choice_entry(wc)
            _toggle_type()
            ctags = self.db.get_card_tags(card[C_ID])
            tags_entry.insert(0, ", ".join(ctags))

        def save():
            front = front_text.get("1.0", tk.END).strip()
            back = back_text.get("1.0", tk.END).strip()
            card_type = type_var.get()

            if not front or not back:
                messagebox.showwarning(
                    "Missing Fields", "Front and answer are required."
                )
                return

            choices = None
            if card_type == "mc":
                wrong = [e.get().strip() for e in self._mc_entries if e.get().strip()]
                if len(wrong) < 1:
                    messagebox.showwarning(
                        "Missing Choices",
                        "Add at least 1 wrong choice for multiple choice.",
                    )
                    return
                choices = wrong

            tag_names = [t.strip() for t in tags_entry.get().split(",") if t.strip()]

            if editing:
                self.db.update_card(card[C_ID], front, back, card_type, choices)
                self.db.set_card_tags(card[C_ID], tag_names)
            else:
                card_id = self.db.create_card(deck_path, front, back, card_type, choices)
                self.db.set_card_tags(card_id, tag_names)

            canvas.unbind_all("<MouseWheel>")
            _navigate_back()

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save", command=save, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(
            btn_frame,
            text="Cancel",
            command=lambda: (canvas.unbind_all("<MouseWheel>"), _navigate_back()),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

    # ── Study View ─────────────────────────────────────────────

    def _start_study(self, cards, title, back_callback):
        self._clear()
        random.shuffle(cards)

        self._study_cards = cards
        self._study_title = title
        self._study_index = 0
        self._study_showing_front = True
        self._study_scored = False
        self._study_back_callback = back_callback

        tk.Label(
            self.container, text=title, font=("Arial", 16)
        ).pack(pady=(20, 5))

        self._study_counter = tk.Label(self.container, text="", font=("Arial", 11))
        self._study_counter.pack()

        self._study_score_label = tk.Label(
            self.container, text="", font=("Arial", 10), fg="gray"
        )
        self._study_score_label.pack()

        self._study_card_frame = tk.Frame(self.container, bd=2, relief=tk.GROOVE)
        self._study_card_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=15)

        self._study_side_label = tk.Label(
            self._study_card_frame, text="FRONT", font=("Arial", 10), fg="gray"
        )
        self._study_side_label.pack(pady=(10, 0))

        self._study_label = tk.Label(
            self._study_card_frame,
            text="",
            font=("Arial", 16),
            wraplength=400,
            justify=tk.CENTER,
        )
        self._study_label.pack(expand=True, padx=20, pady=(10, 5))

        self._study_mc_frame = tk.Frame(self._study_card_frame)
        self._study_mc_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        self._study_feedback = tk.Label(
            self._study_card_frame, text="", font=("Arial", 11)
        )
        self._study_feedback.pack(pady=(0, 10))

        self._study_card_frame.bind("<Button-1>", lambda e: self._flip_card())
        self._study_label.bind("<Button-1>", lambda e: self._flip_card())
        self._study_side_label.bind("<Button-1>", lambda e: self._flip_card())

        nav_frame = tk.Frame(self.container)
        nav_frame.pack(pady=(0, 5))

        self._prev_btn = tk.Button(
            nav_frame, text="Previous", command=self._prev_card, width=12
        )
        self._prev_btn.pack(side=tk.LEFT, padx=5)

        self._next_btn = tk.Button(
            nav_frame, text="Next", command=self._next_card, width=12
        )
        self._next_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            nav_frame, text="Edit", command=self._edit_study_card, width=12
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            nav_frame, text="Back", command=back_callback, width=12
        ).pack(side=tk.LEFT, padx=5)

        self._action_frame = tk.Frame(self.container)
        self._action_frame.pack(pady=(0, 20))

        self._update_study_display()

    def _edit_study_card(self):
        card = self._study_cards[self._study_index]
        card_id = card[C_ID]

        def _after_edit():
            refreshed = self.db.get_card_by_id(card_id)
            if refreshed:
                self._study_cards[self._study_index] = refreshed
            self._study_showing_front = True
            self._study_scored = False
            self._resume_study()

        self.show_card_form(None, None, card=card, on_done=_after_edit)

    def _resume_study(self):
        self._clear()

        tk.Label(
            self.container, text=self._study_title, font=("Arial", 16)
        ).pack(pady=(20, 5))

        self._study_counter = tk.Label(self.container, text="", font=("Arial", 11))
        self._study_counter.pack()

        self._study_score_label = tk.Label(
            self.container, text="", font=("Arial", 10), fg="gray"
        )
        self._study_score_label.pack()

        self._study_card_frame = tk.Frame(self.container, bd=2, relief=tk.GROOVE)
        self._study_card_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=15)

        self._study_side_label = tk.Label(
            self._study_card_frame, text="FRONT", font=("Arial", 10), fg="gray"
        )
        self._study_side_label.pack(pady=(10, 0))

        self._study_label = tk.Label(
            self._study_card_frame,
            text="",
            font=("Arial", 16),
            wraplength=400,
            justify=tk.CENTER,
        )
        self._study_label.pack(expand=True, padx=20, pady=(10, 5))

        self._study_mc_frame = tk.Frame(self._study_card_frame)
        self._study_mc_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        self._study_feedback = tk.Label(
            self._study_card_frame, text="", font=("Arial", 11)
        )
        self._study_feedback.pack(pady=(0, 10))

        self._study_card_frame.bind("<Button-1>", lambda e: self._flip_card())
        self._study_label.bind("<Button-1>", lambda e: self._flip_card())
        self._study_side_label.bind("<Button-1>", lambda e: self._flip_card())

        nav_frame = tk.Frame(self.container)
        nav_frame.pack(pady=(0, 5))

        self._prev_btn = tk.Button(
            nav_frame, text="Previous", command=self._prev_card, width=12
        )
        self._prev_btn.pack(side=tk.LEFT, padx=5)

        self._next_btn = tk.Button(
            nav_frame, text="Next", command=self._next_card, width=12
        )
        self._next_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            nav_frame, text="Edit", command=self._edit_study_card, width=12
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            nav_frame, text="Back", command=self._study_back_callback, width=12
        ).pack(side=tk.LEFT, padx=5)

        self._action_frame = tk.Frame(self.container)
        self._action_frame.pack(pady=(0, 20))

        self._update_study_display()

    def _rebuild_action_buttons(self):
        for widget in self._action_frame.winfo_children():
            widget.destroy()

        card = self._study_cards[self._study_index]

        if card[C_TYPE] == "mc":
            return

        if self._study_showing_front:
            tk.Button(
                self._action_frame, text="Flip", command=self._flip_card, width=12
            ).pack(side=tk.LEFT, padx=5)
        elif not self._study_scored:
            tk.Button(
                self._action_frame,
                text="Correct",
                command=self._mark_correct,
                width=12,
                fg="green",
            ).pack(side=tk.LEFT, padx=5)
            tk.Button(
                self._action_frame,
                text="Incorrect",
                command=self._mark_incorrect,
                width=12,
                fg="red",
            ).pack(side=tk.LEFT, padx=5)
        else:
            tk.Label(
                self._action_frame, text="Scored!", font=("Arial", 11), fg="gray"
            ).pack(side=tk.LEFT, padx=5)

    def _rebuild_mc_choices(self):
        for widget in self._study_mc_frame.winfo_children():
            widget.destroy()

        card = self._study_cards[self._study_index]
        if card[C_TYPE] != "mc":
            return

        correct_answer = card[C_BACK]
        wrong_choices = json.loads(card[C_CHOICES]) if card[C_CHOICES] else []
        all_choices = [correct_answer] + wrong_choices
        random.shuffle(all_choices)

        self._mc_correct_answer = correct_answer
        self._mc_choice_btns = []

        for choice in all_choices:
            btn = tk.Button(
                self._study_mc_frame,
                text=choice,
                font=("Arial", 12),
                anchor=tk.W,
                command=lambda c=choice: self._mc_select(c),
            )
            btn.pack(fill=tk.X, pady=2)
            self._mc_choice_btns.append(btn)

    def _update_study_display(self):
        card = self._study_cards[self._study_index]
        is_mc = card[C_TYPE] == "mc"

        self._study_label.config(text=card[C_FRONT])

        if is_mc:
            self._study_side_label.config(text="MULTIPLE CHOICE")
        elif self._study_showing_front:
            self._study_side_label.config(text="FRONT")
        else:
            self._study_label.config(text=card[C_BACK])
            self._study_side_label.config(text="BACK")

        self._study_counter.config(
            text=f"Card {self._study_index + 1} of {len(self._study_cards)}"
        )

        correct, incorrect = card[C_CORRECT], card[C_INCORRECT]
        total = correct + incorrect
        if total > 0:
            pct = round(correct / total * 100)
            self._study_score_label.config(text=f"Score: {correct}/{total} ({pct}%)")
        else:
            self._study_score_label.config(text="Score: no attempts yet")

        self._study_feedback.config(text="")

        for widget in self._study_mc_frame.winfo_children():
            widget.destroy()

        if is_mc and not self._study_scored:
            self._rebuild_mc_choices()

        self._rebuild_action_buttons()

    def _flip_card(self):
        card = self._study_cards[self._study_index]
        if card[C_TYPE] == "mc":
            return
        if self._study_showing_front:
            self._study_showing_front = False
            self._update_study_display()

    def _mc_select(self, chosen):
        if self._study_scored:
            return

        card = self._study_cards[self._study_index]
        is_correct = chosen == self._mc_correct_answer

        if is_correct:
            self.db.record_correct(card[C_ID])
            updated = list(card)
            updated[C_CORRECT] += 1
            self._study_feedback.config(text="Correct!", fg="green")
        else:
            self.db.record_incorrect(card[C_ID])
            updated = list(card)
            updated[C_INCORRECT] += 1
            self._study_feedback.config(
                text=f"Incorrect! Answer: {self._mc_correct_answer}", fg="red"
            )

        self._study_cards[self._study_index] = tuple(updated)
        self._study_scored = True

        for btn in self._mc_choice_btns:
            if btn["text"] == self._mc_correct_answer:
                btn.config(bg="green", fg="white")
            elif btn["text"] == chosen and not is_correct:
                btn.config(bg="red", fg="white")
            btn.config(state=tk.DISABLED)

    def _mark_correct(self):
        card = self._study_cards[self._study_index]
        self.db.record_correct(card[C_ID])
        updated = list(card)
        updated[C_CORRECT] += 1
        self._study_cards[self._study_index] = tuple(updated)
        self._study_scored = True
        self._update_study_display()

    def _mark_incorrect(self):
        card = self._study_cards[self._study_index]
        self.db.record_incorrect(card[C_ID])
        updated = list(card)
        updated[C_INCORRECT] += 1
        self._study_cards[self._study_index] = tuple(updated)
        self._study_scored = True
        self._update_study_display()

    def _next_card(self):
        self._study_index = (self._study_index + 1) % len(self._study_cards)
        self._study_showing_front = True
        self._study_scored = False
        self._update_study_display()

    def _prev_card(self):
        self._study_index = (self._study_index - 1) % len(self._study_cards)
        self._study_showing_front = True
        self._study_scored = False
        self._update_study_display()

    def on_close(self):
        self.db.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
