from enum import Enum
from typing import Callable
from kitty.fast_data_types import Screen, add_timer, get_boss, get_options
from kitty.tab_bar import (
    DrawData, TabBarData, ExtraData, TabAccessor, as_rgb
)
from kitty.utils import color_as_int
import os
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Colors — pulled from kitty.conf color definitions
# ---------------------------------------------------------------------------
opts = get_options()

BG = as_rgb(color_as_int(opts.color19))       # Cell background (dark bg: #24283b)
FG = as_rgb(color_as_int(opts.color7))         # Cell text (light grey: #a9b1d6)
COLOR_1 = as_rgb(color_as_int(opts.color3))    # Inactive tab accent (yellow: #e0af68)
COLOR_2 = as_rgb(color_as_int(opts.color5))    # Active tab accent (purple: #bb9af7)
COLOR_3 = as_rgb(color_as_int(opts.color4))    # Right-side widgets — time & session (blue: #7aa2f7)
COLOR_4 = as_rgb(color_as_int(opts.color4))    # Left-side widget — cwd (blue: #7aa2f7)

# How often (seconds) the tab bar redraws itself (for the clock widget)
REFRESH_TIME = 15

# Max number of path components shown before truncating with ".."
MAX_LENGTH_PATH = 3

# Nerd Font icons for each widget
folder_icon = " "
time_icon = "󰥔 "
session_icon = " "

# ---------------------------------------------------------------------------
# Cell — a single drawable block in the tab bar
# ---------------------------------------------------------------------------
# Each Cell renders as:  [border_left][icon][separator text][border_right]
# - icon section: colored background with the icon character
# - text section: darker background with the label text
# - borders: drawn with the accent color on a transparent background
#
# When there's not enough space, text_fn can return:
#   None  -> cell is hidden entirely
#   ""    -> icon-only mode (no text section)
#   "..." -> normal mode with text
# ---------------------------------------------------------------------------
class Cell:
    def __init__(
        self,
        icon: str,
        text_fn: Callable[[int, TabBarData], str | None],
        tab: TabBarData = None,
        bg: str = BG,
        fg: str = FG,
        color: int = COLOR_1,
        separator: str = "",
        border: tuple[str, str] = ("",""),
    ) -> None:

        self.tab: TabBarData = tab
        self.fg: str = fg
        self.bg: str = bg
        self.color: int = color
        self.icon: str = icon
        self.text_fn: Callable[[int, TabBarData], str | None] = text_fn
        self.border: tuple[str, str] = border
        self.separator: str = separator
        self.text_length_overhead = len(self.border[0] + self.border[1] + self.separator + self.icon) + 1

    def draw(self, screen: Screen, max_size: int) -> None:
        text = self.text_fn(max_size - self.text_length_overhead, self.tab)

        if text is None:
            return

        screen.cursor.dim = False
        screen.cursor.bold = False
        screen.cursor.italic = False

        # Left border (accent color on transparent bg)
        screen.cursor.bg = 0
        screen.cursor.fg = self.color
        screen.draw(self.border[0])

        # Icon (dark text on accent-colored bg, bold)
        screen.cursor.bg = self.color
        screen.cursor.fg = self.bg
        screen.cursor.bold = True
        screen.draw(self.icon)
        screen.cursor.bold = False

        if text == "":
            # Icon-only mode — just close with right border
            screen.cursor.bg = 0
            screen.cursor.fg = self.color
            screen.draw(self.border[1])
        else:
            # Separator between icon and text
            screen.cursor.bg = self.bg
            screen.cursor.fg = self.color
            screen.draw(self.separator)

            # Text label on dark background
            screen.cursor.fg = self.fg
            screen.draw(f" {text}")

            # Right border
            screen.cursor.fg = self.bg
            screen.cursor.bg = 0
            screen.draw(self.border[1])

    def length(self, max_size: int) -> int:
        """Calculate how many columns this cell will occupy."""
        text = self.text_fn(max_size - self.text_length_overhead, self.tab)

        if text is None:
            return 0
        elif text ==  "":
            return len(self.icon + self.border[0] + self.border[1])
        else:
            return len(text) + self.text_length_overhead

