import logging
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Index, func
from sqlalchemy.orm import declarative_base, sessionmaker

# ========== КОНФИГУРАЦИЯ ==========

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан! Установите переменную окружения.")

DB_PATH = os.environ.get("DB_PATH", "nardy.db")

# SQLite с поддержкой многопоточности
engine = create_engine(
    f'sqlite:///{DB_PATH}',
    connect_args={'check_same_thread': False},
    echo=False
)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# ========== МОДЕЛИ ==========

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    points = Column(Integer, default=0)          # Турнирные очки
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
    points_p1 = Column(Integer, default=0)       # Турнирные очки за игру (0/1/2)
    points_p2 = Column(Integer, default=0)
    game_date = Column(DateTime, default=datetime.utcnow)

# Индексы для производительности
Index('idx_game_date', Game.game_date)
Index('idx_game_p1', Game.player1_id)
Index('idx_game_p2', Game.player2_id)
Index('idx_game_winner', Game.winner_id)

Base.metadata.create_all(engine)

# ========== ЛОГИРОВАНИЕ ==========

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎲 Новая игра")],
        [KeyboardButton("➕ Добавить игрока")],
        [KeyboardButton("📊 Турнирная таблица"), KeyboardButton("👥 Список игроков")],
        [KeyboardButton("📋 Последние игры"), KeyboardButton("📈 Статистика")]
    ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Отмена"]], resize=True)

# ========== УТИЛИТЫ ==========

def get_or_create_player(session, name):
    name = name.strip().lower()
    player = session.query(Player).filter_by(username=name).first()
    if not player:
        player = Player(username=name)
        session.add(player)
        session.flush()
    return player

async def safe_edit_message(query, text, reply_markup=None):
    """Безопасное редактирование сообщения с обработкой конфликтов"""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Ошибка редактирования: {e}")
        try:
            await query.answer("Сообщение устарело, начните заново /start")
        except:
            pass

# ========== КОМАНДЫ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🎲 Бот для учета игр в нарды!\n\n"
        "• Победа = +1 очко\n• Марс = +2 очка\n\n"
        "/import — загрузить историю\n"
        "/delete — удалить последнюю игру\n"
        "/stats Игрок1 Игрок2 — статистика личных встреч",
        reply_markup=get_main_keyboard()
    )

# ========== ИМПОРТ (ИСПРАВЛЕН) ==========

async def import_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Формат: /import Игрок1-Игрок2 Счет, ...\n"
            "Пример: /import сергей-коля 20-10, ваня-петя 15-5\n"
            "Счёт — это очки партии (не турнирные). Победа = +1, Марс = +2",
            reply_markup=get_main_keyboard()
        )
        return
    
    raw = ' '.join(context.args)
    pairs = [p.strip() for p in raw.split(',') if p.strip()]
    session = Session()
    imported, errors = 0, []
    
    try:
        for pair in pairs:
            parts = pair.split()
            if len(parts) != 2:
                errors.append(f"❌ «{pair}» — неверный формат")
                continue
            
            names = parts[0].split('-')
            scores = parts[1].split('-')
            if len(names) != 2 or len(scores) != 2:
                errors.append(f"❌ «{pair}» — неверный формат имен/счёта")
                continue
            
            try:
                s1, s2 = int(scores[0]), int(scores[1])
            except ValueError:
                errors.append(f"❌ «{pair}» — счёт должен быть числом")
                continue
            
            # Определяем победителя и турнирные очки
            if s1 > s2:
                winner_id, tp1, tp2 = None, 1, 0  # пока None, установим после создания игроков
                is_mars = 1 if (s1 - s2) >= 13 else 0  # марс — разгромное поражение (условно)
            elif s2 > s1:
                winner_id, tp1, tp2 = None, 0, 1
                is_mars = 1 if (s2 - s1) >= 13 else 0
            else:
                errors.append(f"❌ «{pair}» — ничья не поддерживается")
                continue
            
            p1 = get_or_create_player(session, names[0])
            p2 = get_or_create_player(session, names[1])
            
            # Уточняем winner_id
            if s1 > s2:
                winner_id = p1.id
                tp1 = 2 if is_mars else 1
            else:
                winner_id = p2.id
                tp2 = 2 if is_mars else 1
            
            # Обновляем статистику игроков
            p1.games_played += 1
            p2.games_played += 1
            p1.points += tp1
            p2.points += tp2
            if winner_id == p1.id:
                p1.games_won += 1
                if is_mars:
                    p1.mars_won += 1
            else:
                p2.games_won += 1
                if is_mars:
                    p2.mars_won += 1
            
            session.add(Game(
                player1_id=p1.id,
                player2_id=p2.id,
                winner_id=winner_id,
                is_mars=is_mars,
                points_p1=tp1,
                points_p2=tp2
            ))
            imported += 1
        
        session.commit()
        r = f"✅ Импортировано игр: {imported}"
        if errors:
            r += "\n\nОшибки:\n" + "\n".join(errors)
        await update.message.reply_text(r, reply_markup=get_main_keyboard())
        
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка импорта: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== УДАЛЕНИЕ ПОСЛЕДНЕЙ ИГРЫ ==========

