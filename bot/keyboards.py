from telegram import KeyboardButton, ReplyKeyboardMarkup

CHECK_IN = '📝 Check In'
HISTORY = '📖 History'
STATS = '📊 Stats'
WEEKLY_SUMMARY = '📈 Weekly Summary'
HELP = '❓ Help'
BACK = '🔙 Back'

# The buttons a main-menu keyboard can produce. A keyboard outlives the
# conversation that sent it, so a recovered session needs to recognise them.
MAIN_MENU_CHOICES = (CHECK_IN, HISTORY, STATS, WEEKLY_SUMMARY, HELP)


def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[CHECK_IN], [HISTORY, STATS], [WEEKLY_SUMMARY], [HELP]],
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


def get_timezone_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton('📍 Share my location', request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton(BACK)]], resize_keyboard=True)
