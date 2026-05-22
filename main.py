import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8621441778:AAHO8OaEjIc4BUdiJUWDH_ND6iu0-PklJcs")

DB_PATH = os.environ.get("DB_PATH", "nardy.db")
engine = create_engine(f'sqlite:///{DB_PATH}')
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    points = Column(Integer, default=0)
    games_played = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    mars_won = Column(Integer, default=0)

class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    player1_id = Column(Integer, nullable=False)
    player2_id = Column(Integer, nullable=False)
    winner_id = Column(Integer, nullable=True)
    is_mars = Column(Integer, default=0)
    points_p1 = Column(Integer, default=0)
    points_p2 = Column(Integer, default=0)
    game_date = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSE_PLAYER1, CHOOSE_PLAYER2, CHOOSE_RESULT, CONFIRM_GAME = range(4)
ADD_PLAYER, CONFIRM_ADD_PLAYER = range(10, 12)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🎲 Добавить результат игры")],
        [KeyboardButton("➕ Добавить игрока")],
        [KeyboardButton("📊 Турнирная таблица"), KeyboardButton("👥 Список игроков")],
        [KeyboardButton("📋 Последние игры")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎲 Бот для учета игр в нарды!\n\n"
        "• Победа = +1 очко\n"
        "• Марс = +2 очка\n\n"
        "Используйте кнопки ниже:",
        reply_markup=get_main_keyboard()
    )

