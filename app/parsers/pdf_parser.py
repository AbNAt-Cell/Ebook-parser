import fitz  # PyMuPDF
from typing import List, Dict, Any, Tuple
from app.parsers.base import BaseParser
from app.config import settings

class PDFParser(BaseParser):
    def parse(self, file_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        doc = fitz.open(file_path)
        
        # Extract Metadata
        doc_meta = doc.metadata or {}
        metadata = {
            "title": doc_meta.get("title", ""),
            "author": doc_meta.get("author", ""),
            "page_count": doc.page_count
        }

        chapters = []
        toc = doc.get_toc()

        if toc:
            # We have a TOC. Let's process chapters based on TOC.
            # toc format: [level, title, page_number]
            # We only want top-level or reasonable headings. Let's process sequentially.
            chapter_num = 1
            for i in range(len(toc)):
                level, title, start_page = toc[i]
                
                # Determine end page
                if i + 1 < len(toc):
                    end_page = toc[i + 1][2]
                else:
                    end_page = doc.page_count + 1 # fitz pages are 1-indexed in TOC, but 0-indexed in doc

                # Extract text for this chapter
                # TOC page numbers are 1-indexed, doc.load_page() is 0-indexed
                content = ""
                # Ensure end_page is at least start_page
                end_page = max(start_page, end_page)
                
                for p in range(start_page - 1, min(end_page - 1, doc.page_count)):
                    try:
                        page = doc.load_page(p)
                        content += page.get_text() + "\n"
                    except Exception:
                        pass
                
                content = content.strip()
                if content:
                    # If chapter is extremely long, we might still want to chunk it.
                    # For now, we keep it as one chapter but apply a basic length check.
                    word_count = len(content.split())
                    if word_count > settings.max_chunk_words * 2:
                        # Chunk the long chapter
                        chunks = self.chunk_text(content, settings.max_chunk_words)
                        for idx, chunk in enumerate(chunks):
                            chapters.append({
                                "chapter_num": chapter_num,
                                "title": f"{title} (Part {idx + 1})",
                                "content": chunk,
                                "word_count": len(chunk.split())
                            })
                            chapter_num += 1
                    else:
                        chapters.append({
                            "chapter_num": chapter_num,
                            "title": title,
                            "content": content,
                            "word_count": word_count
                        })
                        chapter_num += 1
        else:
            # Fallback chunking: No TOC found.
            full_text = ""
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                full_text += page.get_text() + "\n"
            
            chunks = self.chunk_text(full_text, settings.max_chunk_words)
            for idx, chunk in enumerate(chunks):
                chapters.append({
                    "chapter_num": idx + 1,
                    "title": f"Part {idx + 1}",
                    "content": chunk,
                    "word_count": len(chunk.split())
                })
        
        doc.close()
        return metadata, chapters
