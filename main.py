import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
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

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎲 Новая игра")],
        [KeyboardButton("➕ Добавить игрока")],
        [KeyboardButton("📊 Турнирная таблица"), KeyboardButton("👥 Список игроков")],
        [KeyboardButton("📋 Последние игры")]
    ], resize_keyboard=True)

def get_or_create_player(session, name):
    player = session.query(Player).filter_by(username=name).first()
    if not player:
        player = Player(username=name)
        session.add(player)
        session.flush()
    return player

# ========== START ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🎲 Бот для учета игр в нарды!\n\n• Победа = +1 очко\n• Марс = +2 очка\n\n/import — загрузить историю",
        reply_markup=get_main_keyboard()
    )

# ========== ИМПОРТ (БЕЗ ИЗМЕНЕНИЙ) ==========

async def import_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ /import Игрок1-Игрок2 Счет, ...\nПример: /import сергей-коля 20-10", reply_markup=get_main_keyboard())
        return
    raw = ' '.join(context.args)
    pairs = [p.strip() for p in raw.split(',') if p.strip()]
    session = Session()
    imported, errors = 0, []
    try:
        for pair in pairs:
            parts = pair.split()
            if len(parts) != 2: errors.append(f"❌ «{pair}»"); continue
            names, scores = parts[0].split('-'), parts[1].split('-')
            if len(names) != 2 or len(scores) != 2: errors.append(f"❌ «{pair}»"); continue
            try: s1, s2 = int(scores[0]), int(scores[1])
            except: errors.append(f"❌ «{pair}»"); continue
            p1 = get_or_create_player(session, names[0].strip())
            p2 = get_or_create_player(session, names[1].strip())
            w = p1.id if s1 > s2 else (p2.id if s2 > s1 else None)
            session.add(Game(player1_id=p1.id, player2_id=p2.id, winner_id=w, is_mars=0, points_p1=s1, points_p2=s2))
            p1.games_played += 1; p2.games_played += 1
            p1.points += s1; p2.points += s2
            if w == p1.id: p1.games_won += 1
            elif w == p2.id: p2.games_won += 1
            imported += 1
        session.commit()
        r = f"✅ Импортировано: {imported}"
        if errors: r += "\n" + "\n".join(errors)
        await update.message.reply_text(r, reply_markup=get_main_keyboard())
    except Exception as e:
        session.rollback()
        await update.message.reply_text(f"❌ {e}", reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== ГЛАВНЫЙ ОБРАБОТЧИК ==========

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"MSG: {text}, state: {context.user_data.get('state', 'menu')}")
    
    if text == "🎲 Новая игра":
        context.user_data.clear()
        await start_game(update, context)
    elif text == "➕ Добавить игрока":
        context.user_data.clear()
        context.user_data['state'] = 'add_name'
        await update.message.reply_text("Введите имя:", reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True))
    elif text == "📊 Турнирная таблица":
        context.user_data.clear()
        await show_table(update, context)
    elif text == "👥 Список игроков":
        context.user_data.clear()
        await show_players(update, context)
    elif text == "📋 Последние игры":
        context.user_data.clear()
        await show_last_games(update, context)
    elif text == "❌ Отмена":
        context.user_data.clear()
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
    elif context.user_data.get('state') == 'add_name':
        await add_player(update, context)
    else:
        await update.message.reply_text("Используйте кнопки меню", reply_markup=get_main_keyboard())

# ========== ДОБАВЛЕНИЕ ИГРОКА ==========

async def add_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    session = Session()
    try:
        if session.query(Player).filter_by(username=name).first():
            await update.message.reply_text(f"⚠️ «{name}» уже есть!", reply_markup=get_main_keyboard())
        else:
            session.add(Player(username=name))
            session.commit()
            await update.message.reply_text(f"✅ «{name}» добавлен!", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=get_main_keyboard())
    finally:
        session.close()
    context.user_data.clear()

# ========== НОВАЯ ИГРА ==========

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.username).all()
        if len(players) < 2:
            await update.message.reply_text("❌ Нужно 2+ игроков.", reply_markup=get_main_keyboard())
            return
        
        context.user_data['state'] = 'choose_p1'
        keyboard = [[InlineKeyboardButton(p.username, callback_data=f"p1_{p.id}")] for p in players]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        
        msg = await update.message.reply_text("🎲 Выберите ПЕРВОГО игрока:", reply_markup=InlineKeyboardMarkup(keyboard))
        logger.info(f"Отправлены кнопки выбора, msg_id={msg.message_id}, state=choose_p1")
    finally:
        session.close()

