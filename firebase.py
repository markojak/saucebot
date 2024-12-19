#!./.venv/bin/python

import os
import logging
from typing import List
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from telegram import Message
from google.cloud.firestore_v1.base_document import DocumentSnapshot

# Configure logging
if os.getenv("ENVIRONMENT") == "development":
    # Set root logger to WARNING to suppress most third-party logs
    logging.getLogger().setLevel(logging.WARNING)
    
    # Configure our app's logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    
    # Create console handler with formatting
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    logger.addHandler(console_handler)
    
    # Silence noisy loggers only in development
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
else:
    logger = logging.getLogger(__name__)

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)

db = firestore.client()


def convert_user(user):
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
    }


def convert_reply_message(message: Message):
    return {"from": convert_user(message.from_user), "text": message.text}


def save_message(message: Message, image_description: str, urls: List[str] = None, reactions = None) -> str:
    if message == None:
        return
    
    if os.getenv("ENVIRONMENT") == "development":
        logger.debug(f"Saving message: ID={message.message_id}")
        logger.debug(f"Reactions: {reactions}")
    
    message_text = (
        message.text
        if message.text != None
        else message.caption if message.caption != None else image_description
    )
    
    s_message = {
        "message_id": message.message_id,
        "date": message.date,
        "from": convert_user(message.from_user),
        "reply_to_message": (
            convert_reply_message(message.reply_to_message)
            if message.reply_to_message is not None
            else ""
        ),
        "text": message_text,
        "reactions": reactions if reactions else [],
    }

    if urls and len(urls) > 0:
        s_message["urls"] = urls
        if os.getenv("ENVIRONMENT") == "development":
            logger.debug(f"URLs found: {urls}")
    else:
        s_message["urls"] = None
    
    if image_description != None and len(image_description) > 0:
        s_message["attachment_description"] = image_description
        if os.getenv("ENVIRONMENT") == "development":
            logger.debug(f"Image description: {image_description[:100]}...")

    update_time, message_ref = db.collection(str(message.chat.id)).add(s_message)
    
    if os.getenv("ENVIRONMENT") == "development":
        logger.debug(f"Message saved successfully with ref: {message_ref.id}")
    
    return message_ref.id


def get_last_messages(chat_id, limit) -> List:
    if os.getenv("ENVIRONMENT") == "development":
        logger.debug(f"Fetching last {limit} messages for chat {chat_id}")
    
    snapshots = (
        db.collection(chat_id)
        .order_by("date", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .get()
    )
    result = list(map(lambda snap: snap.to_dict(), snapshots))
    result.reverse()
    
    if os.getenv("ENVIRONMENT") == "development":
        logger.debug(f"Retrieved {len(result)} messages")
    
    return result

def get_message(chat_id, message_id) -> DocumentSnapshot:
    return db.collection(chat_id).document(message_id).get()

def get_last_messages_with_urls(chat_id: str, limit: int) -> List:
    """Get last messages that contain URLs"""
    # Get all messages and filter in memory
    snapshots = (
        db.collection(chat_id)
        .order_by("date", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .get()
    )
    # Filter messages that have non-empty urls
    return [
        snap.to_dict() 
        for snap in snapshots 
        if "urls" in snap.to_dict() and snap.get("urls") and len(snap.get("urls")) > 0
    ]