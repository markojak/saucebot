#!./venv/bin/python

import logging
from typing import Callable
import ffmpeg.stream
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    filters,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
)
from firebase import save_message as fb_save_message, get_last_messages, get_message, get_last_messages_with_urls
from md2tgmd import escape

import os
from dotenv import load_dotenv

from open_ai import (
    ai_describe_image,
    ai_retell,
    ai_identify_parameters,
    ai_retell,
    ai_summarize,
    ai_transcript_audio,
)
import base64
import ffmpeg

from tools import process_urls, extract_urls_from_message

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Hi, I'm Sauce Bot. Use /s to summarize the chat or /s n where n is the number of messages to summarize."
    )


async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update == None or update.message == None:
        return

    image_description = await process_images(update, context)
    
    # Extract URLs before saving
    message_text = (
        update.message.text
        if update.message.text != None
        else (update.message.caption if update.message.caption != None else image_description)
    )
    urls = extract_urls_from_message(message_text) if message_text else None
    
    # Save message with URLs
    fb_save_message(update.message, image_description, urls)


async def process_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    image_description = None
    if (
        update != None
        and update.message != None
        and update.message.photo != None
        and len(update.message.photo) > 0
    ):
        highest_quality_photo_id = update.message.photo[-1].file_id

        file = await context.bot.get_file(highest_quality_photo_id)
        byte_array = await file.download_as_bytearray()
        image_data = base64.b64encode(byte_array).decode("utf-8")
        image_description = ai_describe_image(image_data)
    return image_description


async def default_summarize(
    update: Update, context: ContextTypes.DEFAULT_TYPE, ai_func: Callable
):
    try:
        limit = (
            int(context.args[0])
            if (len(context.args) > 0 and context.args[0] is not None)
            else int(os.getenv("DEFAULT_HISTORY_LENGTH"))
        )
        params = {}

        params["history_length"] = limit
        params["language"] = os.getenv("DEFAULT_LANGUAGE")
        params["tone"] = os.getenv("DEFAULT_TONE")
        params["chat_id"] = str(update.message.chat.id)

        messages = get_last_messages(str(update.message.chat.id), limit)
        result = ai_func(messages, params, update.message.chat.type)
        result = escape(result)
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=result, parse_mode="MarkdownV2"
        )
    except Exception as error:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=repr(error)
        )


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the first argument is "url"
    if len(context.args) > 0 and context.args[0].lower() == "url":
        # Get limit from second argument if it exists
        limit = int(context.args[1]) if len(context.args) > 1 else int(os.getenv("DEFAULT_HISTORY_LENGTH"))
        await summarize_urls(update, context, limit)
    else:
        # Original summarize behavior
        await default_summarize(update, context, ai_summarize)


async def retell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await default_summarize(update, context, ai_retell)


async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Chat id: " + str(update.message.chat.id)
    )


async def bot_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update == None or update.message == None:
        return

    try:
        params = ai_identify_parameters(update.message.text)

        if params["history_length"] is None:
            params["history_length"] = int(os.getenv("DEFAULT_HISTORY_LENGTH"))
        if params["language"] is None:
            params["language"] = os.getenv("DEFAULT_LANGUAGE")
        if params["tone"] is None:
            params["tone"] = os.getenv("DEFAULT_TONE")

        params["chat_id"] = str(update.message.chat.id)

        messages = get_last_messages(
            str(update.message.chat.id), params["history_length"]
        )
        result = ai_retell(messages, params)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=escape(result),
            parse_mode="MarkdownV2",
        )
    except Exception as error:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=repr(error)
        )


async def process_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    path_to_file = None
    try:
        new_file = await context.bot.get_file(update.message.voice.file_id)
        path_to_file = await new_file.download_to_drive()
        transcription = ai_transcript_audio(path_to_file)
        fb_message_id = fb_save_message(update.message, transcription)
        
        if os.getenv("IS_ECHO_VOICE_MESSAGES") == "true":
            if os.getenv("ECHO_VOICE_MESSAGE_TYPE") == "BUTTON":
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🎤 Discovered a voice message\! Click below to see the transcription",
                    reply_to_message_id=update.message.message_id,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "Get transcription",
                                callback_data=f"m:{update.effective_chat.id}:{fb_message_id}:{update.message.message_id}"
                            )
                        ]]
                    )
                )
            else:
                reply_text = f"*{escape(update.message.from_user.username)}*: {escape(transcription)}"
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=reply_text,
                    reply_to_message_id=update.message.message_id,
                    parse_mode="MarkdownV2"
                )
    except Exception as e:
        logging.error(f"Error in process_voice_message: {str(e)}")
        pass
    finally:
        if path_to_file != None:
            path_to_file.unlink()


