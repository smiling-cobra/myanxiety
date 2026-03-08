import os
import html
import requests
from telegram import Update, ParseMode
from telegram.ext import CallbackContext
from commands import Command
from messages import (
     create_welcome_landmarks_message,
     DEFAULT_USER_NAME
)
from services import CacheService

google_map_api_key = os.environ.get('GOOGLE_MAP_API_KEY')
google_places_api_url = os.environ.get('GOOGLE_PLACES_API_URL')

landmarks_texts = {
    'PLACES_ERROR': "Sorry, I couldn't find any landmarks in {}!",
}


class Places(Command):
    def __init__(self, get_city_name, get_option_keyboard, logger):
        self.get_city_name = get_city_name
        self.get_landmark_keyboard = get_option_keyboard
        self.logger = logger

    def execute(self, update: Update, context: CallbackContext) -> None:
        city_name = self.get_city_name(context)
        places = self.get_places(city_name, context)

        if places:
            user_name = update.message.chat.first_name or DEFAULT_USER_NAME
            update.message.reply_text(
                create_welcome_landmarks_message(user_name, city_name),
                reply_markup=self.get_landmark_keyboard()
            )
            self.post_landmarks(update, places)
        else:
            update.message.reply_text(
                landmarks_texts['PLACES_ERROR'].format(city_name)
            )

    def get_places(self, city_name: str, context: CallbackContext) -> list:
        cache_service = CacheService()
        places_cache_key = 'city_landmarks'
        cached_data = cache_service.get(places_cache_key, context)
        
        if cached_data:
            return cached_data
        
        params = {
            'query': f"landmarks in {city_name}",
            'inputtype': 'textquery',
            'fields': 'photos,place_id,geometry',
            'key': google_map_api_key
        }

        # self.logger.log('info', f'Google Places API URL: {google_places_api_url}')
        # self.logger.log('info', f'Google Places API Params: {params}')
        
        response = requests.get(google_places_api_url, params=params)

        try:
            data = response.json()
        except ValueError as e:
            return []
            print(f"Error parsing JSON: {e}")

        response_status = data.get('status')

        if response_status == 'OK':
            composed_places_list = self.compose_places_list(
                data.get('results', [])
            )            
            cache_service.set(
                places_cache_key,
                composed_places_list,
                context
            )
            
            return composed_places_list[:7]
        else:
            return f"No places were found! Status: {response_status}"

    def compose_places_list(self, places: list) -> None:
        GOOGLE_PHOTO_API_URL = "https://maps.googleapis.com/maps/api/place/photo"
        landmarks_info = []

        for place in places:
            landmark = {}
            photos = place.get('photos', [])
            if photos:
                photo_ref = photos[0].get('photo_reference')
                if photo_ref:
                    photo_params = {
                        'maxwidth': 400,
                        'photoreference': photo_ref,
                        'key': google_map_api_key
                    }

                    try:
                        photo_url = requests.get(
                            GOOGLE_PHOTO_API_URL,
                            params=photo_params).url

                        landmark['photo'] = photo_url
                    except ValueError as e:
                        return []
                        print(f"Error parsing JSON: {e}")

            landmark['name'] = place.get('name')
            landmark['formatted_address'] = place.get('formatted_address')

            landmarks_info.append(landmark)

        return landmarks_info

    def format_address_as_link(self, address: str):
        google_maps_link = f'https://www.google.com/maps/search/?api=1&query={html.escape(address)}'
        return f'<a href="{google_maps_link}">{html.escape(address)}</a>'

    def post_landmarks(self, update: Update, landmarks: list) -> None:
        for landmark in landmarks:
            landmark_name = landmark.get('name')
            landmark_location = landmark.get('formatted_address')
            landmark_photo = landmark.get('photo')

            if landmark_photo:
                update.message.reply_photo(photo=landmark_photo)

            location_link = self.format_address_as_link(landmark_location)
            message_text = f"{landmark_name}\n{location_link}"
            update.message.reply_text(
                message_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
