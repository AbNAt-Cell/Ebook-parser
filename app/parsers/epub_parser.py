import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple
from app.parsers.base import BaseParser
from app.config import settings

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

        metadata = {
            "title": title,
            "author": author,
            "page_count": 0  # EPUBs don't have standard page counts
        }

        chapters = []
        chapter_num = 1
        
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            # Parse HTML content
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            
            # Extract chapter title if available (from h1, h2, or title tag)
            chapter_title = ""
            heading = soup.find(['h1', 'h2', 'title'])
            if heading:
                chapter_title = heading.get_text().strip()
            
            if not chapter_title:
                chapter_title = f"Chapter {chapter_num}"

            content = soup.get_text(separator='\n').strip()
            
            if not content:
                continue

            word_count = len(content.split())
            
            # Chunk if chapter is too long
            if word_count > settings.max_chunk_words * 2:
                chunks = self.chunk_text(content, settings.max_chunk_words)
                for idx, chunk in enumerate(chunks):
                    chapters.append({
                        "chapter_num": chapter_num,
                        "title": f"{chapter_title} (Part {idx + 1})",
                        "content": chunk,
                        "word_count": len(chunk.split())
                    })
                    chapter_num += 1
            else:
                chapters.append({
                    "chapter_num": chapter_num,
                    "title": chapter_title,
                    "content": content,
                    "word_count": word_count
                })
                chapter_num += 1

        # Fallback if no valid chapters were found via ITEM_DOCUMENT (rare but possible)
        if not chapters:
            full_text = ""
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    full_text += soup.get_text(separator='\n') + "\n"
            
            if full_text.strip():
                chunks = self.chunk_text(full_text, settings.max_chunk_words)
                for idx, chunk in enumerate(chunks):
                    chapters.append({
                        "chapter_num": idx + 1,
                        "title": f"Part {idx + 1}",
                        "content": chunk,
                        "word_count": len(chunk.split())
                    })

        return metadata, chapters
