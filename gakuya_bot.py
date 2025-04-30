import cohere
import tweepy
import requests
import schedule
import time
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
import pytz
from flask import Flask
import threading
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gakuya.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# API keys from .env
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

# Validate API keys
if not all([COHERE_API_KEY, OPENWEATHER_API_KEY, X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
    logger.error("Missing one or more API keys in .env file")
    raise ValueError("Missing API keys in .env file")

# Initialize Cohere client
try:
    co = cohere.Client(COHERE_API_KEY)
    logger.info("Cohere client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Cohere client: {e}")
    raise

# Initialize Tweepy client
try:
    auth = tweepy.OAuthHandler(X_API_KEY, X_API_SECRET)
    auth.set_access_token(X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)
    api = tweepy.API(auth)
    client = tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET
    )
    logger.info("Tweepy client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Tweepy client: {e}")
    raise

# Fetch the user ID for the authenticated account
try:
    user = client.get_me()
    GAKUYA_USER_ID = user.data.id
    logger.info(f"Authenticated as user ID: {GAKUYA_USER_ID}")
except Exception as e:
    logger.error(f"Failed to fetch user ID: {e}")
    raise

# Nairobi coordinates
CITY = "Nairobi"
LAT = -1.2833
LON = 36.8167

# File to store last tweet ID persistently
LAST_TWEET_ID_FILE = "last_tweet_id.json"

# Function to load last tweet ID from file
def load_last_tweet_id():
    try:
        if os.path.exists(LAST_TWEET_ID_FILE):
            with open(LAST_TWEET_ID_FILE, 'r') as f:
                data = json.load(f)
                return data.get('last_tweet_id')
        return None
    except Exception as e:
        logger.error(f"Error loading last tweet ID: {e}")
        return None

# Function to save last tweet ID to file
def save_last_tweet_id(tweet_id):
    try:
        with open(LAST_TWEET_ID_FILE, 'w') as f:
            json.dump({'last_tweet_id': tweet_id}, f)
        logger.info(f"Saved last_tweet_id to file: {tweet_id}")
    except Exception as e:
        logger.error(f"Error saving last tweet ID: {e}")

# Function to get weather data
def get_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={LAT}&lon={LON}&appid={OPENWEATHER_API_KEY}&units=metric"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        temp = data['main']['temp']
        description = data['weather'][0]['description']
        logger.info(f"Weather fetched for {CITY}: {temp}°C, {description}")
        return temp, description
    except Exception as e:
        logger.error(f"Failed to fetch weather data: {e}")
        return None, None

# Function to generate weather post in English with Kenyan banter and hashtags
def generate_weather_post(temp, description):
    prompt = f"""
    You are Gakuya, a Kenyan AI bot with a funny, sarcastic, and unhinged personality. Create a short X post (130 characters or less) in English about today's weather in {CITY} (Temp: {temp}°C, Condition: {description}). Use Kenyan banter with relatable references (e.g., matatus, tea, maandazi, or local vibes), and humor. Add hashtags #NairobiWeather and #KenyanVibes. Keep it short, punchy, and chaotic. Avoid Sheng slang.
    """
    try:
        response = co.generate(
            model='command',
            prompt=prompt,
            max_tokens=60,
            temperature=1.0,
            k=0,
            stop_sequences=[],
            return_likelihoods='NONE'
        )
        post = response.generations[0].text.strip()
        logger.info(f"Generated post length: {len(post)} characters")
        if len(post) > 280:
            last_space = post[:277].rfind(' ')
            if last_space == -1:
                last_space = 277
            post = post[:last_space] + "..."
            logger.warning(f"Post truncated to {len(post)} characters: {post}")
        return post
    except Exception as e:
        logger.error(f"Failed to generate weather post: {e}")
        return None

# Function to generate reply to comments in English with Kenyan banter and hashtags
def generate_reply(comment):
    prompt = f"""
    You are Gakuya, a Kenyan AI bot with a funny, sarcastic, and unhinged personality. A user commented on your X post: "{comment}". Respond with a short, witty reply (130 characters or less) in English using Kenyan banter with relatable references (e.g., matatus, tea, maandazi, or local vibes). Add hashtag #KenyanVibes. Keep it humorous, chaotic, and relevant. Avoid Sheng slang.
    """
    try:
        response = co.generate(
            model='command',
            prompt=prompt,
            max_tokens=60,
            temperature=1.0,
            k=0,
            stop_sequences=[],
            return_likelihoods='NONE'
        )
        reply = response.generations[0].text.strip()
        logger.info(f"Generated reply length: {len(reply)} characters")
        if len(reply) > 280:
            last_space = reply[:277].rfind(' ')
            if last_space == -1:
                last_space = 277
            reply = reply[:last_space] + "..."
            logger.warning(f"Reply truncated to {len(reply)} characters: {reply}")
        return reply
    except Exception as e:
        logger.error(f"Failed to generate reply for comment '{comment}': {e}")
        return None

# Function to post weather update
def post_weather_update():
    temp, description = get_weather()
    if temp is None:
        logger.error("Skipping post due to weather data failure")
        return None
    post = generate_weather_post(temp, description)
    if post is None:
        logger.error("Skipping post due to post generation failure")
        return None
    try:
        tweet = client.create_tweet(text=post)
        logger.info(f"Posted to X: {post} (Tweet ID: {tweet.data['id']})")
        save_last_tweet_id(tweet.data['id'])
        return tweet.data['id']
    except Exception as e:
        logger.error(f"Error posting tweet: {e}")
        return None

# Function to fetch the latest tweet ID as a fallback
def get_latest_tweet_id():
    try:
        logger.info("Attempting to fetch latest tweet ID")
        tweets = client.get_users_tweets(id=GAKUYA_USER_ID, max_results=5)
        if tweets.data:
            latest_tweet_id = tweets.data[0].id
            logger.info(f"Fetched latest tweet ID: {latest_tweet_id}")
            return latest_tweet_id
        else:
            logger.warning("No tweets found for user")
            return None
    except Exception as e:
        logger.error(f"Error fetching latest tweet: {e}")
        return None

# Function to check and reply to comments using v1.1 API
def check_and_reply(last_tweet_id):
    if not last_tweet_id:
        logger.warning("No tweet ID provided, attempting to fetch latest tweet ID")
        last_tweet_id = get_latest_tweet_id()
        if not last_tweet_id:
            logger.warning("Failed to fetch latest tweet ID, attempting to load from file")
            last_tweet_id = load_last_tweet_id()
            if not last_tweet_id:
                logger.error("Failed to fetch or load last tweet ID, skipping reply check")
                return
    try:
        logger.info(f"Checking mentions since tweet ID: {last_tweet_id}")
        mentions = api.mentions_timeline(since_id=last_tweet_id)
        if not mentions:
            logger.info("No new mentions found")
            return
        for mention in mentions:
            comment = mention.text
            user_id = mention.user.id
            username = mention.user.screen_name
            mention_id = mention.id
            reply = generate_reply(comment)
            if reply is None:
                logger.error(f"Skipping reply to @{username} due to reply generation failure")
                continue
            try:
                client.create_tweet(
                    text=f"@{username} {reply}",
                    in_reply_to_tweet_id=mention_id
                )
                logger.info(f"Replied to @{username}: {reply}")
            except Exception as e:
                logger.error(f"Error replying to @{username}: {e}")
    except Exception as e:
        logger.error(f"Error fetching mentions: {e}")

# Function to run the bot's scheduling logic
def run_bot():
    logger.info("Starting Gakuya bot")
    last_tweet_id = load_last_tweet_id()
    def job():
        nonlocal last_tweet_id
        last_tweet_id = post_weather_update()
        logger.info(f"Updated last_tweet_id to: {last_tweet_id}")
        check_and_reply(last_tweet_id)

    # Schedule weather post every 6 hours
    try:
        schedule.every(6).hours.do(job)
        logger.info("Weather post scheduled every 6 hours")
    except Exception as e:
        logger.error(f"Failed to schedule weather post: {e}")
        raise

    # Check for replies every 10 minutes
    try:
        schedule.every(10).minutes.do(check_and_reply, last_tweet_id)
        logger.info("Reply check scheduled every 10 minutes")
    except Exception as e:
        logger.error(f"Failed to schedule reply check: {e}")
        raise

    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(60)

# Health endpoint for UptimeRobot to ping
@app.route('/health')
def health():
    return "Gakuya is alive!", 200

# Start the bot in a separate thread
if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    # Start Flask server
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)