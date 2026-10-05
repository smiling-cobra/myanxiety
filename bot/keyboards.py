from telegram import KeyboardButton, ReplyKeyboardMarkup

CHECK_IN = '📝 Check In'
ADD_NOTE = '🗒 Add a note'
HISTORY = '📖 History'
STATS = '📊 Stats'
WEEKLY_SUMMARY = '📈 Weekly Summary'
EXPORT = '📤 Export'
HELP = '❓ Help'
SETTINGS = '⚙️ Settings'
PLUS = '⭐ Plus'
BACK = '🔙 Back'

# The buttons a main-menu keyboard can produce. A keyboard outlives the
# conversation that sent it, so a recovered session needs to recognise them.
MAIN_MENU_CHOICES = (CHECK_IN, ADD_NOTE, HISTORY, STATS, WEEKLY_SUMMARY, EXPORT, SETTINGS, HELP)

# Both labels start an entry. The label is a hint about which kind it will be,
# not the decision: a keyboard does not change at local midnight, so the one
# on screen can still say "Add a note" the next morning. The entry's kind is
# settled when it is saved.
ENTRY_CHOICES = (CHECK_IN, ADD_NOTE)


def get_main_menu_keyboard(checked_in: bool = False):
    return ReplyKeyboardMarkup(
        [[ADD_NOTE if checked_in else CHECK_IN], [HISTORY, STATS], [WEEKLY_SUMMARY, EXPORT], [SETTINGS, HELP]],
        resize_keyboard=True
    )


def get_mood_keyboard():
    return ReplyKeyboardMarkup(
        [['1', '2', '3', '4', '5'], ['6', '7', '8', '9', '10']],
        resize_keyboard=True,
        one_time_keyboard=True
    )


GUIDANCE_YES = '💡 Yes, show me some guidance'
GUIDANCE_NO = "No thanks, I'm done for now"


def get_guidance_keyboard():
    return ReplyKeyboardMarkup(
        [[GUIDANCE_YES], [GUIDANCE_NO]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


THERAPY_YES = 'Yes'
THERAPY_NO = 'No'
THERAPY_UNDISCLOSED = 'Prefer not to say'

# The cohort answer is a closed vocabulary so it can be grouped in analytics.
# "Prefer not to say" is a real answer, distinct from never having been asked —
# a user who skipped is not the same cohort as one onboarded before the
# question existed.
THERAPY_ANSWERS = {
    THERAPY_YES: 'yes',
    THERAPY_NO: 'no',
    THERAPY_UNDISCLOSED: 'undisclosed',
}


def get_therapy_keyboard():
    return ReplyKeyboardMarkup(
        [[THERAPY_YES, THERAPY_NO], [THERAPY_UNDISCLOSED]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


DELETE_YES = '🗑 Yes, delete everything'
DELETE_NO = 'No, keep my journal'


def get_delete_keyboard():
    # Keep first: the button a stray tap is most likely to hit should be the
    # one that changes nothing.
    return ReplyKeyboardMarkup(
        [[DELETE_NO], [DELETE_YES]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


CHANGE_REMINDER_TIME = '🕘 Change reminder time'
PAUSE_REMINDERS = '⏸ Pause reminders'
RESUME_REMINDERS = '▶️ Resume reminders'

# A pause always has an end. There is deliberately no "off": a break that ends
# by itself doesn't rely on anyone remembering to come back and switch it on.
PAUSE_LENGTHS = {
    '3 days': 3,
    '1 week': 7,
    '2 weeks': 14,
}


def get_settings_keyboard(paused: bool):
    return ReplyKeyboardMarkup(
        [[CHANGE_REMINDER_TIME], [RESUME_REMINDERS if paused else PAUSE_REMINDERS], [PLUS], [BACK]],
        resize_keyboard=True,
    )


def get_pause_keyboard():
    return ReplyKeyboardMarkup([list(PAUSE_LENGTHS), [BACK]], resize_keyboard=True, one_time_keyboard=True)


def get_timezone_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton('📍 Share my location', request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton(BACK)]], resize_keyboard=True)
