import json
import logging
from typing import List, Dict, Any
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

class ChapterBoundary(BaseModel):
    chapter_num: int = Field(description="The sequential number of the chapter.")
    title: str = Field(description="The title of the chapter.")
    start_exact_quote: str = Field(description="A contiguous ~10 word exact quote from the very beginning of the chapter text.")
    end_exact_quote: str = Field(description="A contiguous ~10 word exact quote from the very end of the chapter text.")

class AIChapterExtraction(BaseModel):
    chapters: list[ChapterBoundary]

class AIExtractor:
    def __init__(self):
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY is not set. AIExtractor cannot run.")
        else:
            self.client = genai.Client(api_key=settings.gemini_api_key)
            # using gemini-1.5-flash as it's the stable high-context model available
            self.model = "gemini-1.5-flash"

    def extract_chapters(self, full_text: str) -> List[Dict[str, Any]]:
        """
        Takes raw book text, asks Gemini to find chapter boundaries, 
        and slices the raw text using those exact quotes.
        """
        if not settings.gemini_api_key:
            return []

        logger.info("Sending full text to Gemini for boundary detection...")
        
        prompt = (
            "Analyze the following raw book text. Identify the true chapters of the book. "
            "Ignore title pages, copyright info, indices, and dedications. "
            "If the book has NO chapters (e.g. it is a continuous short story or academic paper), "
            "return a SINGLE chapter that spans the entire actual content, carefully skipping the title and copyright pages at the start. "
            "For each chapter, provide its sequential number, its title (or 'Full Text' if there are no chapters), and an exact, contiguous ~10-word quote "
            "from the very beginning of the chapter's actual content (start_exact_quote) and an exact, contiguous ~10-word quote "
            "from the very end of the chapter's actual content before the next chapter begins (end_exact_quote). "
            "The quotes must be exactly as they appear in the text so they can be string-matched."
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, full_text],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AIChapterExtraction,
                    temperature=0.1,
                ),
            )
            
            result = response.parsed
            if not result or not result.chapters:
                logger.warning("Gemini returned empty chapters.")
                return []
                
            logger.info(f"Gemini identified {len(result.chapters)} chapters. Attempting slicing.")
            
            processed_chapters = []
            for ch in result.chapters:
                # Find start
                start_idx = full_text.find(ch.start_exact_quote)
                if start_idx == -1:
                    # Fallback to basic word splitting if exact match fails
                    first_words = " ".join(ch.start_exact_quote.split()[:5])
                    start_idx = full_text.find(first_words)
                    
                # Find end
                end_idx = full_text.find(ch.end_exact_quote, start_idx if start_idx != -1 else 0)
                if end_idx != -1:
                    end_idx += len(ch.end_exact_quote)
                else:
                    # Fallback to last words
                    last_words = " ".join(ch.end_exact_quote.split()[-5:])
                    end_idx = full_text.find(last_words, start_idx if start_idx != -1 else 0)
                    if end_idx != -1:
                        end_idx += len(last_words)
                
                # If we still can't find boundaries, skip or use what we can
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    content = full_text[start_idx:end_idx].strip()
                elif start_idx != -1:
                    content = full_text[start_idx:].strip()
                else:
                    logger.warning(f"Could not align boundaries for chapter {ch.chapter_num}")
                    continue
                    
                processed_chapters.append({
                    "chapter_num": ch.chapter_num,
                    "title": ch.title,
                    "content": content,
                    "word_count": len(content.split())
                })
                
            return processed_chapters

        except Exception as e:
            logger.error(f"Error during Gemini AI extraction: {e}")
            return []
