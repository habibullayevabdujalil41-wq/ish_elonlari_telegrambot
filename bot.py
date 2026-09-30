import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
	int(value.strip())
	for value in os.getenv("ADMIN_IDS", "").split(",")
	if value.strip().isdigit()
}
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
APPROVAL_CHAT_ID = os.getenv("APPROVAL_CHAT_ID", "").strip()
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "jobs.sqlite3"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
router = Router()


class JobForm(StatesGroup):
	title = State()
	description = State()
	category = State()
	location = State()
	salary = State()
	contact = State()
	confirmation = State()


class SearchForm(StatesGroup):
	query = State()


def db_connection() -> sqlite3.Connection:
	connection = sqlite3.connect(DATABASE_PATH)
	connection.row_factory = sqlite3.Row
	return connection


def initialize_database() -> None:
	with db_connection() as connection:
		connection.executescript(
			"""
			CREATE TABLE IF NOT EXISTS users (
				telegram_id INTEGER PRIMARY KEY,
				full_name TEXT NOT NULL,
				username TEXT,
				created_at TEXT NOT NULL
			);
			CREATE TABLE IF NOT EXISTS jobs (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				telegram_id INTEGER NOT NULL,
				title TEXT NOT NULL,
				description TEXT NOT NULL,
				category TEXT NOT NULL,
				location TEXT NOT NULL,
				salary TEXT NOT NULL,
				contact TEXT NOT NULL,
				status TEXT NOT NULL DEFAULT 'pending',
				created_at TEXT NOT NULL
			);
			"""
		)


def save_user(message: Message) -> None:
	user = message.from_user
	with db_connection() as connection:
		connection.execute(
			"""
			INSERT INTO users (telegram_id, full_name, username, created_at)
			VALUES (?, ?, ?, ?)
			ON CONFLICT(telegram_id) DO UPDATE SET full_name = excluded.full_name,
				username = excluded.username
			""",
			(user.id, user.full_name, user.username, datetime.now().isoformat(timespec="seconds")),
		)


def main_keyboard() -> ReplyKeyboardBuilder:
	keyboard = ReplyKeyboardBuilder()
	keyboard.button(text="📋 E'lonlarni ko‘rish")
	keyboard.button(text="➕ E'lon joylash")
	keyboard.button(text="🔎 Qidirish")
	keyboard.button(text="ℹ️ Yordam")
	keyboard.adjust(2, 1, 1)
	return keyboard


def categories_keyboard() -> InlineKeyboardMarkup:
	builder = InlineKeyboardBuilder()
	for category in ("IT", "Savdo", "Xizmat ko‘rsatish", "Ta’lim", "Transport", "Boshqa"):
		builder.button(text=category, callback_data=f"category:{category}")
	builder.adjust(2)
	return builder.as_markup()


def job_text(job: sqlite3.Row) -> str:
	return (
		f"<b>{job['title']}</b>\n\n"
		f"🗂 <b>Yo‘nalish:</b> {job['category']}\n"
		f"📍 <b>Manzil:</b> {job['location']}\n"
		f"💰 <b>Maosh:</b> {job['salary']}\n\n"
		f"{job['description']}\n\n"
		f"📞 <b>Aloqa:</b> {job['contact']}"
	)


def admin_job_keyboard(job_id: int) -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		inline_keyboard=[
			[
				InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve:{job_id}"),
				InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject:{job_id}"),
			]
		]
	)


def job_confirmation_keyboard() -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		inline_keyboard=[
			[
				InlineKeyboardButton(text="✅ Ha", callback_data="job_confirm:yes"),
				InlineKeyboardButton(text="❌ Yo‘q", callback_data="job_confirm:no"),
			]
		]
	)


def collect_approval_targets(admin_ids: set[int], approval_chat_id: str = "", group_chat_id: str = "") -> list[int | str]:
	if approval_chat_id:
		return [approval_chat_id]

	targets: list[int | str] = []
	for admin_id in sorted(admin_ids):
		targets.append(admin_id)
	if group_chat_id:
		targets.append(group_chat_id)
	return targets


async def broadcast_job(bot: Bot, job: sqlite3.Row) -> tuple[int, int]:
	with db_connection() as connection:
		users = connection.execute("SELECT telegram_id FROM users").fetchall()

	sent = 0
	failed = 0
	for user in users:
		telegram_id = user["telegram_id"]
		if telegram_id == job["telegram_id"]:
			continue
		try:
			await bot.send_message(telegram_id, f"📢 <b>Yangi ish e’loni</b>\n\n{job_text(job)}")
			sent += 1
		except Exception:
			failed += 1
			logging.exception("E’lon foydalanuvchiga yuborilmadi: %s", telegram_id)
		await asyncio.sleep(0.05)
	return sent, failed


