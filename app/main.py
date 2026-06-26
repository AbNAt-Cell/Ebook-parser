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

class ProcessRequest(BaseModel):
    book_id: str

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
        file_path = book_data.get("file_path")
        
        if not file_path:
            raise ValueError("file_path is empty.")

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

        supabase.table("books").update(update_data).eq("id", book_id).execute()

        # Insert chapters
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
            
            # Batch insert chapters
            supabase.table("chapters").insert(chapters_to_insert).execute()

        logger.info(f"Successfully processed book {book_id}")

    except Exception as e:
        logger.error(f"Error processing book {book_id}: {e}")
        update_book_status(book_id, "failed", str(e))
    finally:
        # Cleanup temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Cleaned up temp file {temp_file_path}")


@app.post("/process", status_code=200)
async def process_book(request: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Webhook endpoint to trigger processing.
    Returns 200 OK immediately and processes the book in the background.
    """
    logger.info(f"Received request to process book: {request.book_id}")
    background_tasks.add_task(process_book_task, request.book_id)
    return {"message": "Processing started", "book_id": request.book_id}

@app.get("/health", status_code=200)
async def health_check():
    """Health check endpoint for Fly.io."""
    return {"status": "ok"}
