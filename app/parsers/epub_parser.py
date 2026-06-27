import ebooklib
from ebooklib import epub
import os
import tempfile
from bs4 import BeautifulSoup
import logging
from typing import List, Dict, Any, Tuple
from app.parsers.base import BaseParser
from app.config import settings
from app.parsers.ai_extractor import AIExtractor

logger = logging.getLogger(__name__)

class EPUBParser(BaseParser):
    def parse(self, file_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        book = epub.read_epub(file_path)
        
        # Extract Metadata
        title = ""
        titles = book.get_metadata('DC', 'title')
        if titles:
            title = titles[0][0]
            
        author = ""
        creators = book.get_metadata('DC', 'creator')
        if creators:
            author = creators[0][0]

        # Extract Cover Image
        cover_path = None
        try:
            # Check for cover image items
            cover_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_COVER]
            # If no explicit cover, just get the first image
            if not cover_items:
                cover_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_IMAGE]
            
            if cover_items:
                cover_item = cover_items[0]
                ext = ".jpg" if "jpeg" in cover_item.media_type or "jpg" in cover_item.media_type else ".png"
                fd, cover_path = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                with open(cover_path, "wb") as f:
                    f.write(cover_item.get_content())
        except Exception as e:
            logger.warning(f"Could not extract EPUB cover: {e}")

        metadata = {
            "title": title,
            "author": author,
            "page_count": 0,  # EPUBs don't have standard page counts
            "cover_path": cover_path
        }

        logger.info("Extracting raw text from EPUB...")
        full_text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            full_text += soup.get_text(separator='\n') + "\n\n"
            
        if not full_text.strip():
            logger.warning("Extracted EPUB text is empty.")
            return metadata, []

        extractor = AIExtractor()
        if settings.gemini_api_key:
            logger.info("Using AIExtractor for EPUB chapter boundary detection.")
            chapters = extractor.extract_chapters(full_text)
            
            # If AIExtractor succeeds
            if chapters:
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
        logger.info("Falling back to standard EPUB chunking.")
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
