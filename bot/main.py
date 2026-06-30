import os
import sqlite3
import telebot
from telebot import types

# ─────────────────────────────────────────────
# Константы — берутся из переменных окружения
# ─────────────────────────────────────────────
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_GROUP_ID = int(os.environ["ADMIN_GROUP_ID"])

bot = telebot.TeleBot(TOKEN)

# ─────────────────────────────────────────────
# База данных SQLite
# ─────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "support.db")


def init_db():
    """Инициализация БД. ticket_number — автоматический порядковый номер обращения."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Основная таблица: ticket_number — уникальный номер обращения (AUTOINCREMENT)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            ticket_number INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER UNIQUE NOT NULL,
            topic_id      INTEGER NOT NULL
        )
    """)
    # Миграция: если таблица создана со старой схемой (user_id PRIMARY KEY) — пересоздаём
    cursor.execute("PRAGMA table_info(topics)")
    columns = {row[1] for row in cursor.fetchall()}
    if "ticket_number" not in columns:
        cursor.execute("DROP TABLE topics")
        cursor.execute("""
            CREATE TABLE topics (
                ticket_number INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER UNIQUE NOT NULL,
                topic_id      INTEGER NOT NULL
            )
        """)
    conn.commit()
    conn.close()


def save_topic(user_id: int, topic_id: int) -> int:
    """Сохранить связку и вернуть номер обращения (ticket_number)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO topics (user_id, topic_id) VALUES (?, ?)",
        (user_id, topic_id),
    )
    ticket_number = cursor.lastrowid
    conn.commit()
    conn.close()
    return ticket_number


def get_topic_id(user_id: int) -> int | None:
    """Найти topic_id по user_id."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT topic_id FROM topics WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_user_id(topic_id: int) -> int | None:
    """Найти user_id по topic_id."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM topics WHERE topic_id = ?", (topic_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────
def get_display_name(user: types.User) -> str:
    """Получить читаемое имя пользователя."""
    name = user.first_name or ""
    if user.last_name:
        name += f" {user.last_name}"
    return name.strip() or f"user_{user.id}"


def ensure_topic(user: types.User) -> tuple[int, int | None]:
    """
    Вернуть (topic_id, ticket_number).
    ticket_number = None если тема уже существовала (повторное обращение).
    """
    topic_id = get_topic_id(user.id)
    if topic_id:
        return topic_id, None  # Уже существует — номер не нужен

    display_name = get_display_name(user)
    topic_name = f"{display_name} | {user.id}"

    # Создаём тему (Forum Topic) в супергруппе
    forum_topic = bot.create_forum_topic(ADMIN_GROUP_ID, topic_name)
    topic_id = forum_topic.message_thread_id

    # Сохраняем в БД, получаем номер обращения
    ticket_number = save_topic(user.id, topic_id)

    # Системное сообщение в тему для админов
    username_part = f"@{user.username}" if user.username else ""
    bot.send_message(
        ADMIN_GROUP_ID,
        f"🆕 <b>Новое обращение #{ticket_number:06d}</b>\n"
        f"👤 <b>Имя:</b> {display_name} {username_part}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>",
        message_thread_id=topic_id,
        parse_mode="HTML",
    )

    return topic_id, ticket_number


# ─────────────────────────────────────────────
# /start — приветствие и приглашение написать
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def handle_start(message: types.Message):
    """Приветствуем пользователя и просим описать проблему."""
    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать в поддержку!\n\n"
        "Пожалуйста, опишите вашу проблему или вопрос — и мы передадим его специалистам.\n\n"
        "✍️ <b>Напишите ваш вопрос в следующем сообщении.</b>",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# Сообщения от ПОЛЬЗОВАТЕЛЕЙ
# ─────────────────────────────────────────────
ALLOWED_CONTENT_TYPES = ["text", "photo", "video", "document", "voice"]


@bot.message_handler(
    func=lambda msg: msg.chat.type == "private",
    content_types=ALLOWED_CONTENT_TYPES,
)
def handle_user_message(message: types.Message):
    """Принимаем сообщение от пользователя и пересылаем в нужную тему."""
    user = message.from_user
    topic_id, ticket_number = ensure_topic(user)

    # Пересылаем сообщение в тему
    bot.forward_message(
        chat_id=ADMIN_GROUP_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        message_thread_id=topic_id,
    )

    # Подтверждение только при первом сообщении (новый тикет)
    if ticket_number is not None:
        bot.send_message(
            message.chat.id,
            f"📨 <b>Спасибо! Ваш запрос успешно зафиксирован.</b>\n\n"
            f"🎫 Номер обращения: <b>#{ticket_number:06d}</b>\n\n"
            f"Мы уже передали его специалистам технической поддержки. "
            f"Обычно ответ занимает всего несколько минут.\n\n"
            f"Пожалуйста, не отправляйте повторные сообщения — это может увеличить время обработки.\n\n"
            f"Благодарим за выбор нашего VPN! 💙",
            parse_mode="HTML",
        )


# ─────────────────────────────────────────────
# Сообщения от АДМИНИСТРАТОРОВ
# ─────────────────────────────────────────────
@bot.message_handler(
    func=lambda msg: (
        msg.chat.id == ADMIN_GROUP_ID
        and msg.is_topic_message
        and msg.message_thread_id is not None
    ),
    content_types=["text", "photo", "video", "document", "voice",
                   "sticker", "audio", "animation"],
)
def handle_admin_message(message: types.Message):
    """Принимаем ответ администратора в теме и отправляем пользователю."""
    topic_id = message.message_thread_id
    user_id = get_user_id(topic_id)

    if user_id is None:
        return

    try:
        if message.content_type == "text":
            bot.send_message(user_id, message.text)
        else:
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
    except telebot.apihelper.ApiTelegramException as e:
        bot.send_message(
            ADMIN_GROUP_ID,
            f"⚠️ <b>Не удалось доставить сообщение</b>\n"
            f"Пользователь (ID: <code>{user_id}</code>) заблокировал бота.\n"
            f"<i>Ошибка: {e}</i>",
            message_thread_id=topic_id,
            parse_mode="HTML",
        )


# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print(f"Бот запущен. Группа администраторов: {ADMIN_GROUP_ID}")
    bot.polling(none_stop=True, interval=0)
