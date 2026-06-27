import fitz  # PyMuPDF
import logging
import os
import tempfile
import logging
from typing import List, Dict, Any, Tuple
from app.parsers.base import BaseParser
from app.config import settings
from app.parsers.ai_extractor import AIExtractor

logger = logging.getLogger(__name__)

class PDFParser(BaseParser):
    def parse(self, file_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        doc = fitz.open(file_path)
        
        # Extract Cover Image
        cover_path = None
        if doc.page_count > 0:
            try:
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Higher resolution
                fd, cover_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                pix.save(cover_path)
            except Exception as e:
                logger.warning(f"Could not extract PDF cover: {e}")

        # Extract Metadata
        doc_meta = doc.metadata or {}
        metadata = {
            "title": doc_meta.get("title", ""),
            "author": doc_meta.get("author", ""),
            "page_count": doc.page_count,
            "cover_path": cover_path
        }

        logger.info("Extracting raw text from PDF...")
        full_text = ""
        for page_num in range(doc.page_count):
            try:
                page = doc.load_page(page_num)
                full_text += page.get_text() + "\n"
            except Exception:
                pass
                
        doc.close()
        
        if not full_text.strip():
            logger.warning("Extracted PDF text is empty.")
            return metadata, []

        extractor = AIExtractor()
        if settings.gemini_api_key:
            logger.info("Using AIExtractor for chapter boundary detection.")
            chapters = extractor.extract_chapters(full_text)
            
            # If AIExtractor succeeds
            if chapters:
                # Optionally chunk huge chapters returned by AI
                final_chapters = []
                chapter_num = 1
                for ch in chapters:
                    if ch["word_count"] > settings.max_chunk_words * 2:
                        chunks = self.chunk_text(ch["content"], settings.max_chunk_words)
                        for idx, chunk in enumerate(chunks):
                            final_chapters.append({
                                "chapter_num": chapter_num,
                                "title": f"{ch['title']} (Part {idx + 1})",
                                "content": chunk,
                                "word_count": len(chunk.split())
                            })
                            chapter_num += 1
                    else:
                        ch["chapter_num"] = chapter_num
                        final_chapters.append(ch)
                        chapter_num += 1
                return metadata, final_chapters
        else:
            logger.warning("No Gemini API Key found. Falling back to basic chunking.")
            
        # Fallback chunking if AI extraction fails or is disabled
        logger.info("Falling back to standard chunking.")
        chapters = []
        chunks = self.chunk_text(full_text, settings.max_chunk_words)
        for idx, chunk in enumerate(chunks):
            chapters.append({
                "chapter_num": idx + 1,
                "title": f"Part {idx + 1}",
                "content": chunk,
                "word_count": len(chunk.split())
            })
            
        return metadata, chapters
