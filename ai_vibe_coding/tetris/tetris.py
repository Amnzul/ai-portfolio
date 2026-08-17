#!/usr/bin/env python3
"""Terminal Tetris - A fully functional Tetris game using Python curses."""

import curses
import random
import time

# Board dimensions
BOARD_WIDTH = 10
BOARD_HEIGHT = 20

# Tetromino shapes (each rotation is a list of (row, col) offsets from pivot)
TETROMINOES = {
    'I': [
        [(0,0),(0,1),(0,2),(0,3)],
        [(0,2),(1,2),(2,2),(3,2)],
        [(2,0),(2,1),(2,2),(2,3)],
        [(0,1),(1,1),(2,1),(3,1)],
    ],
    'O': [
        [(0,0),(0,1),(1,0),(1,1)],
        [(0,0),(0,1),(1,0),(1,1)],
        [(0,0),(0,1),(1,0),(1,1)],
        [(0,0),(0,1),(1,0),(1,1)],
    ],
    'T': [
        [(0,1),(1,0),(1,1),(1,2)],
        [(0,1),(1,1),(1,2),(2,1)],
        [(1,0),(1,1),(1,2),(2,1)],
        [(0,1),(1,0),(1,1),(2,1)],
    ],
    'S': [
        [(0,1),(0,2),(1,0),(1,1)],
        [(0,1),(1,1),(1,2),(2,2)],
        [(1,1),(1,2),(2,0),(2,1)],
        [(0,0),(1,0),(1,1),(2,1)],
    ],
    'Z': [
        [(0,0),(0,1),(1,1),(1,2)],
        [(0,2),(1,1),(1,2),(2,1)],
        [(1,0),(1,1),(2,1),(2,2)],
        [(0,1),(1,0),(1,1),(2,0)],
    ],
    'J': [
        [(0,0),(1,0),(1,1),(1,2)],
        [(0,1),(0,2),(1,1),(2,1)],
        [(1,0),(1,1),(1,2),(2,2)],
        [(0,1),(1,1),(2,0),(2,1)],
    ],
    'L': [
        [(0,2),(1,0),(1,1),(1,2)],
        [(0,1),(1,1),(2,1),(2,2)],
        [(1,0),(1,1),(1,2),(2,0)],
        [(0,0),(0,1),(1,1),(2,1)],
    ],
}

PIECE_ORDER = ['I', 'O', 'T', 'S', 'Z', 'J', 'L']

# Color pair indices (1-7 for pieces, 8 for border/UI)
PIECE_COLORS = {
    'I': 1,  # Cyan
    'O': 2,  # Yellow
    'T': 3,  # Magenta
    'S': 4,  # Green
    'Z': 5,  # Red
    'J': 6,  # Blue
    'L': 7,  # White/Orange
}

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)     # I
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)   # O
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_MAGENTA)  # T
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_GREEN)    # S
    curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_RED)      # Z
    curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)     # J
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)    # L
    curses.init_pair(8, curses.COLOR_WHITE, -1)                    # UI text
    curses.init_pair(9, curses.COLOR_CYAN, -1)                     # Title
    curses.init_pair(10, curses.COLOR_BLACK, curses.COLOR_WHITE)   # Ghost piece


