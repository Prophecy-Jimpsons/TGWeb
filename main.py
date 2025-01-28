from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
import logging
from typing import Dict, Optional, List, Tuple
import asyncio

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class GameState:
    def __init__(self, chat_id: int):
        self.chat_id: int = chat_id
        self.board: List[List[str]] = [[" " for _ in range(4)] for _ in range(4)]
        self.current_player: str = "X"
        self.pieces: Dict[str, int] = {"X": 0, "O": 0}
        self.players: Dict[str, Optional[int]] = {"X": None, "O": None}
        self.player_names: Dict[str, Optional[str]] = {"X": None, "O": None}
        self.phase: str = "waiting"
        self.selected_piece: Optional[Tuple[int, int]] = None
        self.message_id: Optional[int] = None
        self.last_action_time = asyncio.get_event_loop().time()

async def check_all_games_timeout(context: ContextTypes.DEFAULT_TYPE):
    games_to_remove = []
    for chat_id, game in context.bot_data.get("games", {}).items():
        if game.phase != "finished" and game.phase != "waiting":
            current_time = asyncio.get_event_loop().time()
            if current_time - game.last_action_time > 60:  # 60 seconds timeout
                winner = "O" if game.current_player == "X" else "X"
                winning_player_name = game.player_names[winner]
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ Time's Up!\n\n"
                         f"Player {winner} ({winning_player_name}) wins by default!\n"
                         f"Player {game.current_player} was inactive for too long.\n\n"
                         f"Use /start to begin a new game. 🎮"
                )
                games_to_remove.append(chat_id)
    
    # Remove finished games
    for chat_id in games_to_remove:
        del context.bot_data["games"][chat_id]

def find_winning_pattern(board: List[List[str]]) -> Optional[List[Tuple[int, int]]]:
    # Check rows and columns
    for i in range(4):
        if all(board[i][j] == "X" for j in range(4)):
            return [(i, j) for j in range(4)]
        if all(board[i][j] == "O" for j in range(4)):
            return [(i, j) for j in range(4)]
        if all(board[j][i] == "X" for j in range(4)):
            return [(j, i) for j in range(4)]
        if all(board[j][i] == "O" for j in range(4)):
            return [(j, i) for j in range(4)]

    # Check diagonals
    if all(board[i][i] == "X" for i in range(4)):
        return [(i, i) for i in range(4)]
    if all(board[i][i] == "O" for i in range(4)):
        return [(i, i) for i in range(4)]
    if all(board[i][3-i] == "X" for i in range(4)):
        return [(i, 3-i) for i in range(4)]
    if all(board[i][3-i] == "O" for i in range(4)):
        return [(i, 3-i) for i in range(4)]

    # Check 2x2 squares
    for i in range(3):
        for j in range(3):
            if all(board[i+di][j+dj] == "X" for di, dj in [(0,0), (0,1), (1,0), (1,1)]):
                return [(i+di, j+dj) for di, dj in [(0,0), (0,1), (1,0), (1,1)]]
            if all(board[i+di][j+dj] == "O" for di, dj in [(0,0), (0,1), (1,0), (1,1)]):
                return [(i+di, j+dj) for di, dj in [(0,0), (0,1), (1,0), (1,1)]]

    return None

def check_winner(board: List[List[str]]) -> Optional[str]:
    pattern = find_winning_pattern(board)
    if pattern:
        return board[pattern[0][0]][pattern[0][1]]
    return None

def create_keyboard_with_highlight(board: List[List[str]],
                                 highlight_pos: Optional[Tuple[int, int]] = None,
                                 winning_pattern: Optional[List[Tuple[int, int]]] = None) -> List[List[InlineKeyboardButton]]:
    keyboard = []
    for i, row in enumerate(board):
        keyboard_row = []
        for j, cell in enumerate(row):
            if winning_pattern and (i, j) in winning_pattern:
                button_text = f"🏆{cell}🏆"
            elif (i, j) == highlight_pos:
                button_text = f"[{cell}]" if cell != " " else "[·]"
            else:
                button_text = cell if cell != " " else "·"
            keyboard_row.append(InlineKeyboardButton(button_text, callback_data=f"{i},{j}"))
        keyboard.append(keyboard_row)
    return keyboard

