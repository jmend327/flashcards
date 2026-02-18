import tkinter as tk
from tkinter import messagebox, simpledialog
import sqlite3
import os
import random

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flashcards.db")


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
            );
        """)
        self.conn.commit()

    def get_decks(self):
        cur = self.conn.execute("SELECT id, name FROM decks ORDER BY name")
        return cur.fetchall()

    def create_deck(self, name):
        self.conn.execute("INSERT INTO decks (name) VALUES (?)", (name,))
        self.conn.commit()

    def rename_deck(self, deck_id, name):
        self.conn.execute("UPDATE decks SET name = ? WHERE id = ?", (name, deck_id))
        self.conn.commit()

    def delete_deck(self, deck_id):
        self.conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        self.conn.commit()

    def get_cards(self, deck_id):
        cur = self.conn.execute(
            "SELECT id, front, back FROM cards WHERE deck_id = ? ORDER BY created_at",
            (deck_id,),
        )
        return cur.fetchall()

    def card_count(self, deck_id):
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE deck_id = ?", (deck_id,)
        )
        return cur.fetchone()[0]

    def create_card(self, deck_id, front, back):
        self.conn.execute(
            "INSERT INTO cards (deck_id, front, back) VALUES (?, ?, ?)",
            (deck_id, front, back),
        )
        self.conn.commit()

    def update_card(self, card_id, front, back):
        self.conn.execute(
            "UPDATE cards SET front = ?, back = ? WHERE id = ?",
            (front, back, card_id),
        )
        self.conn.commit()

    def delete_card(self, card_id):
        self.conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Flashcards")
        self.root.geometry("600x500")
        self.root.minsize(400, 350)
        self.db = Database(DB_PATH)

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

        self.decks = self.db.get_decks()
        for deck_id, name in self.decks:
            count = self.db.card_count(deck_id)
            self.deck_listbox.insert(tk.END, f"{name}  ({count} cards)")

        self.deck_listbox.bind("<Double-Button-1>", lambda e: self._open_deck())

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

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

    def _selected_deck(self):
        sel = self.deck_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a deck.")
            return None
        return self.decks[sel[0]]

    def _new_deck(self):
        name = simpledialog.askstring("New Deck", "Deck name:")
        if name and name.strip():
            self.db.create_deck(name.strip())
            self.show_home()

    def _rename_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        name = simpledialog.askstring(
            "Rename Deck", "New name:", initialvalue=deck[1]
        )
        if name and name.strip():
            self.db.rename_deck(deck[0], name.strip())
            self.show_home()

    def _delete_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        if messagebox.askyesno(
            "Delete Deck", f"Delete '{deck[1]}' and all its cards?"
        ):
            self.db.delete_deck(deck[0])
            self.show_home()

    def _open_deck(self):
        deck = self._selected_deck()
        if not deck:
            return
        self.show_deck(deck[0], deck[1])

    # ── Deck View ──────────────────────────────────────────────

    def show_deck(self, deck_id, deck_name):
        self._clear()

        tk.Label(
            self.container, text=deck_name, font=("Arial", 20, "bold")
        ).pack(pady=(20, 10))

        list_frame = tk.Frame(self.container)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.card_listbox = tk.Listbox(
            list_frame, font=("Arial", 12), yscrollcommand=scrollbar.set
        )
        self.card_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.card_listbox.yview)

        self.cards = self.db.get_cards(deck_id)
        for _, front, _ in self.cards:
            self.card_listbox.insert(tk.END, front)

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 5))

        tk.Button(
            btn_frame,
            text="Add Card",
            command=lambda: self.show_card_form(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame,
            text="Edit",
            command=lambda: self._edit_card(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame,
            text="Delete",
            command=lambda: self._delete_card(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

        btn_frame2 = tk.Frame(self.container)
        btn_frame2.pack(pady=(0, 20))

        tk.Button(
            btn_frame2,
            text="Study",
            command=lambda: self.show_study(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame2, text="Back", command=self.show_home, width=12
        ).pack(side=tk.LEFT, padx=5)

    def _edit_card(self, deck_id, deck_name):
        sel = self.card_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a card.")
            return
        card = self.cards[sel[0]]
        self.show_card_form(deck_id, deck_name, card=card)

    def _delete_card(self, deck_id, deck_name):
        sel = self.card_listbox.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a card.")
            return
        card = self.cards[sel[0]]
        if messagebox.askyesno("Delete Card", f"Delete this card?\n\n{card[1]}"):
            self.db.delete_card(card[0])
            self.show_deck(deck_id, deck_name)

    # ── Card Form View ─────────────────────────────────────────

    def show_card_form(self, deck_id, deck_name, card=None):
        self._clear()
        editing = card is not None
        title = "Edit Card" if editing else "Add Card"

        tk.Label(
            self.container, text=title, font=("Arial", 20, "bold")
        ).pack(pady=(20, 10))

        form = tk.Frame(self.container)
        form.pack(fill=tk.BOTH, expand=True, padx=40, pady=10)

        tk.Label(form, text="Front:", font=("Arial", 12)).pack(anchor=tk.W)
        front_text = tk.Text(form, height=4, font=("Arial", 12), wrap=tk.WORD)
        front_text.pack(fill=tk.X, pady=(0, 10))

        tk.Label(form, text="Back:", font=("Arial", 12)).pack(anchor=tk.W)
        back_text = tk.Text(form, height=4, font=("Arial", 12), wrap=tk.WORD)
        back_text.pack(fill=tk.X, pady=(0, 10))

        if editing:
            front_text.insert("1.0", card[1])
            back_text.insert("1.0", card[2])

        def save():
            front = front_text.get("1.0", tk.END).strip()
            back = back_text.get("1.0", tk.END).strip()
            if not front or not back:
                messagebox.showwarning(
                    "Missing Fields", "Both front and back are required."
                )
                return
            if editing:
                self.db.update_card(card[0], front, back)
            else:
                self.db.create_card(deck_id, front, back)
            self.show_deck(deck_id, deck_name)

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save", command=save, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(
            btn_frame,
            text="Cancel",
            command=lambda: self.show_deck(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

    # ── Study View ─────────────────────────────────────────────

    def show_study(self, deck_id, deck_name):
        cards = self.db.get_cards(deck_id)
        if not cards:
            messagebox.showinfo("No Cards", "This deck has no cards to study.")
            return

        self._clear()
        random.shuffle(cards)

        self._study_cards = cards
        self._study_index = 0
        self._study_showing_front = True

        tk.Label(
            self.container, text=f"Studying: {deck_name}", font=("Arial", 16)
        ).pack(pady=(20, 5))

        self._study_counter = tk.Label(
            self.container, text="", font=("Arial", 11)
        )
        self._study_counter.pack()

        card_frame = tk.Frame(self.container, bd=2, relief=tk.GROOVE)
        card_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=15)

        self._study_side_label = tk.Label(
            card_frame, text="FRONT", font=("Arial", 10), fg="gray"
        )
        self._study_side_label.pack(pady=(10, 0))

        self._study_label = tk.Label(
            card_frame,
            text="",
            font=("Arial", 16),
            wraplength=400,
            justify=tk.CENTER,
        )
        self._study_label.pack(expand=True, padx=20, pady=20)

        card_frame.bind("<Button-1>", lambda e: self._flip_card())
        self._study_label.bind("<Button-1>", lambda e: self._flip_card())
        self._study_side_label.bind("<Button-1>", lambda e: self._flip_card())

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        self._prev_btn = tk.Button(
            btn_frame, text="Previous", command=self._prev_card, width=12
        )
        self._prev_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_frame, text="Flip", command=self._flip_card, width=12
        ).pack(side=tk.LEFT, padx=5)

        self._next_btn = tk.Button(
            btn_frame, text="Next", command=self._next_card, width=12
        )
        self._next_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_frame,
            text="Back",
            command=lambda: self.show_deck(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

        self._update_study_display()

    def _update_study_display(self):
        card = self._study_cards[self._study_index]
        if self._study_showing_front:
            self._study_label.config(text=card[1])
            self._study_side_label.config(text="FRONT")
        else:
            self._study_label.config(text=card[2])
            self._study_side_label.config(text="BACK")

        self._study_counter.config(
            text=f"Card {self._study_index + 1} of {len(self._study_cards)}"
        )
        self._prev_btn.config(
            state=tk.NORMAL if self._study_index > 0 else tk.DISABLED
        )
        self._next_btn.config(
            state=tk.NORMAL
            if self._study_index < len(self._study_cards) - 1
            else tk.DISABLED
        )

    def _flip_card(self):
        self._study_showing_front = not self._study_showing_front
        self._update_study_display()

    def _next_card(self):
        if self._study_index < len(self._study_cards) - 1:
            self._study_index += 1
            self._study_showing_front = True
            self._update_study_display()

    def _prev_card(self):
        if self._study_index > 0:
            self._study_index -= 1
            self._study_showing_front = True
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
