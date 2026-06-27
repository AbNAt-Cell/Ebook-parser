import os
import tempfile
import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from app.supabase_client import supabase
from app.parsers.pdf_parser import PDFParser
from app.parsers.epub_parser import EPUBParser

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ebook Parser Worker")


def update_book_status(book_id: str, status: str, error_msg: str = None):
    """Helper to update the processing status of a book."""
    try:
        data = {"processing_status": status}
        if error_msg:
            data["error"] = error_msg
        supabase.table("books").update(data).eq("id", book_id).execute()
        logger.info(f"Book {book_id} status updated to {status}")
    except Exception as e:
        logger.error(f"Failed to update status for book {book_id}: {e}")

def process_book_task(book_id: str):
    """Background task to download, parse, and sync book data."""
    temp_file_path = None
    try:
        # 1. Update status to 'extracting'
        update_book_status(book_id, "extracting")

        # 2. Fetch book details
        book_response = supabase.table("books").select("*").eq("id", book_id).execute()
        if not book_response.data:
            raise ValueError(f"Book with id {book_id} not found.")
        
        book_data = book_response.data[0]
        file_path = book_data.get("file_url")
        
        if not file_path:
            raise ValueError("file_url is empty.")

        logger.info(f"Downloading file: {file_path}")

        # 3. Download file from Supabase Storage (bucket: books or book-files)
        # Using "book-files" as mentioned in the prompt description
        res = supabase.storage.from_("book-files").download(file_path)
        
        # Save to temp file
        ext = os.path.splitext(file_path)[1].lower()
        fd, temp_file_path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, 'wb') as f:
            f.write(res)
            
        logger.info(f"File downloaded to {temp_file_path}")

        # 4. Parse the file
        if ext == '.pdf':
            parser = PDFParser()
        elif ext == '.epub':
            parser = EPUBParser()
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        logger.info(f"Parsing {ext} file...")
        metadata, chapters = parser.parse(temp_file_path)

        # 5. Sync Database
        logger.info(f"Syncing data to Supabase. Found {len(chapters)} chapters.")
        
        # Update books table metadata
        update_data = {
            "processing_status": "complete",
            "author": metadata.get("author") or book_data.get("author") or "Unknown",
        }
        # Only update page_count if the column exists in the schema and we extracted it
        if metadata.get("page_count"):
            update_data["page_count"] = metadata.get("page_count")
            
        # Update book title if it was empty
        if metadata.get("title") and not book_data.get("title"):
            update_data["title"] = metadata.get("title")

        # Handle cover upload if we extracted one
        cover_path = metadata.get("cover_path")
        if cover_path and os.path.exists(cover_path):
            try:
                user_id = book_data.get("user_id")
                ext = os.path.splitext(cover_path)[1].lower()
                storage_path = f"{user_id}/{book_id}{ext}"
                with open(cover_path, "rb") as f:
                    # Depending on python client version, upload takes bytes
                    supabase.storage.from_("book-covers").upload(
                        file_options={"upsert": "true", "content-type": "image/png" if ext == ".png" else "image/jpeg"},
                        path=storage_path,
                        file=f.read()
                    )
                
                # Get public url
                public_url = supabase.storage.from_("book-covers").get_public_url(storage_path)
                update_data["cover_url"] = public_url
                logger.info(f"Cover uploaded to {public_url}")
                
            except Exception as e:
                logger.warning(f"Failed to upload cover image: {e}")
            finally:
                # Cleanup cover file
                if os.path.exists(cover_path):
                    os.remove(cover_path)

        supabase.table("books").update(update_data).eq("id", book_id).execute()

        # Insert chapters and get their generated IDs
        if chapters:
            chapters_to_insert = []
            for ch in chapters:
                chapters_to_insert.append({
                    "book_id": book_id,
                    "chapter_num": ch["chapter_num"],
                    "title": ch["title"],
                    "content": ch["content"],
                    "word_count": ch["word_count"]
                })
            
            # Batch insert chapters and return the inserted rows
            chapters_res = supabase.table("chapters").insert(chapters_to_insert).execute()
            inserted_chapters = chapters_res.data
            
            if inserted_chapters:
                logger.info(f"Generating AI learning content for {len(inserted_chapters)} chapters...")
                from app.parsers.ai_extractor import AIExtractor
                extractor = AIExtractor()
                
                # Create a master flashcard deck for this book
                user_id = book_data.get("user_id")
                book_title = book_data.get("title", "Unknown Book")
                
                deck_res = supabase.table("flashcard_decks").insert({
                    "user_id": user_id,
                    "book_id": book_id,
                    "title": f"Flashcards for {book_title}",
                    "is_ai_generated": True,
                    "card_count": 0
                }).execute()
                deck_id = deck_res.data[0]["id"] if deck_res.data else None
                
                # We'll batch these inserts as well
                all_flashcards = []
                all_quizzes = []
                
                for ch in inserted_chapters:
                    chapter_id = ch["id"]
                    learning_data = extractor.generate_learning_content(ch["title"], ch.get("content", ""))
                    
                    if learning_data:
                        # Update chapter summary
                        if "summary" in learning_data:
                            supabase.table("chapters").update({"summary": learning_data["summary"]}).eq("id", chapter_id).execute()
                            
                        # Prepare flashcards
                        if deck_id and "flashcards" in learning_data:
                            for fc in learning_data["flashcards"]:
                                all_flashcards.append({
                                    "deck_id": deck_id,
                                    "user_id": user_id,
                                    "chapter_id": chapter_id,
                                    "front": fc.get("front", ""),
                                    "back": fc.get("back", ""),
                                    "difficulty": fc.get("difficulty", "medium").lower()
                                })
                                
                        # Prepare quiz
                        if "quiz" in learning_data:
                            # Insert quiz first to get its ID
                            quiz_res = supabase.table("quizzes").insert({
                                "user_id": user_id,
                                "book_id": book_id,
                                "chapter_id": chapter_id,
                                "title": f"Quiz: {ch['title']}",
                                "question_count": len(learning_data["quiz"]),
                                "quiz_type": "multiple_choice",
                                "difficulty": "medium",
                                "is_ai_generated": True
                            }).execute()
                            
                            if quiz_res.data:
                                quiz_id = quiz_res.data[0]["id"]
                                quiz_questions = []
                                for idx, q in enumerate(learning_data["quiz"]):
                                    quiz_questions.append({
                                        "quiz_id": quiz_id,
                                        "question_num": idx + 1,
                                        "question_text": q.get("question", ""),
                                        "question_type": "multiple_choice",
                                        "options": q.get("options", []),
                                        "correct_answer": q.get("correct_answer", ""),
                                        "explanation": q.get("explanation", "")
                                    })
                                if quiz_questions:
                                    supabase.table("quiz_questions").insert(quiz_questions).execute()
                                    
                # Batch insert all flashcards at the end
                if all_flashcards:
                    supabase.table("flashcards").insert(all_flashcards).execute()
                    # Update card_count on the deck
                    supabase.table("flashcard_decks").update({"card_count": len(all_flashcards)}).eq("id", deck_id).execute()

        logger.info(f"Successfully processed book {book_id}")

    except Exception as e:
        logger.error(f"Error processing book {book_id}: {e}")
        update_book_status(book_id, "failed", str(e))
    finally:
        # Cleanup temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Cleaned up temp file {temp_file_path}")


class ProcessRequest(BaseModel):
    type: str = None
    table: str = None
    record: Dict[str, Any] = None
    book_id: str = None # fallback

@app.post("/process", status_code=200)
async def process_book(request: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Webhook endpoint to trigger processing.
    Accepts Supabase Database Webhook payload or a direct {"book_id": "uuid"}.
    """
    book_id = request.book_id
    if request.record and "id" in request.record:
        book_id = request.record["id"]
        
    if not book_id:
        raise HTTPException(status_code=400, detail="book_id or record.id is required")

    logger.info(f"Received request to process book: {book_id}")
    background_tasks.add_task(process_book_task, book_id)
    return {"message": "Processing started", "book_id": book_id}

@app.get("/health", status_code=200)
async def health_check():
    """Health check endpoint for Fly.io."""
    return {"status": "ok"}
