"""Localizable user-facing moderation strings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModerationTexts:
    """Ukrainian text catalog for Telegram-visible messages."""

    reply_required: str = (
        "Цю команду потрібно використовувати у відповіді на повідомлення."
    )
    admin_required: str = "Цю команду можуть використовувати лише адміністратори чату."
    member_status_unavailable: str = (
        "Зараз не вдалося перевірити статус адміністратора. Спробуйте ще раз."
    )
    bot_permissions_required: str = (
        "Боту потрібні права адміністратора для видалення повідомлень і "
        "обмеження користувачів."
    )
    unsupported_sender: str = "Не підтримується цей тип відправника Telegram."
    user_already_restricted: str = "Цей користувач вже має активне обмеження."
    target_is_administrator: str = "Адміністратора не можна обмежити."
    moderation_failed: str = (
        "Не вдалося виконати дію модерації. Спробуйте ще раз або перевірте "
        "права бота."
    )
    action_unavailable: str = "Ця дія більше недоступна."
    callback_admin_only: str = "Зняти це обмеження може лише адміністратор чату."
    admin_contact_unavailable: str = (
        "З цим адміністратором неможливо зв'язатися через Telegram."
    )
    punishment_notification: str = (
        "{mention}, ви порушили правила.\n" "Вас обмежено на {days} днів."
    )
    released_notification: str = "{mention}, ваше обмеження знято."
    vote_already_active: str = "Для цього користувача вже триває голосування спільноти."
    vote_duplicate: str = "Ви вже проголосували."
    vote_failed: str = "Не вдалося зарахувати голос. Спробуйте ще раз."
    admin_rate_limited: str = "Забагато дій модерації. Спробуйте ще раз за хвилину."
    community_vote_rate_limited: str = (
        "Забагато голосувань у цьому чаті. Спробуйте ще раз за хвилину."
    )
    community_vote_started: str = (
        "⚠️ Розпочато голосування спільноти.\n\n"
        "Користувача {mention} повідомлено за порушення правил чату.\n\n"
        "Якщо ви підтримуєте обмеження цього користувача на {days} днів, "
        "проголосуйте нижче.\n\n"
        "Голоси: {votes_count} / {votes_required}\n\n"
        "Голосування завершується через {minutes} хвилин."
    )
    community_vote_completed: str = (
        "✅ Голосування завершено.\n\n" "Голоси: {votes_count} / {votes_required}"
    )
    community_vote_expired: str = (
        "❌ Голосування завершено.\n\n"
        "Потрібну кількість голосів не набрано.\n\n"
        "Фінальний результат:\n"
        "{votes_count} / {votes_required}"
    )
    activation_required: str = (
        "Спочатку адміністратор чату має підтвердити обов'язкову підписку."
    )
    subscription_admin_only: str = "Активувати бота може лише адміністратор цього чату."
    subscription_required: str = "❌ Ви повинні бути підписані на чат та канал."
    subscription_configuration_missing: str = (
        "Обов'язкова підписка налаштована некоректно."
    )
    subscription_check_failed: str = "Не вдалося перевірити підписку. Спробуйте ще раз."
    subscription_prompt: str = (
        "Для використання бота адміністратор повинен бути підписаний " "на чат і канал."
    )
    subscription_confirmed: str = (
        "✅ Підписку підтверджено.\n\n" "Бот готовий до роботи."
    )
    bot_permission_warning: str = (
        "Для роботи боту потрібні права адміністратора: видалення повідомлень "
        "і обмеження користувачів. Надайте їх у налаштуваннях чату."
    )


TEXTS = ModerationTexts()
