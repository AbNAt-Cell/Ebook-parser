from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple

class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Parses the book file.
        Returns:
            Tuple containing:
            - metadata (dict): author, title, page_count (or estimated length)
            - chapters (list of dicts): [{"chapter_num": int, "title": str, "content": str, "word_count": int}]
        """
        pass
        
    def chunk_text(self, text: str, max_words: int = 2500) -> List[str]:
        """Helper to chunk text by words if no TOC is found or chapters are too long."""
        words = text.split()
        chunks = []
        for i in range(0, len(words), max_words):
            chunks.append(" ".join(words[i:i + max_words]))
        return chunks
