# messages.py

# User onboarding messages
WELCOME_MESSAGE_LONG = '''
🌍 Welcome to TravelBot! 🚀

🛩️ Are you excited about your upcoming journey? Let TravelBot be your trusty guide, providing you with all the essential information for your destination.

📍 To get started, please tell me where you're headed. Simply type the name of your destination city, and I'll fetch the best travel tips and valuable insights just for you!

🏖️ Whether it's exploring famous landmarks, trying local delicacies, or getting the latest weather forecast, TravelBot has got you covered.

🗺️ Traveling is an adventure, and TravelBot is here to make it even better. Type in your destination now to begin your journey!

🙌 Happy travels! If you need any help, just type /help to see what I can assist you with.
'''

WELCOME_MESSAGE_CONCISE = '''
🌍 TravelBot welcomes you, {}! 🚀

🛩️ Tell me your destination city, and I'll be your travel companion, providing valuable tips and insights for your trip!

🗺️ Let's get started! Type your destination city now and embark on a seamless travel experience.

🙌 Happy travels!
'''

DEFAULT_USER_NAME = 'traveler'

HELP_WELCOME_MESSAGE = '''
Here's how you can use this bot: ...
'''

NO_CITY_FOUND_MESSAGE = '''
🤷‍♂️ Excusez-moi but no city was found... Try again!
'''

SHOW_MORE_LANDMARKS_MESSAGE = '''
🗽 Show me more landmarks, please!
'''

TELL_ME_MORE_ABOUT_WEATHER_MESSAGE = '''
☀️ Tell me more about current weather!
'''

def create_wrong_input_message(user_name) -> str:
    return f"🤷‍♂️ Oops, {user_name}! It seems there might be a little mix-up. Feel free to try again, and I'll assist you!"


def create_farewell_message(user_name) -> str:
    return f"👋 Take care, {user_name}! Remember, I'm here whenever you need assistance or information. Safe travels!"


def create_following_question_message(user_name) -> str:
    return f"Hey {user_name}! I'm here to assist you. 😊 What else would you like to know or explore?"


def create_welcome_landmarks_message(user_name, city_name) -> str:
    return f"📍 Hey {user_name}, let's explore some of the most famous landmarks in {city_name}!"


def create_welcome_restaurants_message(user_name, city_name) -> str:
    return f"🥗 Hi {user_name}, looking for great places to eat in {city_name}? You're in the right place!"


def create_weather_message(user_name, city_name, weather_desc) -> str:
    return f"🌤️ Good day, {user_name}! Here's the weather forecast for {city_name}:\n\n{weather_desc}"


def create_interesting_facts_message(city_name) -> str:
    return f"🤓 Sure thing! Let me share some fascinating facts about {city_name} with you."