# ========== CALLBACK ОБРАБОТЧИК (ИСПРАВЛЕНО ЗАВИСАНИЕ) ==========

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    state = context.user_data.get('state', '')
    logger.info(f"CALLBACK: data={data}, state={state}")
    
    if data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Отменено")
        return
    
    # Защита от устаревших callback'ов (после перезапуска или когда state пустой)
    if not state:
        await query.edit_message_text("⌛ Сессия устарела. Начните заново: /start")
        return
    
    # Шаг 1
    if state == 'choose_p1' and data.startswith('p1_'):
        p1_id = int(data.split('_')[1])
        context.user_data['p1'] = p1_id
        context.user_data['state'] = 'choose_p2'
        session = Session()
        try:
            p1 = session.query(Player).get(p1_id)
            players = session.query(Player).filter(Player.id != p1_id).order_by(Player.username).all()
            keyboard = [[InlineKeyboardButton(p.username, callback_data=f"p2_{p.id}")] for p in players]
            keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
            await query.edit_message_text(f"Первый: {p1.username}\n\nВыберите ВТОРОГО:", reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Перешли к выбору второго, state=choose_p2")
        finally:
            session.close()
        return
    
    # Шаг 2
    if state == 'choose_p2' and data.startswith('p2_'):
        p2_id = int(data.split('_')[1])
        context.user_data['p2'] = p2_id
        context.user_data['state'] = 'choose_result'
        session = Session()
        try:
            p1 = session.query(Player).get(context.user_data['p1'])
            p2 = session.query(Player).get(p2_id)
            keyboard = [
                [InlineKeyboardButton(f"🏆 Победил {p1.username} (+1)", callback_data="win1")],
                [InlineKeyboardButton(f"⭐ Марс {p1.username} (+2)", callback_data="mars1")],
                [InlineKeyboardButton(f"🏆 Победил {p2.username} (+1)", callback_data="win2")],
                [InlineKeyboardButton(f"⭐ Марс {p2.username} (+2)", callback_data="mars2")],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
            ]
            await query.edit_message_text(f"🎲 {p1.username} 🆚 {p2.username}\n\nВыберите результат:", reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Перешли к выбору результата, state=choose_result")
        finally:
            session.close()
        return
    
    # Шаг 3
    if state == 'choose_result' and data in ['win1', 'mars1', 'win2', 'mars2']:
        session = Session()
        try:
            p1 = session.query(Player).get(context.user_data['p1'])
            p2 = session.query(Player).get(context.user_data['p2'])
            if data == 'win1': rtext, stext, pp1, pp2, win, mars = f"Победил {p1.username}", f"{p1.username} 1-0 {p2.username}", 1, 0, p1.id, False
            elif data == 'mars1': rtext, stext, pp1, pp2, win, mars = f"МАРС! {p1.username}", f"{p1.username} 2-0 {p2.username}", 2, 0, p1.id, True
            elif data == 'win2': rtext, stext, pp1, pp2, win, mars = f"Победил {p2.username}", f"{p1.username} 0-1 {p2.username}", 0, 1, p2.id, False
            elif data == 'mars2': rtext, stext, pp1, pp2, win, mars = f"МАРС! {p2.username}", f"{p1.username} 0-2 {p2.username}", 0, 2, p2.id, True
            context.user_data.update({'pp1': pp1, 'pp2': pp2, 'win': win, 'mars': mars, 'state': 'confirm'})
            keyboard = [[InlineKeyboardButton("💾 Сохранить", callback_data="save")], [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]
            await query.edit_message_text(f"🎲 Подтверждение:\n\n{p1.username} 🆚 {p2.username}\n{rtext}\nСчет: {stext}\n\nСохранить?", reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Перешли к подтверждению, state=confirm")
        finally:
            session.close()
        return
    
    # Шаг 4 — ИСПРАВЛЕНО: защита от повторного нажатия и обработка ошибок
    if state == 'confirm' and data == 'save':
        # Защита от двойного клика
        if context.user_data.get('saved'):
            await query.answer("✅ Уже сохранено!")
            return
        
        context.user_data['saved'] = True
        session = Session()
        try:
            p1, p2 = session.query(Player).get(context.user_data['p1']), session.query(Player).get(context.user_data['p2'])
            win, mars, pp1, pp2 = context.user_data.get('win'), context.user_data.get('mars', False), context.user_data.get('pp1', 0), context.user_data.get('pp2', 0)
            p1.games_played += 1; p2.games_played += 1
            p1.points += pp1; p2.points += pp2
            if win == p1.id: p1.games_won += 1; 
            if win == p1.id and mars: p1.mars_won += 1
            if win == p2.id: p2.games_won += 1
            if win == p2.id and mars: p2.mars_won += 1
            session.add(Game(player1_id=p1.id, player2_id=p2.id, winner_id=win, is_mars=1 if mars else 0, points_p1=pp1, points_p2=pp2))
            session.commit()
            w = session.query(Player).get(win) if win else None
            mt = " (МАРС!)" if mars else ""
            wt = f"Победитель: 🎉 {w.username}{mt}" if w else ""
            await query.edit_message_text(f"✅ Сохранено!\n\n{p1.username} {pp1} - {pp2} {p2.username}\n{wt}")
            logger.info(f"Игра сохранена!")
        except Exception as e:
            session.rollback()
            context.user_data.pop('saved', None)  # Разблокируем при ошибке
            logger.error(f"Ошибка: {e}")
            await query.edit_message_text(f"❌ {e}")
        finally:
            session.close()
        context.user_data.clear()
        return
    
    logger.warning(f"Необработанный callback: {data}, state={state}")

# ========== ТАБЛИЦЫ (БЕЗ ИЗМЕНЕНИЙ) ==========

async def show_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc()).all()
        if not players: await update.message.reply_text("📊 Нет данных.", reply_markup=get_main_keyboard()); return
        text, shown, has = "📊 ТУРНИРНАЯ ТАБЛИЦА\n\n", set(), False
        for p1 in players:
            for p2 in players:
                if p1.id >= p2.id: continue
                key = (min(p1.id, p2.id), max(p1.id, p2.id))
                if key in shown: continue
                shown.add(key)
                games = session.query(Game).filter(((Game.player1_id==p1.id)&(Game.player2_id==p2.id))|((Game.player1_id==p2.id)&(Game.player2_id==p1.id))).all()
                if games:
                    has = True; t1, t2 = 0, 0
                    for g in games:
                        if g.player1_id == p1.id: t1 += g.points_p1; t2 += g.points_p2
                        else: t1 += g.points_p2; t2 += g.points_p1
                    text += f"{p1.username} — {p2.username}: {t1}-{t2}\n"
        if not has: text += "Нет игр."
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally: session.close()

async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc()).all()
        if not players: await update.message.reply_text("👥 Нет игроков.", reply_markup=get_main_keyboard()); return
        text = "👥 СПИСОК ИГРОКОВ\n\n"
        for i, p in enumerate(players, 1): text += f"{i}. {p.username} — ⭐ {p.points} очк.\n"
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally: session.close()

async def show_last_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        games = session.query(Game).order_by(Game.game_date.desc()).limit(10).all()
        if not games: await update.message.reply_text("📋 Нет игр.", reply_markup=get_main_keyboard()); return
        text = "📋 ПОСЛЕДНИЕ ИГРЫ:\n\n"
        for g in games:
            p1, p2 = session.query(Player).get(g.player1_id), session.query(Player).get(g.player2_id)
            if not p1 or not p2: continue
            mars = " (МАРС!)" if g.is_mars else ""
            text += f"📅 {g.game_date.strftime('%d.%m.%Y %H:%M')}\n{p1.username} {g.points_p1}-{g.points_p2} {p2.username}"
            if g.winner_id:
                w = session.query(Player).get(g.winner_id)
                if w: text += f" → {w.username}{mars}"
            text += "\n\n"
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally: session.close()

# ========== ЗАПУСК ==========

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("import", import_data))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("БОТ ЗАПУЩЕН!")
    app.run_polling(poll_interval=0.5, timeout=30, drop_pending_updates=False)

if __name__ == "__main__":
    main()