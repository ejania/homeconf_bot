# User-facing messages

WELCOME_MESSAGE = (
    "Привет, я бот для регистрации на домконфу!\n\n"
    "Команды:\n"
    "/register - Поучаствовать в лотерее на место слушателя\n"
    "/status - Узнать мой статус\n"
    "/unregister - Не смогу прийти, отдаю своё место\n"
    "/list - Показать, как идёт регистрация\n"
    "/invite - Позвать гостя (только для спикеров)\n\n"
    "Команды админа:\n"
    "/create <группа_спикеров> - Подготовить событие (пре-регистрация)\n"
    "/open <часы> <места> [таймаут_ожидания_ч] - Открыть общую регистрацию\n"
    "/close - Закрыть регистрацию (досрочно)\n"
    "/send_invites - Разослать приглашения после лотереи (админ)\n"
    "/reset - Сбросить все регистрации для текущего события"
)

# Errors & Warnings
ONLY_ADMIN_OPEN = "Открыть регистрацию может только админ."
ONLY_ADMIN_CLOSE = "Закрыть регистрацию может только админ."
ONLY_ADMIN_SEND_INVITES = "Разослать приглашения может только админ."
REGISTRATION_ALREADY_OPEN = "❌ Регистрация или пре-регистрация уже активна."
USAGE_CREATE = "Используй так: /create <группа_спикеров>"
USAGE_OPEN = "Используй так: /open <часы_регистрации> <места> <дата_события> <время_события>\nПример: /open 24 20 2026-03-15 18:00"
INVITE_ONLY_PRE_OPEN = "Позвать гостя можно только до открытия общей регистрации."
EVENT_CREATED = "Событие создано! Статус: PRE_OPEN. Спикеры могут звать гостей. Чтобы открыть для всех, напиши /open <часы_регистрации> <места> <дата_события> <время_события>."
NO_PRE_OPEN_EVENT = "Нет события в статусе PRE_OPEN. Создай его через /create."
ERROR_ACCESS_GROUP = "❌ Ошибка: Не могу доступиться до группы. Проверь, что бот там есть и ID/юзернейм верные."
NO_OPEN_REGISTRATION = "Сейчас нет открытой регистрации."
NO_REVIEW_EVENT = "Нет событий в статусе REVIEW. Сначала закрой регистрацию через /close."
NO_EVENT_FOUND = "Событие не найдено."
ALREADY_SPEAKER = "Ты же докладчик или докладчица! Тебе регистрация не нужна :)"
ALREADY_REGISTERED = "Ты уже в деле (зарегистрирован или в листе ожидания)."
ALREADY_INVITED_HAS_PLACE = "Тебя уже позвал кто-то из докладчиков или докладчиц, место за тобой!"
START_IN_PRIVATE = "Напиши мне в личку, чтобы я мог присылать тебе уведомления!"
ONLY_SPEAKERS_INVITE = "Только докладчики и докладчицы могут звать гостей."
ALREADY_INVITED_GUEST = "Твой гость уже зарегистрировался. Сорри, поменять нельзя."
USAGE_INVITE = "Используй так: /invite <юзернейм> (например, /invite ejania)"
GUEST_ALREADY_GUEST = "@{username} уже записан чьим-то гостем."
GUEST_IS_SPEAKER = "@{username} и так докладчик или докладчица!"
GUEST_ALREADY_HAS_SPOT = "У @{username} уже и так есть место."
GUEST_REPLACED = "Твой предыдущий гость (@{old_username}) был удален из приглашений."
NO_ACTIVE_REGISTRATION = "У тебя нет активных регистраций."
INVALID_INVITATION = "Приглашение уже недействительно или протухло."
NOT_REGISTERED = "Ты пока не регистрировался."
NO_EVENTS_FOUND = "Событий пока нет."
EVENT_NOT_STARTED = "Событие ещё не началось."
PRIVATE_CHAT_ONLY = "Эту команду /{command} лучше использовать в личке со мной."
SPEAKER_UNREGISTER_ERROR = "Если ты передумал выступать, напиши, пожалуйста, организаторам напрямую. Я тут бессилен 🤷‍♂️"

# Success Messages
REGISTRATION_OPENED = (
    "✅ Регистрация открыта на {places} мест!\n"
    "Закроется в: {end_time}."
)
REGISTRATION_CLOSED_MANUAL = "Регистрация закрыта вручную."
REGISTRATION_CLOSED_NO_REG = "Регистрация закрыта. Никто не пришел :("
REGISTRATION_CLOSED_SUMMARY = "Регистрация закрыта! {winners} человек получили места. {waitlist} — в листе ожидания."
LOTTERY_READY_FOR_REVIEW = "Лотерея проведена! Результаты готовы к проверке. Используй /send_invites для рассылки уведомлений."
SEND_INVITES_SUCCESS = "Уведомления отправлены! Регистрация официально закрыта."

