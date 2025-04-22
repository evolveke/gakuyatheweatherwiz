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

# Nairobi coordinates (can be changed to another Kenyan city)
CITY = "Nairobi"
LAT = -1.2833
LON = 36.8167

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

# Function to generate weather post with banter
def generate_weather_post(temp, description):
    prompt = f"""
    You are Gakuya, a Kenyan AI bot with a funny, sarcastic, intelligent, and unhinged personality. Create a short X post (200 characters or less) about today's weather in {CITY} (Temp: {temp}°C, Condition: {description}). Use witty Kenyan banter, local slang, and humor. Keep it short, punchy, and chaotic. Avoid nonsense phrases.
    """
    try:
        response = co.generate(
            model='command',
            prompt=prompt,
            max_tokens=50,  # Reduced to ensure shorter output
            temperature=1.0,
            k=0,
            stop_sequences=[],
            return_likelihoods='NONE'
        )
        post = response.generations[0].text.strip()
        logger.info(f"Generated post length: {len(post)} characters")
        if len(post) > 280:
            # Find the last space before 277 characters to avoid cutting mid-word
            last_space = post[:277].rfind(' ')
            if last_space == -1:
                last_space = 277
            post = post[:last_space] + "..."
            logger.warning(f"Post truncated to {len(post)} characters: {post}")
        return post
    except Exception as e:
        logger.error(f"Failed to generate weather post: {e}")
        return None

# Function to generate reply to comments
def generate_reply(comment):
    prompt = f"""
    You are Gakuya, a Kenyan AI bot with a funny, sarcastic, intelligent, and unhinged personality. A user commented on your X post: "{comment}". Respond with a short, witty reply (200 characters or less) using Kenyan banter. Keep it humorous, chaotic, and relevant.
    """
    try:
        response = co.generate(
            model='command',
            prompt=prompt,
            max_tokens=50,  # Reduced to ensure shorter output
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
        return tweet.data['id']
    except Exception as e:
        logger.error(f"Error posting tweet: {e}")
        return None

# Function to check and reply to comments
def check_and_reply(last_tweet_id):
    if not last_tweet_id:
        logger.warning("No tweet ID provided, skipping reply check")
        return
    try:
        mentions = api.mentions_timeline(since_id=last_tweet_id)
        if not mentions:
            logger.info("No new mentions found")
        for mention in mentions:
            comment = mention.text
            user = mention.user.screen_name
            reply = generate_reply(comment)
            if reply is None:
                logger.error(f"Skipping reply to @{user} due to reply generation failure")
                continue
            try:
                client.create_tweet(
                    text=f"@{user} {reply}",
                    in_reply_to_tweet_id=mention.id
                )
                logger.info(f"Replied to @{user}: {reply}")
            except Exception as e:
                logger.error(f"Error replying to @{user}: {e}")
    except Exception as e:
        logger.error(f"Error fetching mentions: {e}")

# Main function to run bot
def run_bot():
    logger.info("Starting Gakuya bot")
    last_tweet_id = None
    def job():
        nonlocal last_tweet_id
        last_tweet_id = post_weather_update()
        check_and_reply(last_tweet_id)

    # Schedule daily post at 7 AM Nairobi time
    nairobi_tz = pytz.timezone('Africa/Nairobi')
    try:
        schedule.every().day.at("09:00", nairobi_tz).do(job)
        logger.info("Daily weather post scheduled at 09:00 Nairobi time")
    except Exception as e:
        logger.error(f"Failed to schedule daily post: {e}")
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

if __name__ == "__main__":
    run_bot()