async def show_jobs(message: Message, category: str | None = None) -> None:
	with db_connection() as connection:
		if category:
			jobs = connection.execute(
				"SELECT * FROM jobs WHERE status = 'approved' AND category = ? ORDER BY id DESC LIMIT 20",
				(category,),
			).fetchall()
		else:
			jobs = connection.execute(
				"SELECT * FROM jobs WHERE status = 'approved' ORDER BY id DESC LIMIT 20"
			).fetchall()
	if not jobs:
		await message.answer("Hozircha bu bo‘limda e’lonlar yo‘q.")
		return
	await message.answer(f"📋 Topilgan e’lonlar: {len(jobs)} ta")
	for job in jobs:
		await message.answer(job_text(job))


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
	await state.clear()
	save_user(message)
	await message.answer(
		"<b>Assalomu alaykum!</b> 👋\n\n"
		"Bu bot orqali ish e’lonlarini ko‘rishingiz, qidirishingiz va yangi e’lon joylashingiz mumkin.",
		reply_markup=main_keyboard().as_markup(resize_keyboard=True),
	)


@router.message(Command("chatid"))
async def chat_id_handler(message: Message) -> None:
	await message.answer(f"Bu chatning ID raqami: <code>{message.chat.id}</code>")


@router.message(F.text == "📋 E'lonlarni ko‘rish")
async def list_jobs_handler(message: Message) -> None:
	await show_jobs(message)


@router.message(F.text == "➕ E'lon joylash")
async def add_job_handler(message: Message, state: FSMContext) -> None:
	await state.set_state(JobForm.title)
	await message.answer("E’lon sarlavhasini kiriting:\nMasalan: Python dasturchi kerak")


@router.message(JobForm.title)
async def job_title_handler(message: Message, state: FSMContext) -> None:
	await state.update_data(title=message.text.strip())
	await state.set_state(JobForm.description)
	await message.answer("Ish haqida batafsil ma’lumot yozing:")


@router.message(JobForm.description)
async def job_description_handler(message: Message, state: FSMContext) -> None:
	await state.update_data(description=message.text.strip())
	await state.set_state(JobForm.category)
	await message.answer("Yo‘nalishni tanlang:", reply_markup=categories_keyboard())


@router.callback_query(JobForm.category, F.data.startswith("category:"))
async def job_category_handler(callback: CallbackQuery, state: FSMContext) -> None:
	category = callback.data.split(":", 1)[1]
	await state.update_data(category=category)
	await state.set_state(JobForm.location)
	await callback.message.edit_text(f"Tanlandi: <b>{category}</b>\n\nIsh manzilini kiriting:")
	await callback.answer()


@router.message(JobForm.location)
async def job_location_handler(message: Message, state: FSMContext) -> None:
	await state.update_data(location=message.text.strip())
	await state.set_state(JobForm.salary)
	await message.answer("Maoshni kiriting:\nMasalan: 8 000 000 - 12 000 000 so‘m")


@router.message(JobForm.salary)
async def job_salary_handler(message: Message, state: FSMContext) -> None:
	await state.update_data(salary=message.text.strip())
	await state.set_state(JobForm.contact)
	await message.answer("Aloqa ma’lumotini kiriting (telefon yoki Telegram username):")


@router.message(JobForm.contact)
async def job_contact_handler(message: Message, state: FSMContext) -> None:
	data = await state.update_data(contact=message.text.strip())
	await state.set_state(JobForm.confirmation)
	await message.answer(
		f"{job_text(data)}\n\n<b>Aniq e’lon joylamoqchimisiz?</b>",
		reply_markup=job_confirmation_keyboard(),
	)


@router.callback_query(JobForm.confirmation, F.data.startswith("job_confirm:"))
async def job_confirmation_handler(callback: CallbackQuery, state: FSMContext) -> None:
	decision = callback.data.split(":", 1)[1]
	if decision == "no":
		await state.clear()
		await callback.message.edit_text("E’lon yuborish bekor qilindi.")
		await callback.answer()
		return
	if decision != "yes":
		await callback.answer("Noma’lum tanlov.", show_alert=True)
		return
	approval_targets = collect_approval_targets(ADMIN_IDS, APPROVAL_CHAT_ID, GROUP_CHAT_ID)
	if not approval_targets:
		await callback.answer("Tasdiqlash uchun chat yoki admin hali sozlanmagan. Keyinroq urinib ko‘ring.", show_alert=True)
		return

	data = await state.get_data()
	now = datetime.now().isoformat(timespec="seconds")
	with db_connection() as connection:
		cursor = connection.execute(
			"""
			INSERT INTO jobs (telegram_id, title, description, category, location, salary, contact, status, created_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
			""",
			(callback.from_user.id, data["title"], data["description"], data["category"],
			 data["location"], data["salary"], data["contact"], now),
		)
		job_id = cursor.lastrowid
		job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
	await state.clear()
	if APPROVAL_CHAT_ID:
		target_name = "tasdiqlash chatiga"
	else:
		target_name = "adminlar va guruhga" if ADMIN_IDS and GROUP_CHAT_ID else "adminlarga" if ADMIN_IDS else "guruhga"
	await callback.message.edit_text(f"E’loningiz {target_name} tasdig‘iga yuborildi.")
	for target in approval_targets:
		try:
			await callback.bot.send_message(
				target,
				f"🆕 <b>Yangi e’lon #{job_id}</b>\n\n{job_text(job)}",
				reply_markup=admin_job_keyboard(job_id),
			)
		except Exception:
			logging.exception("Tasdiqlash chatiga e’lon yuborilmadi: %s", target)
	await callback.answer()