async def process_video_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    path_to_video_file = None
    audio_file_path = None
    try:
        new_file = await context.bot.get_file(update.message.video.file_id)
        path_to_video_file = await new_file.download_to_drive()
        audio_file_path = path_to_video_file.with_suffix(".mp3")
        ffmpeg.input(path_to_video_file).output(audio_file_path.name).run()
        transcription = ai_transcript_audio(audio_file_path)
        fb_message_id = fb_save_message(update.message, transcription)
        
        if os.getenv("IS_ECHO_VOICE_MESSAGES") == "true":
            if os.getenv("ECHO_VOICE_MESSAGE_TYPE") == "BUTTON":
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🎥 Discovered a video\! Click below to see the transcription",
                    reply_to_message_id=update.message.message_id,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "Get transcription",
                                callback_data=f"m:{update.effective_chat.id}:{fb_message_id}:{update.message.message_id}"
                            )
                        ]]
                    )
                )
            else:
                reply_text = f"*{escape(update.message.from_user.username)}*: {escape(transcription)}"
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=reply_text,
                    reply_to_message_id=update.message.message_id,
                    parse_mode="MarkdownV2"
                )
    except Exception as e:
        logging.error(f"Error in process_video_message: {str(e)}")
        pass
    finally:
        if path_to_video_file != None:
            path_to_video_file.unlink()
        if audio_file_path != None:
            audio_file_path.unlink()


async def process_video_note_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    path_to_video_file = None
    audio_file_path = None
    try:
        new_file = await context.bot.get_file(update.message.video_note.file_id)
        path_to_video_file = await new_file.download_to_drive()
        audio_file_path = path_to_video_file.with_suffix(".mp3")
        ffmpeg.input(path_to_video_file).output(audio_file_path.name).run()
        transcription = ai_transcript_audio(audio_file_path)
        fb_message_id = fb_save_message(update.message, transcription)
        
        if os.getenv("IS_ECHO_VOICE_MESSAGES") == "true":
            if os.getenv("ECHO_VOICE_MESSAGE_TYPE") == "BUTTON":
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🎥 Discovered a video note\! Click below to see the transcription",
                    reply_to_message_id=update.message.message_id,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "Get transcription",
                                callback_data=f"m:{update.effective_chat.id}:{fb_message_id}:{update.message.message_id}"
                            )
                        ]]
                    )
                )
            else:
                reply_text = f"*{escape(update.message.from_user.username)}*: {escape(transcription)}"
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=reply_text,
                    reply_to_message_id=update.message.message_id,
                    parse_mode="MarkdownV2"
                )
    except Exception as e:
        logging.error(f"Error in process_video_note_message: {str(e)}")
        pass
    finally:
        if path_to_video_file != None:
            path_to_video_file.unlink()
        if audio_file_path != None:
            audio_file_path.unlink()


async def process_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.edit_message_text(text="🤖 Processing... 🍆💦")
    type, chat_id, fb_message_id, reply_to_message_id = query.data.split(":")
    text = None
    if type == "u":
        message = get_message(chat_id, fb_message_id).to_dict()
        message_text = message["text"]
        url_summaries = await process_urls(message_text)
        if url_summaries == None or len(url_summaries) == 0:
            return
        for summary in url_summaries:
            title = (
                summary.metadata["title"] if "title" in summary.metadata else "Summary"
            )
            text = f"*{escape(title)}*: {escape(summary.page_content)}"
    elif type == "m":
        message = get_message(chat_id, fb_message_id).to_dict()
        text = escape(message["text"])
    # CallbackQueries need to be answered, even if no notification to the user is needed
    # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
    await query.answer()

    await query.edit_message_text(text=text, parse_mode="MarkdownV2")


async def summarize_urls(update: Update, context: ContextTypes.DEFAULT_TYPE, limit: int):
    try:
        messages = get_last_messages_with_urls(str(update.message.chat.id), limit)
        
        if not messages:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="No messages with URLs found in recent history."
            )
            return
            
        for message in messages:
            url_summaries = await process_urls(message["text"])
            if url_summaries:
                for summary in url_summaries:
                    title = summary.metadata.get("title", "Summary")
                    text = f"*{escape(title)}*: {escape(summary.page_content)}"
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=text,
                        parse_mode="MarkdownV2"
                    )
    except Exception as error:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=repr(error)
        )


def start_bot():
    bot_name = os.getenv("TELEGRAM_BOT_NAME")

    application = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()

    start_handler = CommandHandler("start", start)
    s_handler = CommandHandler("s", summarize)
    summarize_handler = CommandHandler("summarize", summarize)
    chat_id_handler = CommandHandler("chatid", get_chat_id)
    mention_handler = MessageHandler(filters.Mention(bot_name), bot_mention)
    voice_message_handler = MessageHandler(filters.VOICE, process_voice_message)
    video_message_handler = MessageHandler(filters.VIDEO, process_video_message)
    video_note_message_handler = MessageHandler(
        filters.VIDEO_NOTE, process_video_note_message
    )
    save_message_handler = MessageHandler(
        (filters.TEXT | filters.PHOTO)
        & (~filters.COMMAND)
        & (~filters.Mention(bot_name)),
        save_message,
    )

    application.add_handler(start_handler)
    application.add_handler(s_handler)
    application.add_handler(summarize_handler)
    application.add_handler(save_message_handler)
    application.add_handler(chat_id_handler)
    application.add_handler(mention_handler)
    application.add_handler(voice_message_handler)
    application.add_handler(video_message_handler)
    application.add_handler(video_note_message_handler)
    application.add_handler(CallbackQueryHandler(process_callback))

    application.run_polling()
