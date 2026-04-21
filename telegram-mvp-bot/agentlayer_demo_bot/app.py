from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Settings, load_settings
from .logic import (
    balance_text,
    build_preview,
    compare_text,
    format_amount,
    history_text,
    payload_to_transaction,
    portfolio_text,
    preview_to_payload,
)
from .models import ParsedIntent
from .openrouter_client import OpenRouterClient
from .parsing import fallback_parse_intent
from .storage import Storage


LOGGER = logging.getLogger("agentlayer_demo_bot")


class BotRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.openrouter = OpenRouterClient(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
        )

    def ensure_user(self, telegram_user_id: int, username: str | None) -> int:
        return self.storage.get_or_create_user(telegram_user_id, username)


def confirm_keyboard(pending_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"confirm:{pending_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"cancel:{pending_id}"),
            ]
        ]
    )


async def resolve_intent(runtime: BotRuntime, message_text: str, clarification_context: dict | None = None) -> ParsedIntent:
    context_note = None
    if clarification_context:
        context_note = (
            "Resolve the original incomplete request using the prior clarification state.\n"
            f"Original request: {clarification_context.get('original_message')}\n"
            f"Missing field note: {clarification_context.get('clarifying_question')}\n"
            f"User clarification answer: {message_text}"
        )

    try:
        return await runtime.openrouter.parse_intent(message_text, context_note=context_note)
    except Exception as exc:  # pragma: no cover - network fallback path
        LOGGER.warning("OpenRouter parse failed, using fallback parser: %s", exc)
        fallback = fallback_parse_intent(message_text)
        if fallback:
            return fallback
        raise


def build_help_text() -> str:
    return (
        "Примеры запросов:\n"
        "- Обмени 10000 RUB на USDT\n"
        "- Купи BTC на 25000 RUB\n"
        "- Купи TSLAx на 50000 RUB\n"
        "- Что выгоднее купить на 100000 RUB - BTC или SOL?\n\n"
        "Команды:\n"
        "/balance\n"
        "/portfolio\n"
        "/history\n"
        "/reset"
    )


def build_chat_context(runtime: BotRuntime, user_id: int) -> str:
    balances = runtime.storage.get_balances(user_id)
    portfolio_hint = (
        f"Current demo balances: RUB={format_amount(float(balances.get('RUB', 0.0)), 'RUB')}, "
        f"USDT={format_amount(float(balances.get('USDT', 0.0)), 'USDT')}, "
        f"BTC={format_amount(float(balances.get('BTC', 0.0)), 'BTC')}, "
        f"SOL={format_amount(float(balances.get('SOL', 0.0)), 'SOL')}, "
        f"TSLAx={format_amount(float(balances.get('TSLAX', 0.0)), 'TSLAX')}, "
        f"NVDAx={format_amount(float(balances.get('NVDAX', 0.0)), 'NVDAX')}."
    )
    return (
        "This bot supports natural conversation and demo finance actions. "
        "Supported commands: /balance, /portfolio, /history, /reset. "
        "Supported actions: swap and buy_asset. "
        + portfolio_hint
    )


async def build_conversational_reply(runtime: BotRuntime, user_id: int, message_text: str) -> str:
    try:
        reply = await runtime.openrouter.chat_reply(
            message_text,
            context_note=build_chat_context(runtime, user_id),
        )
        if reply:
            return reply
    except Exception as exc:  # pragma: no cover - network fallback path
        LOGGER.warning("OpenRouter chat failed, using local fallback: %s", exc)

    lowered = message_text.lower()
    if "привет" in lowered or "здрав" in lowered:
        return "Привет. Я demo-бот AgentLayer: могу показать портфель, подготовить демо-обмен или демо-покупку актива."
    if "что ты умеешь" in lowered or "что умеешь" in lowered:
        return (
            "Я умею показывать демо-баланс и портфель, делать preview обмена и покупки актива, "
            "а потом применять виртуальную операцию по подтверждению. Попробуй: "
            "`Обмени 10000 RUB на USDT` или `Купи TSLAx на 50000 RUB`."
        )
    return (
        "Могу поговорить о demo-сценарии и подготовить виртуальную финансовую операцию. "
        "Попробуй спросить про портфель или напиши: `Купи BTC на 25000 RUB`."
    )


def build_start_text() -> str:
    return (
        "AgentLayer demo bot готов.\n"
        "Это виртуальный финансовый сценарий без реальных денег и без onchain.\n\n"
        "Стартовый баланс уже создан.\n"
        "Попробуйте:\n"
        "- Обмени 10000 RUB на USDT\n"
        "- Купи BTC на 25000 RUB\n"
        "- Купи TSLAx на 50000 RUB"
    )


