ONBOARDING_WELCOME = (
    "Hi! I'm your private anxiety journal. 🌿\n\n"
    "I'm here to help you process your thoughts and feelings through daily check-ins. "
    "Over time, we'll spot patterns together.\n\n"
    "Let's get started. What's your name?"
)

ONBOARDING_TIMEZONE = (
    "Nice to meet you, {name}! 🙂\n\n"
    "Tap the button below to share your location — I'll detect your timezone automatically.\n\n"
    "Or type it manually, e.g. Europe/London or America/New_York."
)

TIMEZONE_DETECTED = "Got it — I've set your timezone to *{timezone}*."

TIMEZONE_DETECTION_FAILED = (
    "I couldn't detect a timezone from that location. "
    "Please type it manually, e.g. Europe/London or America/New_York."
)

TIMEZONE_SUGGESTIONS = (
    "I found a few matches for \"{query}\". Which one is yours?"
)

ONBOARDING_TIME = (
    "And what time would you like your daily reminder?\n"
    "Please use 24h format, e.g. 09:00 or 21:30."
)

ONBOARDING_DONE = (
    "You're all set, {name}! ✅\n\n"
    "I'll check in with you every day at {reminder_time} ({timezone}).\n\n"
    "Whenever you're ready, tap *Check In* to start your first entry."
)

MAIN_MENU_MESSAGE = "What would you like to do, {name}?"

CHECK_IN_MOOD_PROMPT = (
    "How are you feeling right now, {name}?\n\n"
    "Rate your mood from 1 to 10 👇"
)

CHECK_IN_TEXT_PROMPT = (
    "Got it — a {score}/10. 📝\n\n"
    "Tell me what's on your mind. What's been going on?"
)

CHECK_IN_DONE = (
    "Thank you for sharing, {name}.\n\n"
    "{llm_response}\n\n"
    "_{streak} day(s) in a row. Keep it up!_"
)

HISTORY_EMPTY = "You haven't made any entries yet. Tap *Check In* to start!"

HISTORY_HEADER = "Here are your last {count} entries:\n\n"

HISTORY_ENTRY = "📅 *{date}* — Mood: {score}/10\n{text}\n\n"

STATS_EMPTY = "No data yet. Start checking in daily to see your stats!"

STATS_MESSAGE = (
    "📊 *Your stats*\n\n"
    "🔥 Current streak: {streak} days\n"
    "📅 Total entries: {total}\n"
    "😊 Average mood: {avg_mood}/10\n"
    "🏷 Top tags: {tags}"
)

HELP_MESSAGE = (
    "Here's what I can do:\n\n"
    "*Check In* — Start your daily journal entry\n"
    "*History* — See your last 7 entries\n"
    "*Stats* — View your streak and mood trends\n\n"
    "You can also use these commands any time:\n"
    "*/history* — Show your recent entries\n"
    "*/stats* — Show your stats\n"
    "*/cancel* — End the current session"
)

ERROR_GENERIC = "Something went wrong. Please try again."

GUIDANCE_OFFER_LOW = (
    "You're dealing with something heavy right now. "
    "Would you like a few evidence-based coping strategies tailored to what you shared?"
)

GUIDANCE_OFFER_VERY_LOW = (
    "That sounds really hard — I want to make sure you have some support right now. "
    "Would you like a few grounding techniques to help you get through this moment?"
)

GUIDANCE_DECLINED = "Of course. I'm here whenever you need me. Take gentle care of yourself. 🌿"

GUIDANCE_ERROR_MESSAGE = (
    "I wasn't able to generate suggestions right now. "
    "Please try again later, or reach out to someone you trust."
)

GUIDANCE_CRISIS_RESOURCES = (
    "———\n"
    "If you're in crisis or having thoughts of harming yourself, please reach out:\n"
    "• *International crisis centres*: iasp.info/resources/Crisis\\_Centres\n"
    "• *Crisis Text Line* (US/UK/CA/IE): text HOME to 741741\n"
    "• *Samaritans* (UK/IE): 116 123"
)

CANCEL_MESSAGE = "Take care, {name}. I'm here whenever you need me. 🌿"

WRONG_TIMEZONE = (
    "I didn't recognise that timezone. Please try again, "
    "e.g. Europe/London or America/New_York."
)

WRONG_TIME = "Please enter time in HH:MM format, e.g. 09:00"

REMINDER_MESSAGE = (
    "Hey {name}, time for your daily check-in! 🌿\n\n"
    "Tap *Check In* whenever you're ready."
)

WRONG_MOOD = "Please enter a number between 1 and 10."