# ---------------------------------------------------------------------------
# Text provider functions
# ---------------------------------------------------------------------------
# Each returns a string for the cell label, "" for icon-only, or None to hide.

def get_wd(max_size: int, tab: TabBarData):
    """Left widget: working directory of the active pane, compressed if deep."""
    accessor = TabAccessor(tab.tab_id)

    wd = Path(accessor.active_wd)
    home = Path(os.getenv('HOME'))

    # Replace $HOME prefix with ~
    if wd.is_relative_to(home):
        wd = wd.relative_to(home)

        if wd == home:
            wd = Path("~")
        else:
            wd = Path("~") / wd

    # If path is deeper than MAX_LENGTH_PATH, truncate middle segments with ".."
    parts = list(wd.parts)
    compressed = False
    if len(parts) > MAX_LENGTH_PATH:
        compressed = True
        parts = [parts[0], ".."] + parts[-MAX_LENGTH_PATH:]

    # Progressively drop leading segments until it fits max_size
    parts_cnt = 1 + compressed
    while parts_cnt != len(parts):
        wd = "/".join(parts[0:1+compressed] + parts[parts_cnt:])
        if len(wd) <= max_size:
            return wd
        parts_cnt += 1

    # Last resort: just the final directory name
    if len(parts[-1]) <= max_size:
        return parts[-1]

    return None

def get_time(max_size: int, tab: TabBarData) -> str | None:
    """Right widget: current time in HH:MM format."""
    if max_size < 5:
        return None
    else:
        return datetime.datetime.now().strftime("%H:%M")

def get_tab(max_size: int, tab: TabBarData) -> str | None:
    """Center widget: tab label — uses a custom title (prefixed with #) or the running process name."""
    accessor = TabAccessor(tab.tab_id)

    if tab.title[0] == "#":
        text = tab.title[1:]
    else:
        text = str(accessor.active_exe)

    # Not enough room for the text — show icon only
    if max_size <= len(text):
        return ""
    else:
        return text

def get_session(max_size: int, tab: TabBarData) -> str | None:
    """Right widget: kitty session name (shows 'none' if not in a named session)."""
    text = tab.session_name
    if text == "":
        text = "none"
    if len(text) <= max_size:
        return text
    elif max_size >= 3:
        return text[:3]
    else:
        return None

def get_tab_cell(tab: TabBarData) -> Cell:
    """Create a Cell for a tab — active tabs get COLOR_2 (purple), inactive get COLOR_1 (yellow)."""
    color = COLOR_2 if tab.is_active else COLOR_1
    return Cell(str(tab.tab_id), get_tab, tab, color=color)


# ---------------------------------------------------------------------------
# Timer — periodically redraws the tab bar so the clock stays updated
# ---------------------------------------------------------------------------
def redraw_tab_bar(_):
    tm = get_boss().active_tab_manager
    if tm is not None:
        tm.mark_tab_bar_dirty()

timer_id = None

# ---------------------------------------------------------------------------
# Center layout — the tab cells in the middle of the bar
# ---------------------------------------------------------------------------
# Accumulated per draw_tab() call, then rendered all at once when is_last=True.
center: list[Cell] = []
active_index = 1

class CenterStrategy(Enum):
    """How to render the center tabs depending on available space."""
    EXPAND_ALL = 0              # All tabs show icon + text
    EXPAND_ACTIVE = 1           # Active tab has text, others icon-only
    NO_EXPAND = 2               # All tabs icon-only
    SHOW_ACTIVE = 3             # Only the active tab is visible (with text)
    SHOW_ACTIVE_NO_EXPAND = 4   # Only the active tab is visible (icon-only)