# ========== ОБРАБОТЧИКИ МЕНЮ ==========

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"Нажата кнопка: {text}")
    
    if text == "🎲 Добавить результат игры":
        return await new_game(update, context)
    elif text == "➕ Добавить игрока":
        await update.message.reply_text(
            "Введите имя нового игрока:",
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return ADD_PLAYER
    elif text == "📊 Турнирная таблица":
        await show_stats(update, context)
        return ConversationHandler.END
    elif text == "👥 Список игроков":
        await show_players(update, context)
        return ConversationHandler.END
    elif text == "📋 Последние игры":
        await show_recent_games(update, context)
        return ConversationHandler.END
    elif text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
        return ConversationHandler.END

# ========== ДОБАВЛЕНИЕ ИГРОКА ==========

async def add_player_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player_name = update.message.text.strip()
    
    if player_name == "❌ Отмена":
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    
    session = Session()
    try:
        existing = session.query(Player).filter_by(username=player_name).first()
        if existing:
            await update.message.reply_text(
                f"⚠️ Игрок «{player_name}» уже существует!",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
    finally:
        session.close()
    
    context.user_data['new_player_name'] = player_name
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, добавить", callback_data="confirm_add")],
        [InlineKeyboardButton("❌ Нет", callback_data="cancel_add")]
    ]
    
    await update.message.reply_text(
        f"Добавить игрока «{player_name}»?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_ADD_PLAYER

async def confirm_add_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_add":
        await query.edit_message_text("❌ Отменено")
        await update.effective_chat.send_message(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    player_name = context.user_data.get('new_player_name', '')
    
    session = Session()
    try:
        player = Player(username=player_name)
        session.add(player)
        session.commit()
        await query.edit_message_text(f"✅ Игрок «{player_name}» добавлен!")
        await update.effective_chat.send_message(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        logger.info(f"Добавлен игрок: {player_name}")
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        await query.edit_message_text("❌ Ошибка.")
        await update.effective_chat.send_message(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
    finally:
        session.close()
    
    return ConversationHandler.END

# ========== НОВАЯ ИГРА ==========

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.username).all()
        if len(players) < 2:
            await update.message.reply_text(
                "❌ Нужно минимум 2 игрока.",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
        
        keyboard = []
        for p in players:
            keyboard.append([InlineKeyboardButton(p.username, callback_data=f"p1_{p.id}")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        
        await update.message.reply_text(
            "🎲 Выберите ПЕРВОГО игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_PLAYER1
    except Exception as e:
        logger.error(f"Ошибка new_game: {e}")
        return ConversationHandler.END
    finally:
        session.close()

async def choose_p1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    p1_id = int(query.data.split('_')[1])
    context.user_data['p1_id'] = p1_id
    
    session = Session()
    try:
        p1 = session.query(Player).get(p1_id)
        players = session.query(Player).filter(Player.id != p1_id).order_by(Player.username).all()
        
        keyboard = []
        for p in players:
            keyboard.append([InlineKeyboardButton(p.username, callback_data=f"p2_{p.id}")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        
        await query.edit_message_text(
            f"Первый игрок: {p1.username}\n\nВыберите ВТОРОГО игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_PLAYER2
    except Exception as e:
        logger.error(f"Ошибка choose_p1: {e}")
        return ConversationHandler.END
    finally:
        session.close()

async def choose_p2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    p2_id = int(query.data.split('_')[1])
    context.user_data['p2_id'] = p2_id
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1_id'])
        p2 = session.query(Player).get(p2_id)
        
        keyboard = [
            [InlineKeyboardButton(f"🏆 Победил {p1.username} (+1)", callback_data="win_1")],
            [InlineKeyboardButton(f"⭐ Марс {p1.username} (+2)", callback_data="mars_1")],
            [InlineKeyboardButton(f"🏆 Победил {p2.username} (+1)", callback_data="win_2")],
            [InlineKeyboardButton(f"⭐ Марс {p2.username} (+2)", callback_data="mars_2")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ]
        
        await query.edit_message_text(
            f"🎲 {p1.username} 🆚 {p2.username}\n\nВыберите результат:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_RESULT
    except Exception as e:
        logger.error(f"Ошибка choose_p2: {e}")
        return ConversationHandler.END
    finally:
        session.close()

async def choose_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    data = query.data
    context.user_data['result'] = data
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1_id'])
        p2 = session.query(Player).get(context.user_data['p2_id'])
        
        if data == "win_1":
            result_text = f"Победил {p1.username}"
            score_text = f"{p1.username} 1 - 0 {p2.username}"
            context.user_data['points_p1'] = 1
            context.user_data['points_p2'] = 0
            context.user_data['winner_id'] = p1.id
            context.user_data['is_mars'] = False
        elif data == "mars_1":
            result_text = f"МАРС! Победил {p1.username}"
            score_text = f"{p1.username} 2 - 0 {p2.username}"
            context.user_data['points_p1'] = 2
            context.user_data['points_p2'] = 0
            context.user_data['winner_id'] = p1.id
            context.user_data['is_mars'] = True
        elif data == "win_2":
            result_text = f"Победил {p2.username}"
            score_text = f"{p1.username} 0 - 1 {p2.username}"
            context.user_data['points_p1'] = 0
            context.user_data['points_p2'] = 1
            context.user_data['winner_id'] = p2.id
            context.user_data['is_mars'] = False
        elif data == "mars_2":
            result_text = f"МАРС! Победил {p2.username}"
            score_text = f"{p1.username} 0 - 2 {p2.username}"
            context.user_data['points_p1'] = 0
            context.user_data['points_p2'] = 2
            context.user_data['winner_id'] = p2.id
            context.user_data['is_mars'] = True
        else:
            return ConversationHandler.END
        
        keyboard = [
            [InlineKeyboardButton("💾 Сохранить результат", callback_data="save_game")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_save")]
        ]
        
        await query.edit_message_text(
            f"🎲 Подтверждение:\n\n"
            f"{p1.username} 🆚 {p2.username}\n"
            f"{result_text}\n"
            f"Счет: {score_text}\n\n"
            f"Сохранить?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM_GAME
    except Exception as e:
        logger.error(f"Ошибка choose_result: {e}")
        return ConversationHandler.END
    finally:
        session.close()

async def confirm_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data != "save_game":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    session = Session()
    try:
        p1_id = context.user_data.get('p1_id')
        p2_id = context.user_data.get('p2_id')
        
        p1 = session.query(Player).get(p1_id)
        p2 = session.query(Player).get(p2_id)
        
        if not p1 or not p2:
            await query.edit_message_text("❌ Ошибка: игроки не найдены")
            return ConversationHandler.END
        
        winner_id = context.user_data.get('winner_id')
        is_mars = context.user_data.get('is_mars', False)
        points_p1 = context.user_data.get('points_p1', 0)
        points_p2 = context.user_data.get('points_p2', 0)
        
        p1.games_played += 1
        p2.games_played += 1
        p1.points += points_p1
        p2.points += points_p2
        
        if winner_id == p1.id:
            p1.games_won += 1
            if is_mars:
                p1.mars_won += 1
        elif winner_id == p2.id:
            p2.games_won += 1
            if is_mars:
                p2.mars_won += 1
        
        game = Game(
            player1_id=p1.id,
            player2_id=p2.id,
            winner_id=winner_id,
            is_mars=1 if is_mars else 0,
            points_p1=points_p1,
            points_p2=points_p2
        )
        session.add(game)
        session.commit()
        
        winner = session.query(Player).get(winner_id) if winner_id else None
        mars_text = " (МАРС!)" if is_mars else ""
        winner_text = f"Победитель: 🎉 {winner.username}{mars_text}" if winner else ""
        
        await query.edit_message_text(
            f"✅ Сохранено!\n\n"
            f"{p1.username} {points_p1} - {points_p2} {p2.username}\n"
            f"{winner_text}"
        )
        logger.info(f"Игра: {p1.username} {points_p1}-{points_p2} {p2.username}")
        
    except Exception as e:
        logger.error(f"Ошибка confirm_game: {e}")
        await query.edit_message_text(f"❌ Ошибка сохранения: {e}")
    finally:
        session.close()
    
    return ConversationHandler.END

# ========== ТУРНИРНАЯ ТАБЛИЦА (РЕЗУЛЬТАТЫ ПАР) ==========

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Турнирная таблица: результаты всех пар (накопительный итог)"""
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc()).all()
        if not players:
            await update.message.reply_text("📊 Нет данных.", reply_markup=get_main_keyboard())
            return
        
        text = "📊 ТУРНИРНАЯ ТАБЛИЦА\nРезультаты игр по парам:\n\n"
        
        has_games = False
        shown_pairs = set()
        
        for p1 in players:
            for p2 in players:
                if p1.id >= p2.id:
                    continue
                
                pair_key = tuple(sorted([p1.id, p2.id]))
                if pair_key in shown_pairs:
                    continue
                shown_pairs.add(pair_key)
                
                games = session.query(Game).filter(
                    ((Game.player1_id == p1.id) & (Game.player2_id == p2.id)) |
                    ((Game.player1_id == p2.id) & (Game.player2_id == p1.id))
                ).all()
                
                if games:
                    has_games = True
                    p1_total = 0
                    p2_total = 0
                    for g in games:
                        if g.player1_id == p1.id:
                            p1_total += g.points_p1
                            p2_total += g.points_p2
                        else:
                            p1_total += g.points_p2
                            p2_total += g.points_p1
                    
                    text += f"{p1.username} — {p2.username}: {p1_total}-{p2_total}\n"
        
        if not has_games:
            text += "Пока нет сыгранных игр."
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Ошибка show_stats: {e}")
    finally:
        session.close()

# ========== СПИСОК ИГРОКОВ (ОЧКИ) ==========

async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список игроков и набранные очки"""
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc()).all()
        if not players:
            await update.message.reply_text("👥 Нет игроков.", reply_markup=get_main_keyboard())
            return
        
        text = "👥 СПИСОК ИГРОКОВ\n\n"
        for i, p in enumerate(players, 1):
            text += f"{i}. {p.username} — ⭐ {p.points} очк.\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Ошибка show_players: {e}")
    finally:
        session.close()

# ========== ПОСЛЕДНИЕ ИГРЫ ==========

async def show_recent_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        games = session.query(Game).order_by(Game.game_date.desc()).limit(10).all()
        if not games:
            await update.message.reply_text("📋 Нет игр.", reply_markup=get_main_keyboard())
            return
        
        text = "📋 ПОСЛЕДНИЕ ИГРЫ:\n\n"
        for g in games:
            p1 = session.query(Player).get(g.player1_id)
            p2 = session.query(Player).get(g.player2_id)
            if not p1 or not p2:
                continue
            date = g.game_date.strftime("%d.%m.%Y %H:%M")
            mars = " (МАРС!)" if g.is_mars else ""
            text += f"📅 {date}\n{p1.username} {g.points_p1} - {g.points_p2} {p2.username}"
            if g.winner_id:
                w = session.query(Player).get(g.winner_id)
                if w:
                    text += f" → {w.username}{mars}"
            text += "\n\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Ошибка show_recent_games: {e}")
    finally:
        session.close()

# ========== ЗАПУСК ==========

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    add_player_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить игрока$"), button_handler)],
        states={
            ADD_PLAYER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_player_handler)],
            CONFIRM_ADD_PLAYER: [CallbackQueryHandler(confirm_add_player, pattern="^(confirm_add|cancel_add)")]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отмена$"), button_handler)]
    )
    
    game_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎲 Добавить результат игры$"), button_handler)],
        states={
            CHOOSE_PLAYER1: [CallbackQueryHandler(choose_p1, pattern="^p1_"),
                           CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^cancel$")],
            CHOOSE_PLAYER2: [CallbackQueryHandler(choose_p2, pattern="^p2_"),
                           CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^cancel$")],
            CHOOSE_RESULT: [CallbackQueryHandler(choose_result, pattern="^(win_|mars_|cancel)")],
            CONFIRM_GAME: [CallbackQueryHandler(confirm_game, pattern="^(save_game|cancel_save)")]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_player_conv)
    app.add_handler(game_conv)
    app.add_handler(MessageHandler(filters.Regex("^📊 Турнирная таблица$"), button_handler))
    app.add_handler(MessageHandler(filters.Regex("^👥 Список игроков$"), button_handler))
    app.add_handler(MessageHandler(filters.Regex("^📋 Последние игры$"), button_handler))
    
    logger.info("БОТ ЗАПУЩЕН!")
    app.run_polling()

if __name__ == "__main__":
    main()