def configure_router(runtime: BotRuntime) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def handle_start(message: Message) -> None:
        runtime.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(build_start_text())

    @router.message(Command("help"))
    async def handle_help(message: Message) -> None:
        runtime.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(build_help_text())

    @router.message(Command("balance"))
    async def handle_balance(message: Message) -> None:
        user_id = runtime.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(balance_text(runtime.storage.get_balances(user_id)))

    @router.message(Command("portfolio"))
    async def handle_portfolio(message: Message) -> None:
        user_id = runtime.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(portfolio_text(runtime.storage.get_balances(user_id)))

    @router.message(Command("history"))
    async def handle_history(message: Message) -> None:
        user_id = runtime.ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(history_text(runtime.storage.list_transactions(user_id)))

    @router.message(Command("reset"))
    async def handle_reset(message: Message) -> None:
        user_id = runtime.ensure_user(message.from_user.id, message.from_user.username)
        runtime.storage.reset_user(user_id)
        await message.answer("Демо-состояние сброшено к стартовому портфелю.")

    @router.callback_query(F.data.startswith("confirm:"))
    async def handle_confirm(callback: CallbackQuery) -> None:
        user_id = runtime.ensure_user(callback.from_user.id, callback.from_user.username)
        pending_id = int(callback.data.split(":", 1)[1])
        pending = runtime.storage.get_pending_action(user_id, pending_id)
        if not pending or pending.action_type != "preview":
            await callback.answer("Preview уже истек или не найден.", show_alert=True)
            return

        balances = runtime.storage.get_balances(user_id)
        payload = pending.payload
        from_asset = str(payload["from_asset"])
        from_amount = float(payload["from_amount"])
        if float(balances.get(from_asset, 0.0)) < from_amount:
            runtime.storage.clear_pending_actions(user_id, pending_id)
            await callback.message.answer("Баланс уже недостаточен для этой демо-операции.")
            await callback.answer()
            return

        runtime.storage.replace_balances(user_id, dict(payload["balances_after"]))
        runtime.storage.insert_transaction(user_id, payload_to_transaction(payload))
        runtime.storage.clear_pending_actions(user_id, pending_id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"Готово. Демо-операция выполнена: "
            f"{payload['operation_type']} {payload['to_asset']} на {payload['from_amount']:.2f} {payload['from_asset']}. "
            "Баланс обновлен."
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("cancel:"))
    async def handle_cancel(callback: CallbackQuery) -> None:
        user_id = runtime.ensure_user(callback.from_user.id, callback.from_user.username)
        pending_id = int(callback.data.split(":", 1)[1])
        runtime.storage.clear_pending_actions(user_id, pending_id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Демо-операция отменена.")
        await callback.answer()

    @router.message()
    async def handle_text(message: Message) -> None:
        if not message.text:
            await message.answer("Поддерживаются только текстовые сообщения.")
            return

        user_id = runtime.ensure_user(message.from_user.id, message.from_user.username)
        clarification = runtime.storage.get_pending_action(user_id)
        clarification_context = clarification.payload if clarification and clarification.action_type == "clarification" else None

        try:
            intent = await resolve_intent(runtime, message.text, clarification_context=clarification_context)
        except Exception:
            await message.answer(
                "Не удалось разобрать запрос. Попробуйте одну из форм:\n"
                "- Обмени 10000 RUB на USDT\n"
                "- Купи BTC на 25000 RUB"
            )
            return

        if clarification and clarification.action_type == "clarification":
            runtime.storage.clear_pending_actions(user_id, clarification.id)

        if intent.intent == "help":
            if intent.assistant_summary:
                await message.answer(f"{intent.assistant_summary}\n\n{build_help_text()}")
            else:
                await message.answer(build_help_text())
            return
        if intent.intent in {"chat", "unknown"}:
            reply = await build_conversational_reply(runtime, user_id, message.text)
            await message.answer(reply)
            return
        if intent.intent == "balance":
            await message.answer(balance_text(runtime.storage.get_balances(user_id)))
            return
        if intent.intent == "portfolio":
            await message.answer(portfolio_text(runtime.storage.get_balances(user_id)))
            return
        if intent.intent == "history":
            await message.answer(history_text(runtime.storage.list_transactions(user_id)))
            return
        if intent.intent == "compare":
            if intent.amount is None or not intent.payment_asset or not intent.target_asset or not intent.compare_asset:
                await message.answer("Для сравнения укажите бюджет, валюту и два актива.")
                return
            await message.answer(
                compare_text(
                    intent.amount,
                    intent.payment_asset,
                    intent.target_asset,
                    intent.compare_asset,
                )
            )
            return

        if intent.needs_clarification:
            pending = runtime.storage.put_pending_action(
                user_id=user_id,
                action_type="clarification",
                payload={
                    "original_message": message.text,
                    "intent": intent.intent,
                    "target_asset": intent.target_asset,
                    "payment_asset": intent.payment_asset,
                    "amount": intent.amount,
                    "clarifying_question": intent.clarifying_question,
                },
            )
            await message.answer(intent.clarifying_question or "Уточните запрос.")
            return

        if intent.intent not in {"swap", "buy_asset"}:
            reply = await build_conversational_reply(runtime, user_id, message.text)
            await message.answer(reply)
            return

        try:
            preview = build_preview(intent, runtime.storage.get_balances(user_id))
        except ValueError as exc:
            await message.answer(str(exc))
            return

        pending = runtime.storage.put_pending_action(
            user_id=user_id,
            action_type="preview",
            payload=preview_to_payload(preview),
        )
        await message.answer(preview.summary, reply_markup=confirm_keyboard(pending.id))

    return router


async def async_main() -> None:
    settings = load_settings()
    runtime = BotRuntime(settings)
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(configure_router(runtime))
    await dispatcher.start_polling(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(async_main())
