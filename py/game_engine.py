"""Web state-machine engine for Wrestling Promoter Sim.

Contract with UI:
- No input()/print().
- UI calls:
    - new_game()
    - status_line(state)
    - get_screen(state)
    - get_choices(state) -> list[{id,label}]
    - choose(state, choice_id) -> updated state
- State must be serializable (to support localStorage).

This is a pragmatic port of `pro_wrestling_promoter_sim_fixed.py` into a
click/tap-driven wizard flow (manual booking).

Milestone goal: user can click through booking a 3-segment show and run it
without crashing (formatting/rules simplified).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import random
import re


# -------------------------
# Helpers
# -------------------------

def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s or "x"


def stable_id(prefix: str, name: str) -> str:
    return f"{prefix}:{slugify(name)}"


# -------------------------
# Core Models
# -------------------------


@dataclass
class Choice:
    id: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label}


@dataclass
class Wrestler:
    id: str
    name: str
    alignment: str  # Face/Heel
    popularity: int
    inring: int
    mic: int
    stamina: int = 100

    def star_power(self) -> float:
        return (self.popularity * 0.60) + (self.mic * 0.20) + (self.inring * 0.20)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "alignment": self.alignment,
            "popularity": self.popularity,
            "inring": self.inring,
            "mic": self.mic,
            "stamina": self.stamina,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Wrestler":
        return Wrestler(
            id=d["id"],
            name=d["name"],
            alignment=d.get("alignment", "Face"),
            popularity=int(d.get("popularity", 50)),
            inring=int(d.get("inring", 50)),
            mic=int(d.get("mic", 50)),
            stamina=int(d.get("stamina", 100)),
        )


@dataclass
class PromotionState:
    week: int = 1
    cash: int = 15000
    rep: int = 50

    roster: dict[str, Wrestler] = field(default_factory=dict)

    # Feuds: key "w:a|w:b" (sorted) -> heat 0-100
    feuds: dict[str, int] = field(default_factory=dict)

    champion_id: Optional[str] = None

    rng_seed: int = 1  # used for deterministic per-week simulation

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "cash": self.cash,
            "rep": self.rep,
            "roster": {k: w.to_dict() for k, w in self.roster.items()},
            "feuds": dict(self.feuds),
            "champion_id": self.champion_id,
            "rng_seed": self.rng_seed,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PromotionState":
        p = PromotionState()
        p.week = int(d.get("week", 1))
        p.cash = int(d.get("cash", 15000))
        p.rep = int(d.get("rep", 50))
        p.roster = {k: Wrestler.from_dict(wd) for k, wd in (d.get("roster") or {}).items()}
        p.feuds = {k: int(v) for k, v in (d.get("feuds") or {}).items()}
        p.champion_id = d.get("champion_id")
        p.rng_seed = int(d.get("rng_seed", 1))
        return p


# -------------------------
# Booking Draft
# -------------------------


MATCH_TYPES: list[str] = [
    "Standard",
    "Promo",
    "Hardcore",
    "Cage",
    "Championship",
    "Tag",
    "Iron Warfare",
    "Battle Royale",
]


CITY_OPTIONS: list[tuple[str, float]] = [
    ("Chicago", 1.05),
    ("New York", 1.10),
    ("Los Angeles", 1.08),
    ("Dallas", 1.00),
    ("Miami", 1.02),
    ("Las Vegas", 1.06),
]


def match_participant_target(match_type: str) -> Optional[int]:
    """If fixed size, return required number. If variable, return None."""
    if match_type in ("Standard", "Hardcore", "Cage", "Championship"):
        return 2
    if match_type == "Promo":
        return 1
    if match_type == "Tag":
        return 4
    if match_type == "Iron Warfare":
        return 6
    if match_type == "Battle Royale":
        return None
    return 2


@dataclass
class SegmentDraft:
    match_type: Optional[str] = None
    wrestler_ids: list[str] = field(default_factory=list)
    br_size: Optional[int] = None  # for battle royale

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_type": self.match_type,
            "wrestler_ids": list(self.wrestler_ids),
            "br_size": self.br_size,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SegmentDraft":
        s = SegmentDraft()
        s.match_type = d.get("match_type")
        s.wrestler_ids = list(d.get("wrestler_ids") or [])
        s.br_size = d.get("br_size")
        return s


@dataclass
class BookingDraft:
    city: Optional[str] = None
    city_mult: float = 1.0

    segments: list[SegmentDraft] = field(default_factory=lambda: [SegmentDraft(), SegmentDraft(), SegmentDraft()])
    segment_index: int = 0  # 0..2

    used_wrestler_ids: set[str] = field(default_factory=set)

    # selection flow state
    phase: str = "city"  # city | type | br_size | pick
    picked_ids: set[str] = field(default_factory=set)  # current segment selection toggles

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "city_mult": self.city_mult,
            "segments": [s.to_dict() for s in self.segments],
            "segment_index": self.segment_index,
            "used_wrestler_ids": sorted(self.used_wrestler_ids),
            "phase": self.phase,
            "picked_ids": sorted(self.picked_ids),
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BookingDraft":
        b = BookingDraft()
        b.city = d.get("city")
        b.city_mult = float(d.get("city_mult", 1.0))
        b.segments = [SegmentDraft.from_dict(x) for x in (d.get("segments") or [])]
        if len(b.segments) != 3:
            # normalize
            b.segments = (b.segments + [SegmentDraft(), SegmentDraft(), SegmentDraft()])[:3]
        b.segment_index = int(d.get("segment_index", 0))
        b.used_wrestler_ids = set(d.get("used_wrestler_ids") or [])
        b.phase = d.get("phase", "city")
        b.picked_ids = set(d.get("picked_ids") or [])
        return b


# -------------------------
# Game UI State
# -------------------------


@dataclass
class GameState:
    ui: str = "home"  # home | main | roster | booking | confirm | results
    promo: PromotionState = field(default_factory=PromotionState)

    booking: Optional[BookingDraft] = None

    last_results: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ui": self.ui,
            "promo": self.promo.to_dict(),
            "booking": None if self.booking is None else self.booking.to_dict(),
            "last_results": self.last_results,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "GameState":
        st = GameState()
        st.ui = d.get("ui", "home")
        st.promo = PromotionState.from_dict(d.get("promo") or {})
        st.booking = None if d.get("booking") is None else BookingDraft.from_dict(d.get("booking") or {})
        st.last_results = d.get("last_results", "")
        return st


# -------------------------
# Engine API
# -------------------------


def new_game(seed: int | None = None) -> GameState:
    rng_seed = 1 if seed is None else int(seed)

    # Small but flavorful starter roster (ported spirit; stats simplified)
    names = [
        ("The Masked Man", "Face"),
        ("Loose Booty Warrior", "Face"),
        ("8-Trac Doom", "Heel"),
        ("Bin Hamin", "Heel"),
        ("The Professor", "Face"),
        ("The Strangler", "Heel"),
        ("El Lenador", "Face"),
        ("THE Andrew Bello", "Heel"),
        ("The Rasslin Redneck", "Face"),
        ("The Vet", "Face"),
        ("Mr. Wonderful", "Heel"),
        ("Neon Nightmare", "Heel"),
        ("Captain Cornfed", "Face"),
        ("Violet Vortex", "Face"),
        ("Graveljaw", "Heel"),
        ("Silver Saint", "Face"),
    ]

    rng = random.Random(rng_seed)
    roster: dict[str, Wrestler] = {}
    for nm, align in names:
        wid = stable_id("w", nm)
        roster[wid] = Wrestler(
            id=wid,
            name=nm,
            alignment=align,
            popularity=rng.randint(35, 75),
            inring=rng.randint(35, 80),
            mic=rng.randint(30, 80),
            stamina=rng.randint(70, 100),
        )

    promo = PromotionState(
        week=1,
        cash=15000,
        rep=50,
        roster=roster,
        feuds={},
        champion_id=None,
        rng_seed=rng_seed,
    )

    st = GameState(ui="main", promo=promo)
    return st


def status_line(st: GameState) -> str:
    champ = "None"
    if st.promo.champion_id and st.promo.champion_id in st.promo.roster:
        champ = st.promo.roster[st.promo.champion_id].name
    return f"Week {st.promo.week} | Cash ${st.promo.cash:,} | Rep {st.promo.rep}/100 | Champion: {champ}"


def get_screen(st: GameState) -> str:
    return _render_screen(st)


def get_choices(st: GameState) -> list[dict[str, str]]:
    return [c.to_dict() for c in _choices(st)]


def choose(st: GameState, choice_id: str) -> GameState:
    # Defensive copy is not required for Pyodide UI; mutate in-place.

    if st.ui == "home":
        if choice_id == "new":
            return new_game()
        return st

    if st.ui == "main":
        if choice_id == "main:roster":
            st.ui = "roster"
            return st
        if choice_id == "main:book":
            st.booking = BookingDraft()
            st.ui = "booking"
            return st
        if choice_id == "main:next":
            st.promo.week += 1
            # tiny passive drift
            st.promo.rep = clamp(st.promo.rep + 0, 1, 100)
            return st
        return st

    if st.ui == "roster":
        if choice_id == "back:main":
            st.ui = "main"
            return st
        return st

    if st.ui == "booking":
        return _choose_booking(st, choice_id)

    if st.ui == "confirm":
        if choice_id == "confirm:run":
            _run_show(st)
            st.ui = "results"
            return st
        if choice_id == "confirm:cancel":
            st.booking = None
            st.ui = "main"
            return st
        if choice_id.startswith("confirm:edit:"):
            # edit a segment
            try:
                idx = int(choice_id.split(":")[-1])
            except Exception:
                return st
            if not st.booking:
                return st
            idx = clamp(idx, 1, 3) - 1
            st.booking.segment_index = idx
            st.booking.phase = "type"
            st.booking.picked_ids = set()
            st.ui = "booking"
            return st
        return st

    if st.ui == "results":
        if choice_id == "results:main":
            st.ui = "main"
            st.booking = None
            return st
        return st

    return st


# -------------------------
# Rendering
# -------------------------


def _render_screen(st: GameState) -> str:
    if st.ui == "home":
        return "Wrestling Promoter Sim (Web)\n\nTap New Game to begin."

    if st.ui == "main":
        return "MAIN MENU\n" + status_line(st) + "\n\nWhat would you like to do?"

    if st.ui == "roster":
        lines = ["ROSTER", status_line(st), ""]
        # show champ first if exists
        roster = list(st.promo.roster.values())
        roster.sort(key=lambda w: (0 if w.id == st.promo.champion_id else 1, -w.popularity, w.name))
        for w in roster:
            tag = " (C)" if w.id == st.promo.champion_id else ""
            lines.append(f"- {w.name}{tag} | {w.alignment} | Pop {w.popularity} | Ring {w.inring} | Mic {w.mic}")
        return "\n".join(lines)

    if st.ui == "booking":
        return _render_booking(st)

    if st.ui == "confirm":
        assert st.booking is not None
        b = st.booking
        lines = [
            "CONFIRM SHOW",
            status_line(st),
            "",
            f"City: {b.city} (x{b.city_mult:.2f})",
            "",
        ]
        for i, seg in enumerate(b.segments, start=1):
            mt = seg.match_type or "(unset)"
            names = [st.promo.roster[wid].name for wid in seg.wrestler_ids if wid in st.promo.roster]
            lines.append(f"Segment {i}: {mt}")
            if names:
                lines.append("  " + ", ".join(names))
            else:
                lines.append("  (no wrestlers selected)")
        lines.append("")
        lines.append("Run the show?")
        return "\n".join(lines)

    if st.ui == "results":
        return "SHOW RESULTS\n" + status_line(st) + "\n\n" + (st.last_results or "(no results)")

    return status_line(st)


def _choices(st: GameState) -> list[Choice]:
    if st.ui == "home":
        return [Choice("new", "New Game")]

    if st.ui == "main":
        return [
            Choice("main:book", "Book a show (manual)"),
            Choice("main:roster", "View roster"),
            Choice("main:next", "Advance week"),
        ]

    if st.ui == "roster":
        return [Choice("back:main", "Back")]

    if st.ui == "booking":
        return _choices_booking(st)

    if st.ui == "confirm":
        return [
            Choice("confirm:run", "Run show"),
            Choice("confirm:edit:1", "Edit segment 1"),
            Choice("confirm:edit:2", "Edit segment 2"),
            Choice("confirm:edit:3", "Edit segment 3"),
            Choice("confirm:cancel", "Cancel"),
        ]

    if st.ui == "results":
        return [Choice("results:main", "Back to main menu")]

    return [Choice("main", "Main")]


# -------------------------
# Booking Flow
# -------------------------


def _render_booking(st: GameState) -> str:
    assert st.booking is not None
    b = st.booking
    seg_no = b.segment_index + 1

    if b.phase == "city":
        return "BOOK A SHOW\n" + status_line(st) + "\n\nPick a city:" \
            + "\n" + "\n".join(f"- {nm} (x{mult:.2f})" for nm, mult in CITY_OPTIONS)

    if b.phase == "type":
        cur = b.segments[b.segment_index]
        mt = cur.match_type or "(not set)"
        return (
            "BOOK A SHOW\n" + status_line(st)
            + f"\n\nSegment {seg_no}/3\n"
            + f"Current type: {mt}\n\nPick a segment type:"
        )

    if b.phase == "br_size":
        return (
            "BOOK A SHOW\n" + status_line(st)
            + f"\n\nSegment {seg_no}/3\nBattle Royale size:"\
            + "\n\nPick how many wrestlers will enter."
        )

    if b.phase == "pick":
        seg = b.segments[b.segment_index]
        mt = seg.match_type or "(not set)"
        target = match_participant_target(mt) if mt else None
        already = len(b.picked_ids)
        prompt = "Pick wrestlers" if target is None else f"Pick {target} wrestler(s)"

        used_note = "Wrestlers used in earlier segments are hidden." if b.used_wrestler_ids else ""
        return (
            "BOOK A SHOW\n" + status_line(st)
            + f"\n\nSegment {seg_no}/3 - {mt}\n{prompt} (selected {already})\n"
            + (used_note + "\n" if used_note else "")
            + "\nTap names to toggle selection, then tap Done."
        )

    return "BOOK A SHOW\n" + status_line(st)


def _choices_booking(st: GameState) -> list[Choice]:
    assert st.booking is not None
    b = st.booking

    if b.phase == "city":
        ch: list[Choice] = []
        for nm, mult in CITY_OPTIONS:
            ch.append(Choice(f"city:{slugify(nm)}", f"{nm} (x{mult:.2f})"))
        ch.append(Choice("booking:cancel", "Cancel"))
        return ch

    if b.phase == "type":
        ch = [Choice(f"type:{slugify(mt)}", mt) for mt in MATCH_TYPES]
        ch.append(Choice("booking:back", "Back"))
        ch.append(Choice("booking:cancel", "Cancel"))
        return ch

    if b.phase == "br_size":
        ch = [
            Choice("brsize:6", "6 wrestlers"),
            Choice("brsize:8", "8 wrestlers"),
            Choice("brsize:10", "10 wrestlers"),
        ]
        ch.append(Choice("booking:back", "Back"))
        ch.append(Choice("booking:cancel", "Cancel"))
        return ch

    if b.phase == "pick":
        seg = b.segments[b.segment_index]
        mt = seg.match_type or "Standard"
        target = match_participant_target(mt)

        available = [w for w in st.promo.roster.values() if w.id not in b.used_wrestler_ids]
        available.sort(key=lambda w: (-w.popularity, w.name))

        ch = []
        for w in available:
            picked = w.id in b.picked_ids
            box = "[x]" if picked else "[ ]"
            ch.append(Choice(f"pick:{w.id}", f"{box} {w.name}"))

        # Done button
        if target is None:
            ok = len(b.picked_ids) >= 2
        else:
            ok = len(b.picked_ids) == target
        done_label = "Done" if ok else "Done (select more)"
        ch.insert(0, Choice("pick:done", done_label))

        ch.append(Choice("booking:back", "Back"))
        ch.append(Choice("booking:cancel", "Cancel"))
        return ch

    return [Choice("booking:cancel", "Cancel")]


def _choose_booking(st: GameState, choice_id: str) -> GameState:
    assert st.booking is not None
    b = st.booking

    if choice_id == "booking:cancel":
        st.booking = None
        st.ui = "main"
        return st

    # Universal back handling in booking: step back within segment flow
    if choice_id == "booking:back":
        if b.phase == "pick":
            # go back to type selection for this segment
            b.phase = "type"
            b.picked_ids = set()
            return st
        if b.phase == "br_size":
            b.phase = "type"
            return st
        if b.phase == "type":
            # if we're on segment >1, go back a segment's pick summary by editing previous
            if b.segment_index > 0:
                b.segment_index -= 1
                # restoring previous segment's picks is out-of-scope; let them re-pick
                # but do restore used_wrestler_ids from earlier segments
                _recompute_used(b)
                b.phase = "type"
                b.picked_ids = set()
                return st
            # else go back to city
            b.phase = "city"
            return st
        if b.phase == "city":
            st.booking = None
            st.ui = "main"
            return st

    if b.phase == "city" and choice_id.startswith("city:"):
        slug = choice_id.split(":", 1)[1]
        for nm, mult in CITY_OPTIONS:
            if slugify(nm) == slug:
                b.city = nm
                b.city_mult = float(mult)
                b.phase = "type"
                b.segment_index = 0
                b.picked_ids = set()
                _recompute_used(b)
                return st
        return st

    if b.phase == "type" and choice_id.startswith("type:"):
        mt_slug = choice_id.split(":", 1)[1]
        mt = None
        for cand in MATCH_TYPES:
            if slugify(cand) == mt_slug:
                mt = cand
                break
        if mt is None:
            return st

        seg = b.segments[b.segment_index]
        # editing segment: remove its wrestlers from used before re-picking
        for wid in seg.wrestler_ids:
            b.used_wrestler_ids.discard(wid)
        seg.match_type = mt
        seg.wrestler_ids = []
        seg.br_size = None
        b.picked_ids = set()

        if mt == "Battle Royale":
            b.phase = "br_size"
        else:
            b.phase = "pick"
        return st

    if b.phase == "br_size" and choice_id.startswith("brsize:"):
        try:
            size = int(choice_id.split(":", 1)[1])
        except Exception:
            return st
        seg = b.segments[b.segment_index]
        seg.br_size = clamp(size, 4, 20)
        b.phase = "pick"
        b.picked_ids = set()
        return st

    if b.phase == "pick":
        seg = b.segments[b.segment_index]
        mt = seg.match_type or "Standard"
        target = match_participant_target(mt)

        if choice_id == "pick:done":
            # validate
            if target is None:
                required = seg.br_size or 6
                if len(b.picked_ids) != required:
                    return st
            else:
                if len(b.picked_ids) != target:
                    return st

            seg.wrestler_ids = list(b.picked_ids)
            # update used set
            b.used_wrestler_ids.update(seg.wrestler_ids)
            b.picked_ids = set()

            # next segment or confirm
            if b.segment_index < 2:
                b.segment_index += 1
                b.phase = "type"
                return st

            st.ui = "confirm"
            return st

        if choice_id.startswith("pick:"):
            wid = choice_id.split(":", 1)[1]
            # prevent picking used wrestlers (not displayed, but safe)
            if wid in b.used_wrestler_ids:
                return st
            # for battle royale, size is fixed once chosen
            if mt == "Battle Royale":
                required = seg.br_size or 6
            else:
                required = target

            if wid in b.picked_ids:
                b.picked_ids.remove(wid)
                return st

            # enforce max selections
            if required is not None and len(b.picked_ids) >= required:
                return st

            if wid in st.promo.roster:
                b.picked_ids.add(wid)
            return st

    return st


def _recompute_used(b: BookingDraft) -> None:
    used: set[str] = set()
    for i in range(3):
        if i < b.segment_index:
            used.update(b.segments[i].wrestler_ids)
    b.used_wrestler_ids = used


# -------------------------
# Simulation
# -------------------------


def _feud_key(a: str, b: str) -> str:
    x, y = sorted([a, b])
    return f"{x}|{y}"


def _run_show(st: GameState) -> None:
    assert st.booking is not None
    b = st.booking

    rng_base = st.promo.rng_seed + st.promo.week * 1000

    # simple economics
    base_attendance = 350
    attendance = base_attendance + int(st.promo.rep * 12)

    # show summary
    results_lines: list[str] = []
    results_lines.append(f"City: {b.city} (x{b.city_mult:.2f})")

    total_star = 0.0
    total_rating = 0

    # segment loop
    for i, seg in enumerate(b.segments, start=1):
        mt = seg.match_type or "Standard"
        roster = st.promo.roster
        ws = [roster[wid] for wid in seg.wrestler_ids if wid in roster]
        seg_rng = random.Random(rng_base + i * 17)

        # compute baseline
        star = sum(w.star_power() for w in ws) / max(1, len(ws))
        type_mod = {
            "Promo": 0.92,
            "Standard": 1.00,
            "Hardcore": 1.03,
            "Cage": 1.02,
            "Championship": 1.05,
            "Tag": 1.01,
            "Iron Warfare": 1.06,
            "Battle Royale": 1.04,
        }.get(mt, 1.0)

        noise = seg_rng.randint(-8, 8)
        rating = int(clamp(int(star * type_mod) + noise, 20, 100))

        # pick a "winner" for flavor
        winner = None
        if ws:
            weights = [max(1.0, (w.popularity * 0.5 + w.inring * 0.5)) for w in ws]
            winner = seg_rng.choices(ws, weights=weights, k=1)[0]

        # update champion
        if mt == "Championship" and winner is not None:
            st.promo.champion_id = winner.id

        # feud heat if 1v1
        if len(ws) == 2 and mt != "Promo":
            k = _feud_key(ws[0].id, ws[1].id)
            st.promo.feuds[k] = clamp(st.promo.feuds.get(k, 0) + seg_rng.randint(6, 14), 0, 100)

        # attendance bump from star power
        attendance += int(star * 1.2)

        total_star += star
        total_rating += rating

        names = ", ".join(w.name for w in ws) if ws else "(n/a)"
        win_txt = f" Winner: {winner.name}." if winner is not None else ""
        results_lines.append(f"\nSegment {i}: {mt}")
        results_lines.append(f"  Participants: {names}")
        results_lines.append(f"  Rating: {rating}/100.{win_txt}")

    show_rating = int(total_rating / 3) if total_rating else 0

    attendance = int(attendance * b.city_mult)
    ticket_price = 18 + int(st.promo.rep / 10)
    gate = attendance * ticket_price

    # lightweight weekly cost
    payroll = 0
    for w in st.promo.roster.values():
        payroll += 200  # simplified

    net = gate - payroll

    # rep change
    if show_rating >= 75:
        rep_delta = 2
    elif show_rating >= 60:
        rep_delta = 1
    elif show_rating >= 45:
        rep_delta = 0
    else:
        rep_delta = -1

    st.promo.cash += int(net)
    st.promo.rep = clamp(st.promo.rep + rep_delta, 1, 100)

    results_lines.append("\n---")
    results_lines.append(f"Attendance: {attendance}")
    results_lines.append(f"Gate: ${gate:,}")
    results_lines.append(f"Payroll: -${payroll:,}")
    results_lines.append(f"Net: ${net:,}")
    results_lines.append(f"Overall show rating: {show_rating}/100")

    if st.promo.champion_id and st.promo.champion_id in st.promo.roster:
        results_lines.append(f"Champion: {st.promo.roster[st.promo.champion_id].name}")

    st.last_results = "\n".join(results_lines)

    # advance week after running the show
    st.promo.week += 1

    # clear booking
    st.booking = None
