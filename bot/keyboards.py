from telegram import KeyboardButton, ReplyKeyboardMarkup

CHECK_IN = '📝 Check In'
HISTORY = '📖 History'
STATS = '📊 Stats'
HELP = '❓ Help'
BACK = '🔙 Back'


def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[CHECK_IN], [HISTORY, STATS], [HELP]],
        resize_keyboard=True
    )


def get_mood_keyboard():
    return ReplyKeyboardMarkup(
        [['1', '2', '3', '4', '5'], ['6', '7', '8', '9', '10']],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_timezone_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton('📍 Share my location', request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton(BACK)]], resize_keyboard=True)
