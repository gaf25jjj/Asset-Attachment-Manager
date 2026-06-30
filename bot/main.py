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
    """Инициализация базы данных и создание таблицы topics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            user_id  INTEGER PRIMARY KEY,
            topic_id INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_topic(user_id: int, topic_id: int):
    """Сохранить связку user_id ↔ topic_id."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO topics (user_id, topic_id) VALUES (?, ?)",
        (user_id, topic_id),
    )
    conn.commit()
    conn.close()


def get_topic_id(user_id: int) -> int | None:
    """Найти topic_id по user_id. Возвращает None, если запись не найдена."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT topic_id FROM topics WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_user_id(topic_id: int) -> int | None:
    """Найти user_id по topic_id. Возвращает None, если запись не найдена."""
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


def ensure_topic(user: types.User) -> int:
    """
    Вернуть существующий topic_id или создать новую тему в админ-группе.
    """
    topic_id = get_topic_id(user.id)
    if topic_id:
        return topic_id

    display_name = get_display_name(user)
    topic_name = f"{display_name} | {user.id}"

    # Создаём тему (Forum Topic) в супергруппе
    forum_topic = bot.create_forum_topic(ADMIN_GROUP_ID, topic_name)
    topic_id = forum_topic.message_thread_id

    # Сохраняем связку в БД
    save_topic(user.id, topic_id)

    # Системное сообщение в тему
    username_part = f"@{user.username}" if user.username else ""
    bot.send_message(
        ADMIN_GROUP_ID,
        f"🆕 <b>Новое обращение</b>\n"
        f"👤 <b>Имя:</b> {display_name} {username_part}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>",
        message_thread_id=topic_id,
        parse_mode="HTML",
    )

    return topic_id


# ─────────────────────────────────────────────
# Обработчики сообщений от ПОЛЬЗОВАТЕЛЕЙ
# ─────────────────────────────────────────────
ALLOWED_CONTENT_TYPES = ["text", "photo", "video", "document", "voice"]


@bot.message_handler(
    func=lambda msg: msg.chat.type == "private",
    content_types=ALLOWED_CONTENT_TYPES,
)
def handle_user_message(message: types.Message):
    """Принимаем сообщение от пользователя и пересылаем в нужную тему."""
    user = message.from_user
    topic_id = ensure_topic(user)

    # Пересылаем оригинальное сообщение в тему
    bot.forward_message(
        chat_id=ADMIN_GROUP_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        message_thread_id=topic_id,
    )


# ─────────────────────────────────────────────
# Обработчики сообщений от АДМИНИСТРАТОРОВ
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
        # Тема не связана ни с каким пользователем — игнорируем
        return

    try:
        if message.content_type == "text":
            # Для текста — отправляем напрямую
            bot.send_message(user_id, message.text)
        else:
            # Для медиа — копируем сообщение
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
    except telebot.apihelper.ApiTelegramException as e:
        # Если пользователь заблокировал бота — уведомляем админов в теме
        error_text = (
            f"⚠️ <b>Не удалось доставить сообщение</b>\n"
            f"Пользователь (ID: <code>{user_id}</code>) заблокировал бота.\n"
            f"<i>Ошибка: {e}</i>"
        )
        bot.send_message(
            ADMIN_GROUP_ID,
            error_text,
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