REGISTER_SUCCESS_LOTTERY = "Записал тебя! Маякнем здесь, как пройдет лотерея."
REGISTER_SUCCESS_PUBLIC = "@{username} в игре!"
REGISTER_WAITLIST = "Добавил тебя в лист ожидания на позицию №{position}."
REGISTER_WAITLIST_PUBLIC = "@{username} теперь в листе ожидания."

GUEST_IDENTIFIED = "О, ты гость! Место подтверждено, всё чётко."
GUEST_UPGRADED = "@{username} теперь идет как гость!"
GUEST_INVITED_NOTIFY = "Спикер {speaker} позвал тебя гостем! Место теперь гарантировано."
GUEST_INVITED_NEW = "@{username} приглашен! Место забронировано. Скажи ему нажать /register, чтобы бот мог присылать обновления."

UNREGISTERED_SUCCESS = "Ок, вычеркнул тебя."
UNREGISTER_CONFIRM = "Точно хочешь отменить регистрацию? Регистрация уже закрыта, так что передумать и вернуться не получится."
INVITATION_ACCEPTED = "Принято! Ждем тебя."
INVITATION_DECLINED = "Понял, отказываемся."

# Notifications
LOTTERY_WINNER = "Ура! Тебе досталось место на домконфе! 🎉"
WAITLIST_NOTIFICATION = "Пока ты в листе ожидания. Твой номер: {position}."
INVITATION_EXPIRED = "К сожалению, время на ответ вышло, и твоё приглашение аннулировано. Мы передали место следующему человеку из листа ожидания. Надеемся увидеть тебя в другой раз! ❤️"
SPOT_OPENED_INVITE = "Освободилось место! Пойдешь? (Нужно ответить за {hours} ч.)"

# Status & List
STATUS_MSG = "Твой статус: {status}"
WAITLIST_POSITION = "\nМесто в очереди: {position}"
EVENT_STATUS_HEADER = (
    "📊 *Статус: {status}*\n\n"
    "🌟 *VIP-места (спикеры + гости):* {vip_taken}\n"
    "🎟 *Общие места:* {general_taken}/{general_total}\n"
)
EVENT_STATUS_HEADER_PRE_OPEN = (
    "📊 *Статус: {status}*\n\n"
    "🌟 *VIP-места (спикеры + гости):* {vip_taken}\n"
)
EVENT_STATUS_PRE_OPEN = "Регистрация пока закрыта. Спикеры могут звать гостей."
EVENT_STATUS_OPEN = "Участников в лотерее: {count}\n\nЛотерея запустится, когда регистрация закроется."
EVENT_REGISTRATION_ENDS = "\nРегистрация закроется в: {end_time} (CET/CEST)"
EVENT_STATUS_REVIEW = "Лотерея проведена, ждем подтверждения админа.\n"
EVENT_STATUS_CLOSED = "Человек в листе ожидания: {waitlist}\n"
EVENT_STATUS_PENDING = "Ожидают подтверждения: {invited}\n"

STATUS_REGISTERED = "Записан в пул лотереи"
STATUS_INVITED = "Приглашен (ожидаем подтверждения)"
STATUS_ACCEPTED = "Идешь на конфу!"
STATUS_WAITLIST = "В листе ожидания"
STATUS_UNREGISTERED = "Отказался от участия"
STATUS_EXPIRED = "Приглашение протухло"
STATUS_SPEAKER = "Докладчик или докладчица"

# Command descriptions
DESC_START = "Запустить бота и получить приветствие"
DESC_REGISTER = "Записаться на конфу"
DESC_STATUS = "Узнать, как там моя регистрация"
DESC_UNREGISTER = "Отказаться от участия"
DESC_LIST = "Посмотреть общую статистику"
DESC_INVITE = "Позвать гостя (только для спикеров)"
DESC_CREATE = "Создать событие (админ)"
DESC_OPEN = "Открыть регистрацию (админ)"
DESC_CLOSE = "Закрыть регистрацию (админ)"
DESC_SEND_INVITES = "Разослать приглашения после лотереи (админ)"
DESC_RESET = "Сбросить все регистрации (админ)"

RESET_CONFIRMATION = "⚠️ Ты уверен, что хочешь сбросить ВСЕ регистрации для этого события? Это действие необратимо. Напиши `/reset confirm` для подтверждения."
RESET_SUCCESS = "✅ Все регистрации сброшены. Статистика очищена."
ONLY_ADMIN_RESET = "Сбросить регистрации может только админ."
