# Flashcards

A desktop flashcard application built with Python and Tkinter for creating, managing, and studying flashcard decks.

## Features

- **Deck Management** — Create, rename, and delete flashcard decks stored as portable JSON files.
- **Two Card Types** — Free-response cards (flip to reveal answer) and multiple-choice cards (auto-evaluated with shuffled options).
- **Tagging** — Apply tags at the deck and card level; study across decks by selecting one or more tags.
- **Score Tracking** — Persistent per-card correct/incorrect counts that survive across sessions.
- **Study Controls** — Navigate cards, reorder by random/original/lowest-scored, and edit cards mid-session.
- **Cross-Platform** — Runs on Linux, macOS, and Windows with platform-aware font and input handling.

## Getting Started

The application requires **Python 3** with Tkinter (included in most Python distributions).

```bash
python flashcards.py
```

Example decks are provided in `public_flashcards/`. User-created decks are saved to `private_flashcards/`.

## Architecture

The app uses a 3-layer MVC design, all contained in `flashcards.py`:

| Layer | Class | Responsibility |
|-------|-------|----------------|
| **Storage** | `DeckStorage`, `ScoreStore` | Read/write JSON deck files and score data |
| **Controller** | `AppController` | Business logic, validation, study session state |
| **View** | `TkView` | Tkinter GUI, event handling, screen navigation |

The view never contains business logic and the controller never references Tkinter, making it straightforward to swap in a different frontend.

## Data Schema

### Deck

Each deck is stored as a JSON file in `public_flashcards/` or `private_flashcards/`.

```json
{
  "name": "My Deck",
  "tags": ["history", "science"],
  "next_id": 4,
  "cards": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name of the deck |
| `tags` | string[] | Deck-level tags for categorization |
| `next_id` | integer | Auto-incrementing counter for generating unique card IDs |
| `cards` | Card[] | List of card objects |

### Card

```json
{
  "id": 1,
  "front": "What is the capital of France?",
  "back": "Paris",
  "card_type": "free",
  "choices": null,
  "tags": ["geography"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique card ID within the deck |
| `front` | string | Question or prompt shown on the front of the card |
| `back` | string | Answer shown on the back (also the correct answer for MC cards) |
| `card_type` | `"free"` \| `"mc"` | `"free"` for free-response, `"mc"` for multiple-choice |
| `choices` | string[] \| null | Wrong answer choices for MC cards; `null` for free-response |
| `tags` | string[] | Card-level tags for filtering |

### Scores

Scores are stored separately in `.local/scores.json` to keep deck files clean and shareable.

```json
{
  "public_flashcards/Fun Trivia Mix.json": {
    "1": [5, 2],
    "3": [3, 4]
  }
}
```

| Level | Key/Value | Description |
|-------|-----------|-------------|
| Top-level key | Deck file path (string) | Relative path using forward slashes |
| Card-level key | Card ID (string) | The card's local ID |
| Card-level value | `[correct, incorrect]` (int[]) | Cumulative correct and incorrect counts |
