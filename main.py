import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker

# Токен Bothost подставит автоматически из переменной окружения
import os
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8621441778:AAHO8OaEjIc4BUdiJUWDH_ND6iu0-PklJcs")

# База данных (SQLite для хранения данных)
DB_PATH = os.environ.get("DB_PATH", "nardy.db")
engine = create_engine(f'sqlite:///{DB_PATH}')
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    rating = Column(Float, default=1000.0)
    games_played = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    games_draw = Column(Integer, default=0)

class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    player1_id = Column(Integer, nullable=False)
    player2_id = Column(Integer, nullable=False)
    winner_id = Column(Integer, nullable=True)
    is_draw = Column(Integer, default=0)
    game_date = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSE_PLAYER1, CHOOSE_PLAYER2, CHOOSE_RESULT = range(3)

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
        "🎲 Бот для учета игр в нарды!\n\nИспользуйте кнопки ниже:",
        reply_markup=get_main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🎲 Добавить результат игры":
        return await new_game(update, context)
    elif text == "➕ Добавить игрока":
        await update.message.reply_text(
            "Введите имя нового игрока:",
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return 99
    elif text == "📊 Турнирная таблица":
        await show_stats(update, context)
    elif text == "👥 Список игроков":
        await show_players(update, context)
    elif text == "📋 Последние игры":
        await show_recent_games(update, context)
    elif text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
        return ConversationHandler.END

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
                f"⚠️ Игрок {player_name} уже существует!",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
        
        player = Player(username=player_name)
        session.add(player)
        session.commit()
        await update.message.reply_text(
            f"✅ Игрок «{player_name}» добавлен!",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        session.close()
    return ConversationHandler.END

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.username).all()
        if len(players) < 2:
            await update.message.reply_text(
                "❌ Нужно минимум 2 игрока. Сначала добавьте их!",
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
    finally:
        session.close()

async def choose_p1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    context.user_data['p1_id'] = int(query.data.split('_')[1])
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1_id'])
        players = session.query(Player).filter(Player.id != context.user_data['p1_id']).order_by(Player.username).all()
        
        keyboard = []
        for p in players:
            keyboard.append([InlineKeyboardButton(p.username, callback_data=f"p2_{p.id}")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        
        await query.edit_message_text(
            f"Первый игрок: {p1.username}\n\nВыберите ВТОРОГО игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_PLAYER2
    finally:
        session.close()

async def choose_p2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    context.user_data['p2_id'] = int(query.data.split('_')[1])
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1_id'])
        p2 = session.query(Player).get(context.user_data['p2_id'])
        
        keyboard = [
            [InlineKeyboardButton(f"🏆 Победил {p1.username}", callback_data="win_1")],
            [InlineKeyboardButton(f"🏆 Победил {p2.username}", callback_data="win_2")],
            [InlineKeyboardButton("🤝 Ничья", callback_data="draw")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ]
        
        await query.edit_message_text(
            f"🎲 Игра:\n{p1.username} 🆚 {p2.username}\n\nКто победил?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_RESULT
    finally:
        session.close()

async def choose_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1_id'])
        p2 = session.query(Player).get(context.user_data['p2_id'])
        
        is_draw = False
        winner_id = None
        winner_name = None
        
        if query.data == "draw":
            is_draw = True
            p1.games_draw += 1
            p2.games_draw += 1
            result_text = f"✅ Записана ничья!\n\n{p1.username} 🤝 {p2.username}"
        elif query.data == "win_1":
            winner_id = p1.id
            winner_name = p1.username
            p1.games_won += 1
            p1.rating += 25
            p2.rating -= 25
            result_text = f"✅ Игра записана!\n\nПобедитель: 🎉 {p1.username}\nПроигравший: {p2.username}"
        elif query.data == "win_2":
            winner_id = p2.id
            winner_name = p2.username
            p2.games_won += 1
            p2.rating += 25
            p1.rating -= 25
            result_text = f"✅ Игра записана!\n\nПобедитель: 🎉 {p2.username}\nПроигравший: {p1.username}"
        
        p1.games_played += 1
        p2.games_played += 1
        
        game = Game(
            player1_id=p1.id,
            player2_id=p2.id,
            winner_id=winner_id,
            is_draw=1 if is_draw else 0
        )
        session.add(game)
        session.commit()
        
        await query.edit_message_text(result_text)
        
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")
        await query.edit_message_text("❌ Ошибка при сохранении.")
    finally:
        session.close()
    
    return ConversationHandler.END

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.rating.desc()).all()
        if not players:
            await update.message.reply_text("📊 Нет данных.", reply_markup=get_main_keyboard())
            return
        
        text = "📊 ТУРНИРНАЯ ТАБЛИЦА\n\n"
        text += "─" * 35 + "\n"
        for i, p in enumerate(players, 1):
            wr = (p.games_won / p.games_played * 100) if p.games_played > 0 else 0
            text += f"{i}. {p.username}\n"
            text += f"   📈 Рейтинг: {p.rating:.0f} | Игр: {p.games_played}\n"
            text += f"   🏆 Побед: {p.games_won} | 🤝 Ничьих: {p.games_draw} | % побед: {wr:.0f}%\n\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.username).all()
        if not players:
            await update.message.reply_text("👥 Нет игроков.", reply_markup=get_main_keyboard())
            return
        
        text = "👥 СПИСОК ИГРОКОВ:\n\n"
        for p in players:
            wr = (p.games_won / p.games_played * 100) if p.games_played > 0 else 0
            text += f"• {p.username}\n"
            text += f"  Рейтинг: {p.rating:.0f} | Игр: {p.games_played} | Побед: {p.games_won} ({wr:.0f}%)\n\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

async def show_recent_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        games = session.query(Game).order_by(Game.game_date.desc()).limit(10).all()
        if not games:
            await update.message.reply_text("📋 Нет записанных игр.", reply_markup=get_main_keyboard())
            return
        
        text = "📋 ПОСЛЕДНИЕ ИГРЫ:\n\n"
        for g in games:
            p1 = session.query(Player).get(g.player1_id)
            p2 = session.query(Player).get(g.player2_id)
            date = g.game_date.strftime("%d.%m.%Y %H:%M")
            
            if g.is_draw:
                result = f"{p1.username} 🤝 {p2.username} (ничья)"
            else:
                w = session.query(Player).get(g.winner_id)
                result = f"{p1.username} 🆚 {p2.username} → 🏆 {w.username}"
            
            text += f"📅 {date}\n{result}\n\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== ЗАПУСК ==========

def main():
    # На Bothost не нужен прокси
    app = Application.builder().token(BOT_TOKEN).build()
    
    add_player_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить игрока$"), button_handler)],
        states={99: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_player_handler)]},
        fallbacks=[MessageHandler(filters.Regex("^❌ Отмена$"), button_handler)]
    )
    
    game_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎲 Добавить результат игры$"), button_handler)],
        states={
            CHOOSE_PLAYER1: [CallbackQueryHandler(choose_p1, pattern="^p1_"),
                           CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^cancel$")],
            CHOOSE_PLAYER2: [CallbackQueryHandler(choose_p2, pattern="^p2_"),
                           CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^cancel$")],
            CHOOSE_RESULT: [CallbackQueryHandler(choose_result, pattern="^(win_|draw|cancel)")]
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