def center_strategy(screen: Screen) -> tuple[CenterStrategy, int]:
    """Pick the best rendering strategy that fits the screen width."""
    n_cells = len(center)

    # Try: all tabs fully expanded
    length = n_cells - 1 + sum(map(lambda x: x.length(screen.columns), center))
    if length < screen.columns:
        return CenterStrategy.EXPAND_ALL, length

    # Try: only active tab expanded, rest icon-only
    length = n_cells - 1
    for index, cell in enumerate(center):
        if index == active_index:
            length += cell.length(screen.columns)
        else:
            length += cell.length(0)
    if length < screen.columns:
        return CenterStrategy.EXPAND_ACTIVE, length

    # Try: all tabs icon-only
    length = n_cells - 1+ sum(map(lambda x: x.length(0), center))
    if length < screen.columns:
        return CenterStrategy.NO_EXPAND, length

    # Try: only active tab visible (with text)
    length = center[active_index].length(screen.columns)
    if length < screen.columns:
        return CenterStrategy.SHOW_ACTIVE, length

    # Fallback: only active tab visible (icon-only)
    return CenterStrategy.SHOW_ACTIVE_NO_EXPAND, center[active_index].length(0)

def draw_center(screen: Screen, strategy: CenterStrategy):
    """Render the center tab cells according to the chosen strategy."""
    match strategy:
        case CenterStrategy.EXPAND_ALL:
            for idx, cell in enumerate(center):
                if idx != 0:
                    screen.draw(" ")
                cell.draw(screen, screen.columns)

        case CenterStrategy.EXPAND_ACTIVE:
            for idx, cell in enumerate(center):
                if idx != 0:
                    screen.draw(" ")
                cell.draw(screen, screen.columns * (idx == active_index))
        case CenterStrategy.NO_EXPAND:
            for idx, cell in enumerate(center):
                if idx != 0:
                    screen.draw(" ")
                cell.draw(screen, 0)
        case CenterStrategy.SHOW_ACTIVE:
            center[active_index].draw(screen, screen.columns)
        case CenterStrategy.SHOW_ACTIVE_NO_EXPAND:
            center[active_index].draw(screen, 0)

# ---------------------------------------------------------------------------
# Section drawers — left, center, and right regions of the tab bar
# ---------------------------------------------------------------------------

def draw_left(screen: Screen, max_length: int):
    """Draw the left section: working directory of the active tab."""
    cell = Cell(folder_icon, get_wd, center[active_index].tab, color=COLOR_4)
    cell.draw(screen, max_length)

def draw_right(screen: Screen):
    """Draw the right section: session name and clock."""
    max_size = screen.columns - screen.cursor.x
    time_cell = Cell(time_icon, get_time, color=COLOR_3)
    session_cell = Cell(session_icon, get_session, center[active_index].tab, color=COLOR_3)

    # Calculate how much space the right widgets need
    total_length = time_cell.length(max_size)
    session_length = session_cell.length(max_size - total_length - 1)

    if session_length != 0:
        total_length += 1 + session_length

    # Pad with spaces to right-align
    offset_length = max_size - total_length
    screen.draw(" " * offset_length)

    if session_length != 0:
        session_cell.draw(screen, session_length)
        screen.draw(" ")

    time_cell.draw(screen, max_size)

# ---------------------------------------------------------------------------
# draw_tab — kitty's entry point (called once per tab)
# ---------------------------------------------------------------------------
# Kitty calls this for each tab in order. We accumulate tab cells, then on
# the last tab (is_last=True) we render the entire bar at once so we can
# center the tabs and place left/right widgets.
# ---------------------------------------------------------------------------
def draw_tab(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    before: int,
    max_title_length: int,
    index: int,
    is_last: bool,
    extra_data: ExtraData,
) -> int:
    global center
    global timer_id
    global active_index

    # Start the refresh timer on first call (keeps the clock updated)
    if timer_id is None:
        timer_id = add_timer(redraw_tab_bar, REFRESH_TIME, True)
    if tab.is_active:
        active_index = index - 1

    center.append(get_tab_cell(tab))

    # On the last tab, render the full bar layout:
    #   [left: cwd] ... [center: tabs] ... [right: session + time]
    if is_last:
        strategy, length = center_strategy(screen)

        center_start_position = (screen.columns - length) // 2
        draw_left(screen, center_start_position - 1)

        screen.cursor.x = center_start_position
        draw_center(screen, strategy)
        screen.draw(" ")

        draw_right(screen)
        center = []
    return screen.cursor.x