@router.message(F.text == "🔎 Qidirish")
async def search_handler(message: Message, state: FSMContext) -> None:
	await state.set_state(SearchForm.query)
	await message.answer("Qidiruv so‘zini kiriting. Masalan: dizayner, Toshkent yoki Python")


@router.message(SearchForm.query)
async def search_query_handler(message: Message, state: FSMContext) -> None:
	query = f"%{message.text.strip()}%"
	with db_connection() as connection:
		jobs = connection.execute(
			"""
			SELECT * FROM jobs
			WHERE status = 'approved' AND (title LIKE ? OR description LIKE ? OR location LIKE ? OR category LIKE ?)
			ORDER BY id DESC LIMIT 20
			""",
			(query, query, query, query),
		).fetchall()
	await state.clear()
	if not jobs:
		await message.answer("🔎 Hech narsa topilmadi. Boshqa so‘z bilan urinib ko‘ring.")
		return
	await message.answer(f"🔎 Qidiruv natijasi: {len(jobs)} ta")
	for job in jobs:
		await message.answer(job_text(job))


@router.message(F.text == "ℹ️ Yordam")
async def help_handler(message: Message) -> None:
	await message.answer(
		"<b>Botdan foydalanish:</b>\n\n"
		"📋 E’lonlarni ko‘rish — tasdiqlangan vakansiyalar\n"
		"➕ E’lon joylash — yangi ish e’loni yuborish\n"
		"🔎 Qidirish — kalit so‘z bo‘yicha qidirish\n\n"
		"Savollar bo‘lsa, administratorga murojaat qiling."
	)


@router.callback_query(F.data.startswith("approve:"))
async def approve_handler(callback: CallbackQuery) -> None:
	if callback.from_user.id != OWNER_ID:
		await callback.answer("Sizda bu amal uchun ruxsat yo‘q.", show_alert=True)
		return
	job_id = int(callback.data.split(":")[1])
	with db_connection() as connection:
		cursor = connection.execute(
			"UPDATE jobs SET status = 'approved' WHERE id = ? AND status = 'pending'",
			(job_id,),
		)
		job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
	if cursor.rowcount == 0 or not job:
		await callback.answer("Bu e’lon avval ko‘rib chiqilgan yoki topilmadi.", show_alert=True)
		return
	await callback.message.edit_reply_markup(reply_markup=None)
	await callback.answer()
	sent, failed = await broadcast_job(callback.bot, job)
	try:
		await callback.bot.send_message(
			job["telegram_id"],
			f"✅ E’loningiz tasdiqlandi va foydalanuvchilarga yuborildi.\n\n{job_text(job)}",
		)
	except Exception:
		logging.exception("E’lon egasiga xabar yuborilmadi")
	await callback.message.answer(
		f"✅ E’lon #{job_id} tasdiqlandi. {sent} ta foydalanuvchiga yuborildi; muvaffaqiyatsiz: {failed}."
	)


@router.callback_query(F.data.startswith("reject:"))
async def reject_handler(callback: CallbackQuery) -> None:
	if callback.from_user.id != OWNER_ID:
		await callback.answer("Sizda bu amal uchun ruxsat yo‘q.", show_alert=True)
		return
	job_id = int(callback.data.split(":")[1])
	with db_connection() as connection:
		cursor = connection.execute(
			"UPDATE jobs SET status = 'rejected' WHERE id = ? AND status = 'pending'",
			(job_id,),
		)
		job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
	if cursor.rowcount == 0 or not job:
		await callback.answer("Bu e’lon avval ko‘rib chiqilgan yoki topilmadi.", show_alert=True)
		return
	await callback.message.edit_reply_markup(reply_markup=None)
	await callback.message.answer(f"❌ E’lon #{job_id} rad etildi.")
	try:
		await callback.bot.send_message(job["telegram_id"], "❌ E’loningiz rad etildi. Ma’lumotlarni tekshirib, qayta yuborishingiz mumkin.")
	except Exception:
		logging.exception("E’lon egasiga xabar yuborilmadi")
	await callback.answer()


async def main() -> None:
	if not BOT_TOKEN:
		raise RuntimeError("BOT_TOKEN .env faylida ko‘rsatilmagan")
	initialize_database()
	bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
	dispatcher = Dispatcher()
	dispatcher.include_router(router)
	logging.info("Bot ishga tushdi")
	await dispatcher.start_polling(bot)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except (KeyboardInterrupt, SystemExit):
		logging.info("Bot to‘xtatildi")
