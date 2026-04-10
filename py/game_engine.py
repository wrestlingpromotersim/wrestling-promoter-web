"""Minimal web-friendly game adapter.

This is a *starter* engine that proves the UI wiring with Pyodide.
Next step is porting your full sim logic into this state-machine style.

Design:
- No input()/print().
- Engine returns (screen_text, choices[]).
- UI calls engine.choose(choice_id).

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import random


@dataclass
class Choice:
    id: str
    label: str


@dataclass
class GameState:
    screen: str = ""
    menu: str = "home"
    week: int = 1
    cash: int = 15000
    rep: int = 50
    roster: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def new_game(seed: int | None = None) -> GameState:
    if seed is not None:
        random.seed(seed)
    st = GameState()
    st.roster = [
        "The Masked Man",
        "Loose Booty Warrior",
        "8-Trac Doom",
        "Bin Hamin",
        "The Professor",
        "The Strangler",
        "El Lenador",
        "THE Andrew Bello",
        "The Rasslin Redneck",
        "The Vet",
        "Mr. Wonderful",
    ]
    st.screen = (
        "Welcome to Wrestling Promoter Sim (Web MVP)\n\n"
        "This is the web UI proof-of-life.\n"
        "Next step: port your full sim rules into this engine.\n"
    )
    st.menu = "main"
    return st


def status_line(st: GameState) -> str:
    return f"Week {st.week} | Cash ${st.cash:,} | Rep {st.rep}/100 | Roster {len(st.roster)}"


def get_choices(st: GameState) -> list[Choice]:
    if st.menu == "home":
        return [Choice("new", "New Game")]
    if st.menu == "main":
        return [
            Choice("roster", "View roster"),
            Choice("autobook", "Auto-book a show"),
            Choice("next", "Next week"),
        ]
    if st.menu == "roster":
        return [Choice("back", "Back")]
    if st.menu == "show":
        return [Choice("back", "Back to menu")]
    return [Choice("home", "Home")]


def choose(st: GameState, choice_id: str) -> GameState:
    if choice_id == "new":
        return new_game()

    if st.menu == "main" and choice_id == "roster":
        st.menu = "roster"
        st.screen = "ROSTER\n" + "\n".join(f"- {n}" for n in st.roster)
        return st

    if st.menu == "main" and choice_id == "autobook":
        st.menu = "show"
        # toy simulation
        a, b = random.sample(st.roster, 2)
        rating = random.randint(35, 85)
        st.cash += random.randint(-500, 1800)
        st.rep = max(1, min(100, st.rep + (1 if rating >= 70 else 0)))
        st.screen = (
            f"AUTO-BOOKED SHOW\n{status_line(st)}\n\n"
            f"Main Event: {a} vs {b}\n"
            f"Rating: {rating}/100\n\n"
            "(Web MVP stub — full rules to be ported.)"
        )
        return st

    if st.menu == "main" and choice_id == "next":
        st.week += 1
        st.screen = f"Advanced to week {st.week}.\n{status_line(st)}"
        return st

    if choice_id in ("back", "home"):
        st.menu = "main"
        st.screen = f"MAIN MENU\n{status_line(st)}"
        return st

    # default
    st.screen = f"Unknown choice: {choice_id}\n{status_line(st)}"
    return st
