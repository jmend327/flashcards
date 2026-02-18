import tkinter as tk
from tkinter import messagebox, simpledialog
import sqlite3
import json
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
                card_type TEXT NOT NULL DEFAULT 'free',
                choices TEXT,
                correct_count INTEGER NOT NULL DEFAULT 0,
                incorrect_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
            );
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        cur = self.conn.execute("PRAGMA table_info(cards)")
        columns = {row[1] for row in cur.fetchall()}
        if "correct_count" not in columns:
            self.conn.execute(
                "ALTER TABLE cards ADD COLUMN correct_count INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.execute(
                "ALTER TABLE cards ADD COLUMN incorrect_count INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.commit()
        if "card_type" not in columns:
            self.conn.execute(
                "ALTER TABLE cards ADD COLUMN card_type TEXT NOT NULL DEFAULT 'free'"
            )
            self.conn.execute("ALTER TABLE cards ADD COLUMN choices TEXT")
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
            "SELECT id, front, back, correct_count, incorrect_count,"
            " card_type, choices"
            " FROM cards WHERE deck_id = ? ORDER BY created_at",
            (deck_id,),
        )
        return cur.fetchall()

    def record_correct(self, card_id):
        self.conn.execute(
            "UPDATE cards SET correct_count = correct_count + 1 WHERE id = ?",
            (card_id,),
        )
        self.conn.commit()

    def record_incorrect(self, card_id):
        self.conn.execute(
            "UPDATE cards SET incorrect_count = incorrect_count + 1 WHERE id = ?",
            (card_id,),
        )
        self.conn.commit()

    def card_count(self, deck_id):
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE deck_id = ?", (deck_id,)
        )
        return cur.fetchone()[0]

    def create_card(self, deck_id, front, back, card_type="free", choices=None):
        choices_json = json.dumps(choices) if choices else None
        self.conn.execute(
            "INSERT INTO cards (deck_id, front, back, card_type, choices)"
            " VALUES (?, ?, ?, ?, ?)",
            (deck_id, front, back, card_type, choices_json),
        )
        self.conn.commit()

    def update_card(self, card_id, front, back, card_type="free", choices=None):
        choices_json = json.dumps(choices) if choices else None
        self.conn.execute(
            "UPDATE cards SET front = ?, back = ?, card_type = ?, choices = ?"
            " WHERE id = ?",
            (front, back, card_type, choices_json, card_id),
        )
        self.conn.commit()

    def delete_card(self, card_id):
        self.conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()