async def delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        last_game = session.query(Game).order_by(Game.game_date.desc()).first()
        if not last_game:
            await update.message.reply_text("📋 Нет игр для удаления.", reply_markup=get_main_keyboard())
            return
        
        p1 = session.query(Player).get(last_game.player1_id)
        p2 = session.query(Player).get(last_game.player2_id)
        
        # Откат статистики
        p1.games_played -= 1
        p2.games_played -= 1
        p1.points -= last_game.points_p1
        p2.points -= last_game.points_p2
        
        if last_game.winner_id == p1.id:
            p1.games_won -= 1
            if last_game.is_mars:
                p1.mars_won -= 1
        elif last_game.winner_id == p2.id:
            p2.games_won -= 1
            if last_game.is_mars:
                p2.mars_won -= 1
        
        session.delete(last_game)
        session.commit()
        
        await update.message.reply_text(
            f"🗑 Удалена последняя игра:\n"
            f"{p1.username} {last_game.points_p1}-{last_game.points_p2} {p2.username}\n"
            f"Статистика игроков откатана.",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка удаления: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== СТАТИСТИКА ЛИЧНЫХ ВСТРЕЧ ==========

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Формат: /stats Игрок1 Игрок2",
            reply_markup=get_main_keyboard()
        )
        return
    
    name1, name2 = context.args[0].strip().lower(), context.args[1].strip().lower()
    session = Session()
    try:
        p1 = session.query(Player).filter_by(username=name1).first()
        p2 = session.query(Player).filter_by(username=name2).first()
        
        if not p1 or not p2:
            missing = []
            if not p1: missing.append(name1)
            if not p2: missing.append(name2)
            await update.message.reply_text(
                f"❌ Игроки не найдены: {', '.join(missing)}",
                reply_markup=get_main_keyboard()
            )
            return
        
        games = session.query(Game).filter(
            ((Game.player1_id == p1.id) & (Game.player2_id == p2.id)) |
            ((Game.player1_id == p2.id) & (Game.player2_id == p1.id))
        ).order_by(Game.game_date.desc()).all()
        
        if not games:
            await update.message.reply_text(
                f"📊 {p1.username} vs {p2.username}\n\nИгр не найдено.",
                reply_markup=get_main_keyboard()
            )
            return
        
        wins1, wins2, mars1, mars2 = 0, 0, 0, 0
        total_tp1, total_tp2 = 0, 0
        
        for g in games:
            if g.player1_id == p1.id:
                total_tp1 += g.points_p1
                total_tp2 += g.points_p2
                if g.winner_id == p1.id:
                    wins1 += 1
                    if g.is_mars: mars1 += 1
                elif g.winner_id == p2.id:
                    wins2 += 1
                    if g.is_mars: mars2 += 1
            else:
                total_tp1 += g.points_p2
                total_tp2 += g.points_p1
                if g.winner_id == p1.id:
                    wins1 += 1
                    if g.is_mars: mars1 += 1
                elif g.winner_id == p2.id:
                    wins2 += 1
                    if g.is_mars: mars2 += 1
        
        text = (
            f"📊 {p1.username} vs {p2.username}\n\n"
            f"Всего игр: {len(games)}\n"
            f"Побед {p1.username}: {wins1} (марсов: {mars1})\n"
            f"Побед {p2.username}: {wins2} (марсов: {mars2})\n"
            f"Турнирные очки: {total_tp1} - {total_tp2}\n\n"
            f"Последние 5 игр:\n"
        )
        
        for g in games[:5]:
            date = g.game_date.strftime('%d.%m.%Y')
            if g.player1_id == p1.id:
                sc1, sc2 = g.points_p1, g.points_p2
            else:
                sc1, sc2 = g.points_p2, g.points_p1
            w = "🎯" if g.winner_id == p1.id else "🎯" if g.winner_id == p2.id else "🤝"
            m = " (МАРС!)" if g.is_mars else ""
            text += f"{date}: {sc1}-{sc2}{m} {w}\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
        
    finally:
        session.close()

