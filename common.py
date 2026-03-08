from telegram.ext import CallbackContext
from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup
)

PLACES = '🗽 Places'
WEATHER_FORECAST = '☀️ Weather'
AFFORDABLE_EATS = '🥗 Eats'
EVENTS = '⭐ Events'
TRAVEL_TIPS = '🎯 Tips'
STORIES = '🎲 Stories'
HELP = '❓ Help'
BACK = '🔙 Back'


def get_lobby_keyboard():
    options = [
        [PLACES, WEATHER_FORECAST, AFFORDABLE_EATS],
        [EVENTS, TRAVEL_TIPS, STORIES],
        [HELP]
    ]

    keyboard = [[KeyboardButton(option) for option in row] for row in options]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_city_name(context: CallbackContext) -> str:
    city_data = context.user_data.get('city_data')[0]
    address_components = city_data.get('address_components')[0]
    city_name = address_components.get('long_name')
    return city_name


def get_option_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[KeyboardButton(BACK)]]
    return ReplyKeyboardMarkup(keyboard)