class TetrisGame:
    def __init__(self):
        self.board = [[0] * BOARD_WIDTH for _ in range(BOARD_HEIGHT)]
        self.score = 0
        self.level = 1
        self.lines = 0
        self.game_over = False
        self.paused = False
        self.current_piece = None
        self.current_type = None
        self.current_rot = 0
        self.current_pos = [0, 0]
        self.next_type = random.choice(PIECE_ORDER)
        self.spawn_piece()

    def spawn_piece(self):
        self.current_type = self.next_type
        self.next_type = random.choice(PIECE_ORDER)
        self.current_rot = 0
        self.current_piece = TETROMINOES[self.current_type][0]
        # Place piece so its topmost cell is at row 0
        min_row = min(r for (r, c) in self.current_piece)
        self.current_pos = [-min_row, BOARD_WIDTH // 2 - 2]
        if not self.is_valid(self.current_piece, self.current_pos):
            self.game_over = True

    def is_valid(self, piece, pos):
        for (r, c) in piece:
            nr, nc = pos[0] + r, pos[1] + c
            # Cells above the board are allowed (piece entering from top)
            if nr >= BOARD_HEIGHT or nc < 0 or nc >= BOARD_WIDTH:
                return False
            if nr >= 0 and self.board[nr][nc] != 0:
                return False
        return True

    def lock_piece(self):
        color = PIECE_COLORS[self.current_type]
        for (r, c) in self.current_piece:
            nr, nc = self.current_pos[0] + r, self.current_pos[1] + c
            if 0 <= nr < BOARD_HEIGHT and 0 <= nc < BOARD_WIDTH:
                self.board[nr][nc] = color
            elif nr < 0:
                # Piece locked above visible board — game over
                self.game_over = True
        self.clear_lines()
        self.spawn_piece()

    def clear_lines(self):
        full_lines = [r for r in range(BOARD_HEIGHT)
                      if sum(1 for c in self.board[r] if c != 0) == BOARD_WIDTH]
        count = len(full_lines)
        if count == 0:
            return
        for r in sorted(full_lines, reverse=True):
            del self.board[r]
            self.board.insert(0, [0] * BOARD_WIDTH)
        self.lines += count
        points = [0, 100, 300, 500, 800][min(count, 4)] * self.level
        self.score += points
        self.level = self.lines // 10 + 1

    def move(self, dr, dc):
        new_pos = [self.current_pos[0] + dr, self.current_pos[1] + dc]
        if self.is_valid(self.current_piece, new_pos):
            self.current_pos = new_pos
            return True
        return False

    def rotate(self):
        new_rot = (self.current_rot + 1) % 4
        new_piece = TETROMINOES[self.current_type][new_rot]
        if self.is_valid(new_piece, self.current_pos):
            self.current_rot = new_rot
            self.current_piece = new_piece
        else:
            # Wall kick: try shifting left or right
            for dc in [-1, 1, -2, 2]:
                shifted = [self.current_pos[0], self.current_pos[1] + dc]
                if self.is_valid(new_piece, shifted):
                    self.current_rot = new_rot
                    self.current_piece = new_piece
                    self.current_pos = shifted
                    break

    def hard_drop(self):
        while self.move(1, 0):
            pass
        self.lock_piece()

    def fall(self):
        if not self.move(1, 0):
            self.lock_piece()

    def get_ghost_pos(self):
        pos = list(self.current_pos)
        while self.is_valid(self.current_piece, [pos[0] + 1, pos[1]]):
            pos[0] += 1
        return pos

    def get_fall_interval(self):
        # Faster at higher levels
        return max(0.05, 0.5 - (self.level - 1) * 0.045)


def draw_box(win, y, x, h, w, title=None):
    """Draw a bordered box."""
    try:
        win.attron(curses.color_pair(8))
        # Corners
        win.addch(y, x, curses.ACS_ULCORNER)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        # Horizontal
        for c in range(1, w - 1):
            win.addch(y, x + c, curses.ACS_HLINE)
            win.addch(y + h - 1, x + c, curses.ACS_HLINE)
        # Vertical
        for r in range(1, h - 1):
            win.addch(y + r, x, curses.ACS_VLINE)
            win.addch(y + r, x + w - 1, curses.ACS_VLINE)
        win.attroff(curses.color_pair(8))
        if title:
            label = f" {title} "
            win.attron(curses.color_pair(9) | curses.A_BOLD)
            win.addstr(y, x + (w - len(label)) // 2, label)
            win.attroff(curses.color_pair(9) | curses.A_BOLD)
    except curses.error:
        pass


def draw_board(win, game, board_y, board_x):
    """Draw the game board and pieces."""
    ghost_pos = game.get_ghost_pos()

    for r in range(BOARD_HEIGHT):
        for c in range(BOARD_WIDTH):
            cell_y = board_y + 1 + r
            cell_x = board_x + 1 + c * 2

            color = game.board[r][c]
            if color:
                try:
                    win.attron(curses.color_pair(color))
                    win.addstr(cell_y, cell_x, "  ")
                    win.attroff(curses.color_pair(color))
                except curses.error:
                    pass
            else:
                try:
                    win.attron(curses.color_pair(8))
                    win.addstr(cell_y, cell_x, "··")
                    win.attroff(curses.color_pair(8))
                except curses.error:
                    pass

    # Ghost piece
    ghost_color = PIECE_COLORS[game.current_type]
    for (r, c) in game.current_piece:
        gr, gc = ghost_pos[0] + r, ghost_pos[1] + c
        if 0 <= gr < BOARD_HEIGHT and 0 <= gc < BOARD_WIDTH:
            cell_y = board_y + 1 + gr
            cell_x = board_x + 1 + gc * 2
            try:
                win.attron(curses.color_pair(ghost_color) | curses.A_DIM)
                win.addstr(cell_y, cell_x, "░░")
                win.attroff(curses.color_pair(ghost_color) | curses.A_DIM)
            except curses.error:
                pass

    # Current piece
    piece_color = PIECE_COLORS[game.current_type]
    for (r, c) in game.current_piece:
        pr, pc = game.current_pos[0] + r, game.current_pos[1] + c
        if 0 <= pr < BOARD_HEIGHT and 0 <= pc < BOARD_WIDTH:
            cell_y = board_y + 1 + pr
            cell_x = board_x + 1 + pc * 2
            try:
                win.attron(curses.color_pair(piece_color) | curses.A_BOLD)
                win.addstr(cell_y, cell_x, "  ")
                win.attroff(curses.color_pair(piece_color) | curses.A_BOLD)
            except curses.error:
                pass


def draw_next_piece(win, game, box_y, box_x):
    """Draw the next piece in the NEXT box."""
    piece = TETROMINOES[game.next_type][0]
    color = PIECE_COLORS[game.next_type]
    # Center in a 4x4 grid inside the box
    for r in range(4):
        for c in range(4):
            cy = box_y + 2 + r
            cx = box_x + 2 + c * 2
            try:
                win.addstr(cy, cx, "  ")
            except curses.error:
                pass
    for (r, c) in piece:
        cy = box_y + 2 + r
        cx = box_x + 2 + c * 2
        try:
            win.attron(curses.color_pair(color) | curses.A_BOLD)
            win.addstr(cy, cx, "  ")
            win.attroff(curses.color_pair(color) | curses.A_BOLD)
        except curses.error:
            pass


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)
    init_colors()

    MIN_HEIGHT = 26
    MIN_WIDTH = 60

    while True:
        height, width = stdscr.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            stdscr.clear()
            msg = f"Terminal too small! Need {MIN_WIDTH}x{MIN_HEIGHT}, got {width}x{height}"
            try:
                stdscr.addstr(height // 2, max(0, (width - len(msg)) // 2), msg[:width])
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord('q') or key == ord('Q'):
                return
            time.sleep(0.1)
            continue
        break

    game = TetrisGame()

    # Layout constants
    board_w = BOARD_WIDTH * 2 + 2   # 22
    board_h = BOARD_HEIGHT + 2       # 22

    # Center the entire layout
    total_w = 14 + 1 + board_w + 1 + 12   # left + gap + board + gap + right = ~50
    start_x = max(0, (width - total_w) // 2)
    start_y = 2

    left_x = start_x
    board_x = left_x + 14 + 1
    right_x = board_x + board_w + 1

    last_fall = time.time()
    soft_drop = False

    while True:
        now = time.time()
        height, width = stdscr.getmaxyx()

        key = stdscr.getch()

        if key == ord('q') or key == ord('Q'):
            break

        if key == ord('p') or key == ord('P'):
            game.paused = not game.paused

        if game.game_over:
            # Show game over screen
            stdscr.clear()
            msg1 = "GAME OVER"
            msg2 = f"Final Score: {game.score}"
            msg3 = "Press Q to quit or R to restart"
            cy = height // 2 - 2
            try:
                stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
                stdscr.addstr(cy, (width - len(msg1)) // 2, msg1)
                stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
                stdscr.attron(curses.color_pair(8))
                stdscr.addstr(cy + 2, (width - len(msg2)) // 2, msg2)
                stdscr.addstr(cy + 4, (width - len(msg3)) // 2, msg3)
                stdscr.attroff(curses.color_pair(8))
            except curses.error:
                pass
            stdscr.refresh()
            if key == ord('r') or key == ord('R'):
                game = TetrisGame()
                last_fall = time.time()
            continue

        if not game.paused:
            if key == curses.KEY_LEFT:
                game.move(0, -1)
            elif key == curses.KEY_RIGHT:
                game.move(0, 1)
            elif key == curses.KEY_UP:
                game.rotate()
            elif key == curses.KEY_DOWN:
                soft_drop = True
            elif key == ord(' '):
                game.hard_drop()
                last_fall = now

            if key != curses.KEY_DOWN:
                soft_drop = False

            interval = game.get_fall_interval()
            if soft_drop:
                interval = 0.05

            if now - last_fall >= interval:
                game.fall()
                last_fall = now

        # Draw everything
        stdscr.clear()

        # Title
        title = "Terminal Tetris"
        try:
            stdscr.attron(curses.color_pair(9) | curses.A_BOLD)
            stdscr.addstr(0, max(0, (width - len(title)) // 2), title)
            stdscr.attroff(curses.color_pair(9) | curses.A_BOLD)
        except curses.error:
            pass

        # Left sidebar: SCORE, LEVEL, LINES boxes
        draw_box(stdscr, start_y, left_x, 4, 13, "SCORE")
        try:
            stdscr.attron(curses.color_pair(8) | curses.A_BOLD)
            score_str = str(game.score)
            stdscr.addstr(start_y + 2, left_x + (13 - len(score_str)) // 2, score_str)
            stdscr.attroff(curses.color_pair(8) | curses.A_BOLD)
        except curses.error:
            pass

        draw_box(stdscr, start_y + 5, left_x, 4, 13, "LEVEL")
        try:
            stdscr.attron(curses.color_pair(8) | curses.A_BOLD)
            lv_str = str(game.level)
            stdscr.addstr(start_y + 7, left_x + (13 - len(lv_str)) // 2, lv_str)
            stdscr.attroff(curses.color_pair(8) | curses.A_BOLD)
        except curses.error:
            pass

        draw_box(stdscr, start_y + 10, left_x, 4, 13, "LINES")
        try:
            stdscr.attron(curses.color_pair(8) | curses.A_BOLD)
            ln_str = str(game.lines)
            stdscr.addstr(start_y + 12, left_x + (13 - len(ln_str)) // 2, ln_str)
            stdscr.attroff(curses.color_pair(8) | curses.A_BOLD)
        except curses.error:
            pass

        # Controls legend (bottom left)
        controls = [
            "Controls:",
            "← → : Move",
            "↑   : Rotate",
            "↓   : Soft drop",
            "SPC : Hard drop",
            "P   : Pause",
            "Q   : Quit",
            "R   : Restart",
        ]
        cy = start_y + 15
        for i, line in enumerate(controls):
            try:
                stdscr.attron(curses.color_pair(8))
                stdscr.addstr(cy + i, left_x, line[:13])
                stdscr.attroff(curses.color_pair(8))
            except curses.error:
                pass

        # Main board
        draw_box(stdscr, start_y, board_x, board_h, board_w, "TETRIS")
        draw_board(stdscr, game, start_y, board_x)

        # Right panel: NEXT box
        draw_box(stdscr, start_y, right_x, 8, 12, "NEXT")
        draw_next_piece(stdscr, game, start_y, right_x)

        # Pause overlay
        if game.paused:
            pmsg = "  PAUSED  "
            try:
                stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(start_y + board_h // 2, board_x + (board_w - len(pmsg)) // 2, pmsg)
                stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
            except curses.error:
                pass

        stdscr.refresh()


if __name__ == "__main__":
    curses.wrapper(main)
