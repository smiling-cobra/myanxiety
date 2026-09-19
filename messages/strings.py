ONBOARDING_WELCOME = (
    "Hi! I'm your anxiety journal. 🌿\n\n"
    "I'm here to help you process your thoughts and feelings through daily check-ins. "
    "Over time, we'll spot patterns together.\n\n"
    "First, a quick word about what happens to what you write."
)

PRIVACY_NOTICE = (
    "*What happens to what you write*\n\n"
    "• Your entries, mood scores and settings are stored in this bot's database.\n"
    "• The text of each entry is sent to Anthropic's API, which writes the replies, "
    "extracts the tags and generates your weekly summary. Under its API terms that "
    "text is not used to train models.\n"
    "• Messages travel through Telegram, so they are not end-to-end encrypted.\n"
    "• Your entry is also checked here against a fixed list of crisis-related phrases, "
    "so I can offer support resources when they might help. It's a plain keyword match "
    "on this server — nothing extra is sent anywhere, and no judgement is made about you.\n"
    "• I record which features you use and when — never what you write — to see whether "
    "the bot is actually helping. Those records are deleted after 180 days.\n"
    "• */export* sends you a file of your recent entries, in this chat. Once you have it, "
    "where it goes is up to you.\n"
    "• */delete* permanently removes everything this bot stores about you, in one step.\n"
    "• I'm a journalling tool. I'm not a therapist, a diagnosis, or a crisis service.\n\n"
    "Type */privacy* any time to read this again."
)

PRIVACY_ACCEPTED_PROMPT = "If that's alright with you, let's get started. What's your name?"

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

