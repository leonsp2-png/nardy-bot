import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

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

CHOOSE_P1, CHOOSE_P2, CHOOSE_RESULT, CONFIRM = range(4)

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎲 Добавить результат игры")],
        [KeyboardButton("➕ Добавить игрока")],
        [KeyboardButton("📊 Турнирная таблица"), KeyboardButton("👥 Список игроков")],
        [KeyboardButton("📋 Последние игры")]
    ], resize_keyboard=True)

def get_or_create_player(session, name):
    """Найти или создать игрока"""
    player = session.query(Player).filter_by(username=name).first()
    if not player:
        player = Player(username=name)
        session.add(player)
        session.flush()
    return player

# ========== ИМПОРТ ИСТОРИЧЕСКИХ ДАННЫХ ==========

async def import_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для загрузки исторических данных.
    Формат: /import Игрок1-Игрок2 Счет1-Счет2, Игрок3-Игрок4 Счет3-Счет4, ...
    Пример: /import сергей-коля 20-10, иван-андрей 40-23, коля-иван 10-20, андрей-сергей 13-8
    """
    if not context.args:
        await update.message.reply_text(
            "❌ Формат: /import Игрок1-Игрок2 Счет1-Счет2, ...\n\n"
            "Пример:\n"
            "/import сергей-коля 20-10, иван-андрей 40-23, коля-иван 10-20, андрей-сергей 13-8",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Собираем весь текст после команды
    raw = ' '.join(context.args)
    
    # Разбиваем на пары по запятой
    pairs = [p.strip() for p in raw.split(',') if p.strip()]
    
    if not pairs:
        await update.message.reply_text("❌ Не указаны данные для импорта.", reply_markup=get_main_keyboard())
        return
    
    session = Session()
    imported = 0
    errors = []
    
    try:
        for pair in pairs:
            # Разбиваем "сергей-коля 20-10" на части
            parts = pair.split()
            if len(parts) != 2:
                errors.append(f"❌ Неверный формат: «{pair}»")
                continue
            
            names_part = parts[0]  # "сергей-коля"
            scores_part = parts[1]  # "20-10"
            
            names = names_part.split('-')
            scores = scores_part.split('-')
            
            if len(names) != 2 or len(scores) != 2:
                errors.append(f"❌ Неверный формат: «{pair}»")
                continue
            
            name1, name2 = names[0].strip(), names[1].strip()
            
            try:
                score1 = int(scores[0].strip())
                score2 = int(scores[1].strip())
            except ValueError:
                errors.append(f"❌ Неверный счет в: «{pair}»")
                continue
            
            # Получаем или создаем игроков
            p1 = get_or_create_player(session, name1)
            p2 = get_or_create_player(session, name2)
            
            # Определяем победителя
            if score1 > score2:
                winner_id = p1.id
            elif score2 > score1:
                winner_id = p2.id
            else:
                winner_id = None  # ничья
            
            # Сохраняем игру
            game = Game(
                player1_id=p1.id,
                player2_id=p2.id,
                winner_id=winner_id,
                is_mars=0,
                points_p1=score1,
                points_p2=score2
            )
            session.add(game)
            
            # Обновляем статистику
            p1.games_played += 1
            p2.games_played += 1
            p1.points += score1
            p2.points += score2
            
            if winner_id == p1.id:
                p1.games_won += 1
            elif winner_id == p2.id:
                p2.games_won += 1
            
            imported += 1
        
        session.commit()
        
        result_text = f"✅ Импортировано игр: {imported}"
        if errors:
            result_text += "\n\nОшибки:\n" + "\n".join(errors)
        
        await update.message.reply_text(result_text, reply_markup=get_main_keyboard())
        logger.info(f"Импортировано {imported} игр")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка импорта: {e}")
        await update.message.reply_text(f"❌ Ошибка импорта: {e}", reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== ГЛАВНОЕ МЕНЮ ==========

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🎲 Добавить результат игры":
        return await game_start(update, context)
    elif text == "➕ Добавить игрока":
        await update.message.reply_text("Введите имя нового игрока:", reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True))
        return 1
    elif text == "📊 Турнирная таблица":
        await show_table(update, context)
    elif text == "👥 Список игроков":
        await show_players(update, context)
    elif text == "📋 Последние игры":
        await show_last_games(update, context)
    elif text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
        return ConversationHandler.END

# ========== ДОБАВЛЕНИЕ ИГРОКА ==========

async def add_player_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if name == "❌ Отмена":
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    
    session = Session()
    try:
        if session.query(Player).filter_by(username=name).first():
            await update.message.reply_text(f"⚠️ Игрок «{name}» уже существует!", reply_markup=get_main_keyboard())
            return ConversationHandler.END
    finally:
        session.close()
    
    context.user_data['new_name'] = name
    keyboard = [[InlineKeyboardButton("✅ Да, добавить", callback_data="add_yes"),
                 InlineKeyboardButton("❌ Нет", callback_data="add_no")]]
    await update.message.reply_text(f"Добавить игрока «{name}»?", reply_markup=InlineKeyboardMarkup(keyboard))
    return 2

async def add_player_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_no":
        await query.edit_message_text("❌ Отменено")
    else:
        name = context.user_data.get('new_name', '')
        session = Session()
        try:
            session.add(Player(username=name))
            session.commit()
            await query.edit_message_text(f"✅ Игрок «{name}» добавлен!")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await query.edit_message_text("❌ Ошибка")
        finally:
            session.close()
    
    await update.effective_chat.send_message("Меню:", reply_markup=get_main_keyboard())
    return ConversationHandler.END

# ========== НОВАЯ ИГРА ==========

async def game_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.username).all()
        if len(players) < 2:
            await update.message.reply_text("❌ Нужно минимум 2 игрока.", reply_markup=get_main_keyboard())
            return ConversationHandler.END
        
        keyboard = [[InlineKeyboardButton(p.username, callback_data=f"s1_{p.id}")] for p in players]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        
        await update.message.reply_text("🎲 Выберите ПЕРВОГО игрока:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSE_P1
    finally:
        session.close()

async def choose_p1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    p1_id = int(query.data.split('_')[1])
    context.user_data['p1'] = p1_id
    
    session = Session()
    try:
        p1 = session.query(Player).get(p1_id)
        players = session.query(Player).filter(Player.id != p1_id).order_by(Player.username).all()
        keyboard = [[InlineKeyboardButton(p.username, callback_data=f"s2_{p.id}")] for p in players]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        await query.edit_message_text(f"Первый: {p1.username}\nВыберите ВТОРОГО игрока:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSE_P2
    finally:
        session.close()

async def choose_p2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    p2_id = int(query.data.split('_')[1])
    context.user_data['p2'] = p2_id
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1'])
        p2 = session.query(Player).get(p2_id)
        keyboard = [
            [InlineKeyboardButton(f"🏆 Победил {p1.username} (+1)", callback_data="r_win1")],
            [InlineKeyboardButton(f"⭐ Марс {p1.username} (+2)", callback_data="r_mars1")],
            [InlineKeyboardButton(f"🏆 Победил {p2.username} (+1)", callback_data="r_win2")],
            [InlineKeyboardButton(f"⭐ Марс {p2.username} (+2)", callback_data="r_mars2")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ]
        await query.edit_message_text(f"🎲 {p1.username} 🆚 {p2.username}\nВыберите результат:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSE_RESULT
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
        p1 = session.query(Player).get(context.user_data['p1'])
        p2 = session.query(Player).get(context.user_data['p2'])
        
        if data == "r_win1":
            rtext = f"Победил {p1.username}"; stext = f"{p1.username} 1 - 0 {p2.username}"
            context.user_data['pp1'] = 1; context.user_data['pp2'] = 0
            context.user_data['win'] = p1.id; context.user_data['mars'] = False
        elif data == "r_mars1":
            rtext = f"МАРС! {p1.username}"; stext = f"{p1.username} 2 - 0 {p2.username}"
            context.user_data['pp1'] = 2; context.user_data['pp2'] = 0
            context.user_data['win'] = p1.id; context.user_data['mars'] = True
        elif data == "r_win2":
            rtext = f"Победил {p2.username}"; stext = f"{p1.username} 0 - 1 {p2.username}"
            context.user_data['pp1'] = 0; context.user_data['pp2'] = 1
            context.user_data['win'] = p2.id; context.user_data['mars'] = False
        elif data == "r_mars2":
            rtext = f"МАРС! {p2.username}"; stext = f"{p1.username} 0 - 2 {p2.username}"
            context.user_data['pp1'] = 0; context.user_data['pp2'] = 2
            context.user_data['win'] = p2.id; context.user_data['mars'] = True
        else:
            return ConversationHandler.END
        
        keyboard = [[InlineKeyboardButton("💾 Сохранить", callback_data="save_yes"),
                     InlineKeyboardButton("❌ Отмена", callback_data="save_no")]]
        await query.edit_message_text(f"🎲 Подтверждение:\n\n{p1.username} 🆚 {p2.username}\n{rtext}\nСчет: {stext}\n\nСохранить?", reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM
    finally:
        session.close()

async def confirm_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data != "save_yes":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END
    
    session = Session()
    try:
        p1 = session.query(Player).get(context.user_data['p1'])
        p2 = session.query(Player).get(context.user_data['p2'])
        win = context.user_data.get('win')
        mars = context.user_data.get('mars', False)
        pp1 = context.user_data.get('pp1', 0)
        pp2 = context.user_data.get('pp2', 0)
        
        p1.games_played += 1; p2.games_played += 1
        p1.points += pp1; p2.points += pp2
        if win == p1.id:
            p1.games_won += 1
            if mars: p1.mars_won += 1
        elif win == p2.id:
            p2.games_won += 1
            if mars: p2.mars_won += 1
        
        session.add(Game(player1_id=p1.id, player2_id=p2.id, winner_id=win, is_mars=1 if mars else 0, points_p1=pp1, points_p2=pp2))
        session.commit()
        
        w = session.query(Player).get(win) if win else None
        mt = " (МАРС!)" if mars else ""
        wt = f"Победитель: 🎉 {w.username}{mt}" if w else ""
        await query.edit_message_text(f"✅ Сохранено!\n\n{p1.username} {pp1} - {pp2} {p2.username}\n{wt}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await query.edit_message_text(f"❌ Ошибка: {e}")
    finally:
        session.close()
    return ConversationHandler.END

# ========== ТАБЛИЦЫ ==========

async def show_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc()).all()
        if not players:
            await update.message.reply_text("📊 Нет данных.", reply_markup=get_main_keyboard())
            return
        text = "📊 ТУРНИРНАЯ ТАБЛИЦА\nРезультаты пар:\n\n"
        shown = set()
        has = False
        for p1 in players:
            for p2 in players:
                if p1.id >= p2.id: continue
                key = (min(p1.id, p2.id), max(p1.id, p2.id))
                if key in shown: continue
                shown.add(key)
                games = session.query(Game).filter(((Game.player1_id==p1.id)&(Game.player2_id==p2.id))|((Game.player1_id==p2.id)&(Game.player2_id==p1.id))).all()
                if games:
                    has = True
                    t1, t2 = 0, 0
                    for g in games:
                        if g.player1_id == p1.id: t1 += g.points_p1; t2 += g.points_p2
                        else: t1 += g.points_p2; t2 += g.points_p1
                    text += f"{p1.username} — {p2.username}: {t1}-{t2}\n"
        if not has: text += "Нет игр."
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc()).all()
        if not players:
            await update.message.reply_text("👥 Нет игроков.", reply_markup=get_main_keyboard())
            return
        text = "👥 СПИСОК ИГРОКОВ\n\n"
        for i, p in enumerate(players, 1): text += f"{i}. {p.username} — ⭐ {p.points} очк.\n"
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

async def show_last_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            if not p1 or not p2: continue
            mars = " (МАРС!)" if g.is_mars else ""
            text += f"📅 {g.game_date.strftime('%d.%m.%Y %H:%M')}\n{p1.username} {g.points_p1} - {g.points_p2} {p2.username}"
            if g.winner_id:
                w = session.query(Player).get(g.winner_id)
                if w: text += f" → {w.username}{mars}"
            text += "\n\n"
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== ЗАПУСК ==========

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Команда импорта
    app.add_handler(CommandHandler("import", import_data))
    
    # Команда старт
    app.add_handler(CommandHandler("start", start))
    
    # Добавление игрока
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить игрока$"), menu_handler)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_player_name)],
                2: [CallbackQueryHandler(add_player_confirm, pattern="^(add_yes|add_no)")]},
        fallbacks=[MessageHandler(filters.Regex("^❌ Отмена$"), menu_handler)]
    ))
    
    # Новая игра
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎲 Добавить результат игры$"), menu_handler)],
        states={
            CHOOSE_P1: [CallbackQueryHandler(choose_p1, pattern="^s1_"), CallbackQueryHandler(lambda u,c: ConversationHandler.END, pattern="^cancel$")],
            CHOOSE_P2: [CallbackQueryHandler(choose_p2, pattern="^s2_"), CallbackQueryHandler(lambda u,c: ConversationHandler.END, pattern="^cancel$")],
            CHOOSE_RESULT: [CallbackQueryHandler(choose_result, pattern="^r_"), CallbackQueryHandler(lambda u,c: ConversationHandler.END, pattern="^cancel$")],
            CONFIRM: [CallbackQueryHandler(confirm_game, pattern="^(save_yes|save_no)")]
        },
        fallbacks=[]
    ))
    
    app.add_handler(MessageHandler(filters.Regex("^(📊 Турнирная таблица|👥 Список игроков|📋 Последние игры)$"), menu_handler))
    
    logger.info("БОТ ЗАПУЩЕН!")
    app.run_polling()

if __name__ == "__main__":
    main()