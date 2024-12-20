from firebase_admin import firestore
from firebase_admin import credentials
import firebase_admin
import os
from dotenv import load_dotenv

load_dotenv()

# This script is used to copy messages from one chat to another for testing purposes so that you can test summarization of messages without affecting the group chat. 
# enter the source chat id and target chat id and the script will copy the messages from the source chat to the target chat based on the same collection name
# Initialize Firebase if not already initialized
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

def copy_messages(source_chat_id: str, target_chat_id: str, limit: int = None):
    """
    Copy messages from source chat collection to target chat collection for testing
    """
    print(f"Debug: Attempting to copy from collection '{source_chat_id}' to collection '{target_chat_id}'")
    
    # Test query first
    test_docs = db.collection(source_chat_id).limit(1).get()
    if not list(test_docs):
        print(f"Debug: No messages found in collection {source_chat_id}")
        return

    # Get source messages
    query = db.collection(source_chat_id)
    if limit:
        query = query.limit(limit)
    
    source_messages = query.get()
    total_messages = len(list(source_messages))
    print(f"Debug: Found {total_messages} messages to copy")
    
    if total_messages == 0:
        return
        
    # Copy each message to target collection
    batch = db.batch()
    count = 0
    
    for msg in source_messages:
        data = msg.to_dict()
        print(f"Debug: Processing message {count + 1}/{total_messages}")
        
        # Create new document reference in target collection
        new_doc_ref = db.collection(target_chat_id).document()
        batch.set(new_doc_ref, data)
        
        count += 1
        # Firestore batches are limited to 500 operations
        if count % 400 == 0:  # Commit every 400 documents
            print(f"Debug: Committing batch of {count} messages")
            batch.commit()
            batch = db.batch()
    
    # Commit any remaining documents
    if count % 400 != 0:
        batch.commit()
    
    print(f"Successfully copied {count} messages from collection '{source_chat_id}' to collection '{target_chat_id}'")

if __name__ == "__main__":
    # Remove -100 prefix if present in source chat ID
    SOURCE_CHAT = "-1002217159309"     # Your source group chat ID (removed -100) Software scalers ID
    TARGET_CHAT = "535263823"      # Your test chat ID / markojak and saucebot staging ID
    LIMIT = 1000                   # Optional: limit number of messages to copy
    
    copy_messages(SOURCE_CHAT, TARGET_CHAT, LIMIT) 