ONBOARDING_THERAPY = (
    "Last thing, and it's optional.\n\n"
    "Are you currently working with a therapist or counsellor?\n\n"
    "I ask because I'm being built to help people take something useful into a session, "
    "and knowing who that applies to shapes what gets built next. It changes nothing about "
    "how I treat you, and you're welcome to skip it."
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

# Shown instead of CHECK_IN_MOOD_PROMPT once today's check-in is done. Later
# entries are welcome — they are saved as notes on the day, without a reply.
NOTE_MOOD_PROMPT = (
    "You've already checked in today, {name} — want to add a note about what's come up since?\n\n"
    "Rate how you're feeling right now, from 1 to 10 👇"
)

CHECK_IN_TEXT_PROMPT = (
    "Got it — a {score}/10. 📝\n\n"
    "Tell me what's on your mind. What's been going on?"
)

CHECK_IN_DONE = (
    "Thank you for sharing, {name}.\n\n"
    "{llm_response}\n\n"
    "_{streak} day(s) in a row. Keep it up!_\n\n"
    "Want to talk about this in therapy? Send /flag."
)

# Shown instead of CHECK_IN_DONE once a user is at their daily LLM ceiling.
# The entry is saved either way — only the written reflection is missing, and
# the copy says so, because silently returning a shorter reply would read as
# the bot losing interest.
CHECK_IN_DONE_BRIEF = (
    "Thank you for sharing, {name}. Your entry is saved. 📝\n\n"
    "I've reached my limit for written replies today, so there's no reflection from me "
    "this time — but what you wrote is safely in your journal, and I'll be back to normal "
    "tomorrow.\n\n"
    "_{streak} day(s) in a row. Keep it up!_\n\n"
    "Want to talk about this in therapy? Send /flag."
)

# The reply to a note: a later entry on a day that already has its check-in.
# Deliberately brief — no reflection and no streak line. The note is in the
# journal and in the export either way.
NOTE_SAVED = (
    "Noted, {name} — added to today's journal. 📝\n\n"
    "Want to talk about this in therapy? Send /flag."
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
    "*Stats* — View your streak and mood trends\n"
    "*Export* — Get a file of the last 30 days to take to a therapy session\n\n"
    "You can also use these commands any time:\n"
    "*/history* — Show your recent entries\n"
    "*/stats* — Show your stats\n"
    "*/summary* — Show your weekly mood summary\n"
    "*/export* — Get a file of your recent entries\n"
    "*/flag* — Mark your latest entry to raise in your next session\n"
    "*/delete* — Permanently delete everything I store about you\n"
    "*/privacy* — What happens to what you write\n"
    "*/cancel* — End the current session\n\n"
    "———\n"
    "I'm a journalling tool, not a crisis service or a substitute for "
    "professional care. If you need urgent support:\n"
    "• *International crisis centres*: iasp.info/resources/Crisis\\_Centres\n"
    "• *Crisis Text Line* (US/UK/CA/IE): text HOME to 741741\n"
    "• *Samaritans* (UK/IE): 116 123"
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

# The guidance path is the one place a user has explicitly asked for help and
# is, by definition, having a hard time. When the LLM cannot be called, they get
# this rather than an apology: a fixed, well-established grounding exercise is
# worth more in that moment than a tailored paragraph they never receive.
GUIDANCE_STATIC_FALLBACK = (
    "I can't tailor suggestions right now, so here's something that helps many people "
    "in the moment:\n\n"
    "1. *Ground yourself.* Name 5 things you can see, 4 you can touch, 3 you can hear, "
    "2 you can smell, 1 you can taste. Say them out loud if you can.\n"
    "2. *Slow your breathing.* In for 4 counts, hold for 4, out for 6. Six rounds. "
    "The long exhale is the part that does the work.\n"
    "3. *Change your temperature.* Cold water on your face or wrists for 30 seconds "
    "settles the body faster than trying to talk yourself down.\n"
    "4. *Make the next step small.* One glass of water, one open window, one message "
    "to someone you trust — not the whole problem.\n\n"
    "You reached out, and that counts. I'm here tomorrow."
)

GUIDANCE_CRISIS_RESOURCES = (
    "———\n"
    "If you're in crisis or having thoughts of harming yourself, please reach out:\n"
    "• *International crisis centres*: iasp.info/resources/Crisis\\_Centres\n"
    "• *Crisis Text Line* (US/UK/CA/IE): text HOME to 741741\n"
    "• *Samaritans* (UK/IE): 116 123"
)

MOOD_LOST = (
    "Sorry — I've lost track of the rating that goes with this entry, "
    "so I haven't saved it yet.\n\n"
    "Could you rate your mood from 1 to 10 again? "
    "I'll ask for your entry straight after."
)

WEEKLY_SUMMARY_EMPTY = (
    "No check-ins this week yet. Start today with *Check In*! ✨"
)

WEEKLY_SUMMARY_HEADER = "📈 *Your week — {date_from} to {date_to}* ({count} entries)\n\n"

WEEKLY_SUMMARY_TREND_ROW = "*{score}*/10  {bar}  {day}\n"

WEEKLY_SUMMARY_TAGS = "\n🏷 *Top themes*: {tags}\n"

WEEKLY_SUMMARY_LLM_INTRO = "\n💬 *Patterns this week*\n"

WEEKLY_SUMMARY_TOO_FEW = "\n_Check in a few more times this week for pattern insights._"

WEEKLY_SUMMARY_BUDGET_REACHED = (
    "\n_Pattern insights are paused until tomorrow — you've reached today's limit. "
    "Your trend above is complete._"
)

WEEKLY_SUMMARY_NOTIFICATION = (
    "📈 *Your weekly insight*\n\n"
    "{summary}\n\n"
    "_Open your journal to see the full mood trend._"
)

EXPORT_EMPTY = (
    "There's nothing to export yet — you haven't written any entries in the last {days} days. "
    "Tap *Check In* to start one."
)

# Sent as the document's caption, so it must stay under Telegram's 1024-character
# caption limit. Plain text: captions are not parsed as Markdown here.
EXPORT_CAPTION = (
    "Your journal for the last {days} days — {count} {entries}.\n\n"
    "It's a plain text file you can open on your phone, print, or show to your therapist. "
    "It has everything you wrote in full, so share it only with people you trust."
)

FLAG_SET = (
    "🚩 Flagged your entry from {date} to raise in your next session. "
    "It'll be listed first when you */export*.\n\n"
    "Send /flag again to remove the flag."
)

FLAG_CLEARED = "Removed the flag from your entry from {date}."

FLAG_NO_ENTRY = "There's no entry to flag yet. Tap *Check In* to write one, then send /flag."

DELETE_CONFIRM_PROMPT = (
    "*Delete everything?*\n\n"
    "This permanently removes everything this bot stores about you: every journal entry, "
    "your mood scores and tags, your streak, your name and reminder settings, and the "
    "records of how you've used the bot.\n\n"
    "It can't be undone. If you want a copy first, choose *No* and send */export*.\n\n"
    "Two things this can't reach: the messages in this Telegram chat (you can clear the "
    "chat yourself), and text that was already sent to Anthropic, which is handled under "
    "Anthropic's own data retention terms."
)

DELETE_DONE = (
    "Done. Everything I stored about you has been deleted, and you won't get any more "
    "reminders from me.\n\n"
    "If you ever want to start again, send /start. Take care. 🌿"
)

DELETE_CANCELLED = "Nothing was deleted. Your journal is exactly as it was."

DELETE_FAILED = (
    "Sorry — I couldn't finish deleting your data just now, so some of it may still be "
    "stored. Please send /delete again in a few minutes; it's safe to repeat."
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