# Card tuple indices
C_ID, C_FRONT, C_BACK, C_CORRECT, C_INCORRECT, C_TYPE, C_CHOICES = range(7)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Flashcards")
        self.root.geometry("600x550")
        self.root.minsize(400, 400)
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
        for card in self.cards:
            front = card[C_FRONT]
            correct, incorrect = card[C_CORRECT], card[C_INCORRECT]
            card_type = card[C_TYPE]
            tag = "[MC] " if card_type == "mc" else ""
            total = correct + incorrect
            if total > 0:
                pct = round(correct / total * 100)
                self.card_listbox.insert(
                    tk.END, f"{tag}{front}  [{correct}/{total} — {pct}%]"
                )
            else:
                self.card_listbox.insert(tk.END, f"{tag}{front}")

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
        if messagebox.askyesno(
            "Delete Card", f"Delete this card?\n\n{card[C_FRONT]}"
        ):
            self.db.delete_card(card[C_ID])
            self.show_deck(deck_id, deck_name)

    # ── Card Form View ─────────────────────────────────────────

    def show_card_form(self, deck_id, deck_name, card=None):
        self._clear()
        editing = card is not None
        title = "Edit Card" if editing else "Add Card"

        tk.Label(
            self.container, text=title, font=("Arial", 20, "bold")
        ).pack(pady=(20, 10))

        # Scrollable form area
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

        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        form = form_outer

        # Card type selector
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

        # Front
        tk.Label(form, text="Front (Question):", font=("Arial", 12)).pack(anchor=tk.W)
        front_text = tk.Text(form, height=3, font=("Arial", 12), wrap=tk.WORD)
        front_text.pack(fill=tk.X, pady=(0, 10))

        # Back / correct answer
        self._back_label = tk.Label(form, text="Back (Answer):", font=("Arial", 12))
        self._back_label.pack(anchor=tk.W)
        back_text = tk.Text(form, height=3, font=("Arial", 12), wrap=tk.WORD)
        back_text.pack(fill=tk.X, pady=(0, 10))

        # MC wrong choices area
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

        def _add_choice_entry(value=""):
            entry = tk.Entry(
                self._mc_entries_frame, font=("Arial", 12)
            )
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

        # Pre-fill if editing
        if editing:
            front_text.insert("1.0", card[C_FRONT])
            back_text.insert("1.0", card[C_BACK])
            type_var.set(card[C_TYPE])
            if card[C_TYPE] == "mc" and card[C_CHOICES]:
                wrong_choices = json.loads(card[C_CHOICES])
                for wc in wrong_choices:
                    _add_choice_entry(wc)
            _toggle_type()

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

            if editing:
                self.db.update_card(card[C_ID], front, back, card_type, choices)
            else:
                self.db.create_card(deck_id, front, back, card_type, choices)

            # Unbind mousewheel before leaving
            canvas.unbind_all("<MouseWheel>")
            self.show_deck(deck_id, deck_name)

        btn_frame = tk.Frame(self.container)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save", command=save, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(
            btn_frame,
            text="Cancel",
            command=lambda: (
                canvas.unbind_all("<MouseWheel>"),
                self.show_deck(deck_id, deck_name),
            ),
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
        self._study_deck_id = deck_id
        self._study_deck_name = deck_name
        self._study_index = 0
        self._study_showing_front = True
        self._study_scored = False

        tk.Label(
            self.container, text=f"Studying: {deck_name}", font=("Arial", 16)
        ).pack(pady=(20, 5))

        self._study_counter = tk.Label(
            self.container, text="", font=("Arial", 11)
        )
        self._study_counter.pack()

        self._study_score_label = tk.Label(
            self.container, text="", font=("Arial", 10), fg="gray"
        )
        self._study_score_label.pack()

        # Card display area
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

        # MC choices area (inside card frame)
        self._study_mc_frame = tk.Frame(self._study_card_frame)
        self._study_mc_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        # Feedback label
        self._study_feedback = tk.Label(
            self._study_card_frame, text="", font=("Arial", 11)
        )
        self._study_feedback.pack(pady=(0, 10))

        # Click to flip (only for free-response cards)
        self._study_card_frame.bind("<Button-1>", lambda e: self._flip_card())
        self._study_label.bind("<Button-1>", lambda e: self._flip_card())
        self._study_side_label.bind("<Button-1>", lambda e: self._flip_card())

        # Navigation row
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
            nav_frame,
            text="Back",
            command=lambda: self.show_deck(deck_id, deck_name),
            width=12,
        ).pack(side=tk.LEFT, padx=5)

        # Action row (Flip or Correct/Incorrect — for free-response only)
        self._action_frame = tk.Frame(self.container)
        self._action_frame.pack(pady=(0, 20))

        self._update_study_display()

    def _rebuild_action_buttons(self):
        for widget in self._action_frame.winfo_children():
            widget.destroy()

        card = self._study_cards[self._study_index]

        # MC cards use the choice buttons for scoring, no action row needed
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

        # Question text
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
            self._study_score_label.config(
                text=f"Score: {correct}/{total} ({pct}%)"
            )
        else:
            self._study_score_label.config(text="Score: no attempts yet")

        self._study_feedback.config(text="")

        # Build MC choices or action buttons
        for widget in self._study_mc_frame.winfo_children():
            widget.destroy()

        if is_mc and not self._study_scored:
            self._rebuild_mc_choices()
        elif is_mc and self._study_scored:
            pass  # feedback already shown

        self._rebuild_action_buttons()

    def _flip_card(self):
        card = self._study_cards[self._study_index]
        if card[C_TYPE] == "mc":
            return  # MC cards don't flip
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

        # Color the buttons
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