async def animate_win(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     game: 'GameState', winner: str, pattern: List[Tuple[int, int]]):
    animations = ["🎮", "🎲", "🎯", "🎪", "🎨"]
    for anim in animations:
        keyboard = create_keyboard_with_highlight(game.board, winning_pattern=pattern)
        await context.bot.edit_message_text(
            chat_id=game.chat_id,
            message_id=game.message_id,
            text=f"{anim} WINNER! {anim}\n\n"
                 f"Player {winner} ({game.player_names[winner]}) wins!\n"
                 f"Final Board Position:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await asyncio.sleep(0.5)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if update.effective_chat.type == 'private':
        await update.message.reply_text(
            "This game must be played in a group chat. Add me to a group and use /start there!"
        )
        return

    if "games" not in context.bot_data:
        context.bot_data["games"] = {}

    existing_game = context.bot_data["games"].get(chat_id)
    if existing_game and existing_game.phase != "finished":
        await update.message.reply_text("A game is already in progress in this chat!")
        return

    game = GameState(chat_id)
    context.bot_data["games"][chat_id] = game
    game.players["X"] = user_id
    game.player_names["X"] = user_name

    keyboard = create_keyboard_with_highlight(game.board)
    message = await update.message.reply_text(
        f"4x4 Tic-Tac-Toe!\nPlayer X: {user_name}\n"
        f"Waiting for player O to join...\nUse /join to join the game!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    game.message_id = message.message_id
    logger.info(f"New game started in chat {chat_id} by user {user_id}")

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if update.effective_chat.type == 'private':
        await update.message.reply_text(
            "You can only join games in group chats!"
        )
        return

    game = context.bot_data["games"].get(chat_id)
    if not game:
        await update.message.reply_text("No game in progress. Use /start to begin.")
        return

    if game.phase != "waiting":
        await update.message.reply_text("Game already in progress!")
        return

    if game.players["O"]:
        await update.message.reply_text("Game is full!")
        return

    if user_id == game.players["X"]:
        await update.message.reply_text("You can't play against yourself!")
        return

    game.players["O"] = user_id
    game.player_names["O"] = user_name
    game.phase = "placement"

    keyboard = create_keyboard_with_highlight(game.board)
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=game.message_id,
        text=f"Game started!\nX: {game.player_names['X']}\nO: {game.player_names['O']}\n"
             f"Player X's turn\nPlacement phase: {game.pieces['X']}/4 pieces placed",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    logger.info(f"Player O ({user_id}) joined the game in chat {chat_id}")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        # Check for inactivity timeout
        if await check_inactivity(update, context):
            await query.answer("Game was reset due to inactivity!", show_alert=True)
            return

        game = context.bot_data["games"].get(chat_id)
        if not game:
            await query.answer("No active game found!", show_alert=True)
            return

        if game.phase == "waiting":
            await query.answer("Waiting for player O to join!", show_alert=True)
            return

        if user_id != game.players[game.current_player]:
            await query.answer("Not your turn!", show_alert=True)
            return

        # Update last action time
        game.last_action_time = asyncio.get_event_loop().time()
        row, col = map(int, query.data.split(","))

        if game.phase == "placement":
            if game.board[row][col] != " ":
                await query.answer("Space already occupied!", show_alert=True)
                return

            game.board[row][col] = game.current_player
            game.pieces[game.current_player] += 1

            winner = check_winner(game.board)
            if winner:
                game.phase = "finished"
                winning_pattern = find_winning_pattern(game.board)
                await animate_win(update, context, game, winner, winning_pattern)
                # Clean up game data after win
                del context.bot_data["games"][chat_id]
                return

            if game.pieces["X"] == 4 and game.pieces["O"] == 4:
                game.phase = "movement"
                # Reset to X's turn for movement phase
                game.current_player = "X"  # Force X to go first in movement phase
                keyboard = create_keyboard_with_highlight(game.board)
                await query.edit_message_text(
                    f"All pieces placed! Movement phase begins.\n"
                    f"Player X's turn ({game.player_names['X']}) - Select any piece to move\n"
                    f"(Click a piece to select/deselect)",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return


            game.current_player = "O" if game.current_player == "X" else "X"
            keyboard = create_keyboard_with_highlight(game.board)
            await query.edit_message_text(
                f"Player {game.current_player}'s turn ({game.player_names[game.current_player]})\n"
                f"Placement phase: {game.pieces[game.current_player]}/4 pieces placed",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif game.phase == "movement":
            if not game.selected_piece:
                if game.board[row][col] == game.current_player:
                    game.selected_piece = (row, col)
                    keyboard = create_keyboard_with_highlight(game.board, (row, col))
                    await query.edit_message_text(
                        f"Selected piece at ({row+1},{col+1}). Choose new position.\n"
                        f"(Click the same piece again to deselect)",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await query.answer("Select your own piece!", show_alert=True)
            else:
                # Check if clicking the same piece (deselection)
                if (row, col) == game.selected_piece:
                    game.selected_piece = None
                    keyboard = create_keyboard_with_highlight(game.board)
                    await query.edit_message_text(
                        f"Player {game.current_player}'s turn ({game.player_names[game.current_player]})\n"
                        f"Movement phase: Select any piece to move",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    await query.answer("Piece deselected")
                    return

                if game.board[row][col] != " ":
                    await query.answer("Invalid move!", show_alert=True)
                    return

                # Make the move
                old_row, old_col = game.selected_piece
                game.board[old_row][old_col] = " "
                game.board[row][col] = game.current_player
                game.selected_piece = None

                winner = check_winner(game.board)
                if winner:
                    game.phase = "finished"
                    winning_pattern = find_winning_pattern(game.board)
                    await animate_win(update, context, game, winner, winning_pattern)
                    # Clean up game data after win
                    del context.bot_data["games"][chat_id]
                    return

                game.current_player = "O" if game.current_player == "X" else "X"
                keyboard = create_keyboard_with_highlight(game.board)
                await query.edit_message_text(
                    f"Player {game.current_player}'s turn ({game.player_names[game.current_player]})\n"
                    f"Movement phase: Select any piece to move",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        await query.answer()

    except Exception as e:
        logger.error(f"Error processing button click: {e}")
        await query.answer("Error processing move!", show_alert=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
4x4 Tic-Tac-Toe Game Rules:

1. Each player gets 4 pieces
2. First phase: Place all pieces
3. Second phase: Move any of your pieces
4. Win by getting:
   - Four in a row
   - Four in a column
   - Four in a diagonal
   - Four in a 2x2 square

Commands:
/start - Start a new game
/join - Join an existing game
/help - Show this help message
"""
    await update.message.reply_text(help_text)

def main():
    application = Application.builder().token("7794061139:AAFT2hDjBwOsk4rNoSlJ6eVn9ckeuCIg3fA").build()
    
    # Add job queue to check timeouts every 5 seconds
    job_queue = application.job_queue
    job_queue.run_repeating(check_all_games_timeout, interval=5)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_click))
    
    logger.info("Bot started with automatic timeout checking")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