# ========== ГЛАВНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ ==========

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"MSG: {text}, state: {context.user_data.get('state', 'menu')}")
    
    # Кнопки меню — всегда сбрасывают состояние
    if text == "🎲 Новая игра":
        context.user_data.clear()
        await start_game(update, context)
    elif text == "➕ Добавить игрока":
        context.user_data.clear()
        context.user_data['state'] = 'add_name'
        await update.message.reply_text("Введите имя игрока:", reply_markup=get_cancel_keyboard())
    elif text == "📊 Турнирная таблица":
        context.user_data.clear()
        await show_table(update, context)
    elif text == "👥 Список игроков":
        context.user_data.clear()
        await show_players(update, context)
    elif text == "📋 Последние игры":
        context.user_data.clear()
        await show_last_games(update, context)
    elif text == "📈 Статистика":
        context.user_data.clear()
        await update.message.reply_text(
            "📈 Для просмотра статистики личных встреч используйте:\n/stats Игрок1 Игрок2",
            reply_markup=get_main_keyboard()
        )
    elif text == "❌ Отмена":
        context.user_data.clear()
        await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
    elif context.user_data.get('state') == 'add_name':
        await add_player(update, context)
    else:
        await update.message.reply_text("Используйте кнопки меню", reply_markup=get_main_keyboard())

# ========== ДОБАВЛЕНИЕ ИГРОКА ==========

async def add_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text(
            "⚠️ Имя должно быть от 2 до 50 символов.",
            reply_markup=get_main_keyboard()
        )
        context.user_data.clear()
        return
    
    session = Session()
    try:
        existing = session.query(Player).filter_by(username=name).first()
        if existing:
            await update.message.reply_text(
                f"⚠️ «{name}» уже есть в базе!",
                reply_markup=get_main_keyboard()
            )
        else:
            session.add(Player(username=name))
            session.commit()
            await update.message.reply_text(
                f"✅ «{name}» добавлен!",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка добавления: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())
    finally:
        session.close()
    context.user_data.clear()

# ========== НОВАЯ ИГРА (ИСПРАВЛЕНА ЗАЩИТА ОТ ДУБЛЕЙ) ==========

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.username).all()
        if len(players) < 2:
            await update.message.reply_text(
                "❌ Нужно минимум 2 игрока. Добавьте через «➕ Добавить игрока»",
                reply_markup=get_main_keyboard()
            )
            return
        
        context.user_data['state'] = 'choose_p1'
        keyboard = [[InlineKeyboardButton(p.username, callback_data=f"p1_{p.id}")] for p in players]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        
        msg = await update.message.reply_text(
            "🎲 Выберите ПЕРВОГО игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['msg_id'] = msg.message_id
        logger.info(f"Отправлены кнопки выбора P1, msg_id={msg.message_id}")
    finally:
        session.close()

# ========== CALLBACK ОБРАБОТЧИК (ИСПРАВЛЕНО ЗАВИСАНИЕ) ==========

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Всегда отвечаем Telegram, чтобы убрать "часы"
    
    data = query.data
    state = context.user_data.get('state', '')
    
    # Защита от повторной обработки
    if context.user_data.get('processing'):
        await query.answer("⏳ Обработка...", show_alert=False)
        return
    
    logger.info(f"CALLBACK: data={data}, state={state}")
    
    # Обработка устаревших callback'ов (после перезапуска или отмены)
    if not state and data != "cancel":
        await safe_edit_message(query, "⌛ Сессия устарела. Начните заново: /start")
        return
    
    if data == "cancel":
        context.user_data.clear()
        await safe_edit_message(query, "❌ Отменено")
        return
    
    # === Шаг 1: Выбор первого игрока ===
    if state == 'choose_p1' and data.startswith('p1_'):
        context.user_data['processing'] = True
        try:
            p1_id = int(data.split('_')[1])
            context.user_data['p1'] = p1_id
            context.user_data['state'] = 'choose_p2'
            
            session = Session()
            try:
                p1 = session.query(Player).get(p1_id)
                players = session.query(Player).filter(Player.id != p1_id).order_by(Player.username).all()
                keyboard = [[InlineKeyboardButton(p.username, callback_data=f"p2_{p.id}")] for p in players]
                keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
                await safe_edit_message(
                    query,
                    f"Первый игрок: {p1.username}\n\nВыберите ВТОРОГО:",
                    InlineKeyboardMarkup(keyboard)
                )
            finally:
                session.close()
        finally:
            context.user_data.pop('processing', None)
        return
    
    # === Шаг 2: Выбор второго игрока ===
    if state == 'choose_p2' and data.startswith('p2_'):
        context.user_data['processing'] = True
        try:
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
                await safe_edit_message(
                    query,
                    f"🎲 {p1.username} 🆚 {p2.username}\n\nВыберите результат:",
                    InlineKeyboardMarkup(keyboard)
                )
            finally:
                session.close()
        finally:
            context.user_data.pop('processing', None)
        return
    
    # === Шаг 3: Выбор результата ===
    if state == 'choose_result' and data in ['win1', 'mars1', 'win2', 'mars2']:
        context.user_data['processing'] = True
        try:
            session = Session()
            try:
                p1 = session.query(Player).get(context.user_data['p1'])
                p2 = session.query(Player).get(context.user_data['p2'])
                
                if data == 'win1':
                    rtext, stext, pp1, pp2, win, mars = f"Победил {p1.username}", f"{p1.username} 1-0 {p2.username}", 1, 0, p1.id, False
                elif data == 'mars1':
                    rtext, stext, pp1, pp2, win, mars = f"МАРС! {p1.username}", f"{p1.username} 2-0 {p2.username}", 2, 0, p1.id, True
                elif data == 'win2':
                    rtext, stext, pp1, pp2, win, mars = f"Победил {p2.username}", f"{p1.username} 0-1 {p2.username}", 0, 1, p2.id, False
                elif data == 'mars2':
                    rtext, stext, pp1, pp2, win, mars = f"МАРС! {p2.username}", f"{p1.username} 0-2 {p2.username}", 0, 2, p2.id, True
                
                context.user_data.update({
                    'pp1': pp1, 'pp2': pp2, 'win': win, 
                    'mars': mars, 'state': 'confirm'
                })
                
                keyboard = [
                    [InlineKeyboardButton("💾 Сохранить", callback_data="save")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
                ]
                await safe_edit_message(
                    query,
                    f"🎲 Подтверждение:\n\n{p1.username} 🆚 {p2.username}\n{rtext}\nСчет: {stext}\n\nСохранить?",
                    InlineKeyboardMarkup(keyboard)
                )
            finally:
                session.close()
        finally:
            context.user_data.pop('processing', None)
        return
    
    # === Шаг 4: Сохранение (КРИТИЧЕСКИ ВАЖНО — ЗАЩИТА ОТ ДУБЛЕЙ) ===
    if state == 'confirm' and data == 'save':
        # Проверяем, не сохранили ли уже
        if context.user_data.get('saved'):
            await query.answer("✅ Уже сохранено!", show_alert=False)
            return
        
        context.user_data['processing'] = True
        context.user_data['saved'] = True  # Блокировка повторного сохранения
        
        session = Session()
        try:
            p1 = session.query(Player).get(context.user_data['p1'])
            p2 = session.query(Player).get(context.user_data['p2'])
            win = context.user_data.get('win')
            mars = context.user_data.get('mars', False)
            pp1 = context.user_data.get('pp1', 0)
            pp2 = context.user_data.get('pp2', 0)
            
            # Обновляем статистику
            p1.games_played += 1
            p2.games_played += 1
            p1.points += pp1
            p2.points += pp2
            
            if win == p1.id:
                p1.games_won += 1
                if mars:
                    p1.mars_won += 1
            elif win == p2.id:
                p2.games_won += 1
                if mars:
                    p2.mars_won += 1
            
            session.add(Game(
                player1_id=p1.id,
                player2_id=p2.id,
                winner_id=win,
                is_mars=1 if mars else 0,
                points_p1=pp1,
                points_p2=pp2
            ))
            session.commit()
            
            w = session.query(Player).get(win) if win else None
            mt = " (МАРС!)" if mars else ""
            wt = f"Победитель: 🎉 {w.username}{mt}" if w else ""
            
            await safe_edit_message(
                query,
                f"✅ Сохранено!\n\n{p1.username} {pp1} - {pp2} {p2.username}\n{wt}"
            )
            logger.info(f"Игра сохранена: {p1.username} vs {p2.username}")
            
        except Exception as e:
            session.rollback()
            # Разблокируем при ошибке
            context.user_data.pop('saved', None)
            logger.error(f"Ошибка сохранения: {e}")
            await safe_edit_message(query, f"❌ Ошибка сохранения: {e}")
        finally:
            session.close()
            context.user_data.pop('processing', None)
            # Не очищаем user_data сразу — даём время на ответ Telegram
            # Очистка произойдёт при следующем взаимодействии или через /start
        return
    
    # Неизвестный callback
    logger.warning(f"Необработанный callback: {data}, state={state}")
    await query.answer("Неизвестная команда", show_alert=False)

# ========== ТАБЛИЦЫ (ИСПРАВЛЕН N+1) ==========

async def show_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = {p.id: p for p in session.query(Player).all()}
        if not players:
            await update.message.reply_text("📊 Нет данных.", reply_markup=get_main_keyboard())
            return
        
        # Оптимизированный запрос: считаем очки по парам в БД
        from sqlalchemy import case, func
        
        results = session.query(
            func.min(Game.player1_id).label('p1'),
            func.max(Game.player1_id).label('p2'),  # на самом деле нужен GREATEST/LEAST
            func.sum(case((Game.player1_id < Game.player2_id, Game.points_p1), else_=Game.points_p2)).label('tp1'),
            func.sum(case((Game.player1_id < Game.player2_id, Game.points_p2), else_=Game.points_p1)).label('tp2'),
            func.count(Game.id).label('games')
        ).filter(
            Game.winner_id.isnot(None)
        ).group_by(
            func.min(Game.player1_id, Game.player2_id),
            func.max(Game.player1_id, Game.player2_id)
        ).all()
        
        # Упрощённый вариант — просто загружаем все игры и считаем в Python
        # (для небольшого количества игр это быстрее)
        games = session.query(Game).filter(Game.winner_id.isnot(None)).all()
        
        h2h = {}  # (id1, id2) -> (tp1, tp2, games)
        for g in games:
            id1, id2 = min(g.player1_id, g.player2_id), max(g.player1_id, g.player2_id)
            key = (id1, id2)
            if key not in h2h:
                h2h[key] = [0, 0, 0]
            
            if g.player1_id == id1:
                h2h[key][0] += g.points_p1
                h2h[key][1] += g.points_p2
            else:
                h2h[key][0] += g.points_p2
                h2h[key][1] += g.points_p1
            h2h[key][2] += 1
        
        if not h2h:
            await update.message.reply_text("📊 ТУРНИРНАЯ ТАБЛИЦА\n\nПока нет сыгранных игр.", reply_markup=get_main_keyboard())
            return
        
        text = "📊 ТУРНИРНАЯ ТАБЛИЦА (личные встречи)\n\n"
        for (id1, id2), (tp1, tp2, cnt) in sorted(h2h.items(), key=lambda x: -x[1][2]):
            p1_name = players.get(id1, Player(username="?")).username
            p2_name = players.get(id2, Player(username="?")).username
            text += f"{p1_name} — {p2_name}: {tp1}-{tp2} ({cnt} игр)\n"
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
        
    finally:
        session.close()

async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        players = session.query(Player).order_by(Player.points.desc(), Player.games_won.desc()).all()
        if not players:
            await update.message.reply_text("👥 Нет игроков.", reply_markup=get_main_keyboard())
            return
        
        text = "👥 СПИСОК ИГРОКОВ\n\n"
        for i, p in enumerate(players, 1):
            win_rate = (p.games_won / p.games_played * 100) if p.games_played > 0 else 0
            text += (
                f"{i}. {p.username}\n"
                f"   ⭐ {p.points} очк. | {p.games_won} побед"
                f" | {p.mars_won} марсов | {win_rate:.0f}% побед\n\n"
            )
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
        
        # Предзагружаем игроков одним запросом
        player_ids = set()
        for g in games:
            player_ids.update([g.player1_id, g.player2_id, g.winner_id or 0])
        
        players = {p.id: p for p in session.query(Player).filter(Player.id.in_(player_ids)).all()}
        
        text = "📋 ПОСЛЕДНИЕ ИГРЫ:\n\n"
        for g in games:
            p1 = players.get(g.player1_id)
            p2 = players.get(g.player2_id)
            if not p1 or not p2:
                continue
            
            mars = " (МАРС!)" if g.is_mars else ""
            w = players.get(g.winner_id)
            w_text = f" → 🎉 {w.username}{mars}" if w else ""
            
            text += (
                f"📅 {g.game_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"{p1.username} {g.points_p1}-{g.points_p2} {p2.username}{w_text}\n\n"
            )
        
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    finally:
        session.close()

# ========== ЗАПУСК ==========

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("import", import_data))
    app.add_handler(CommandHandler("delete", delete_last))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("БОТ ЗАПУЩЕН!")
    
    # drop_pending_updates=True — игнорируем старые callback'и при перезапуске
    app.run_polling(
        poll_interval=0.5,
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()