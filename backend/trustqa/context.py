import json
from .prompts import messages


class Window:
    def __init__(self, config):
        self.limit = config.context_tokens - config.output_tokens - 128
        self.policy = "utf8_byte_upper_bound"
        self.tokenizer = None
        if config.qwen_tokenizer:
            try:
                from transformers import AutoTokenizer
            except ImportError:
                raise ValueError("Install trustqa[tokenizer] to use the Qwen tokenizer") from None
            self.tokenizer = AutoTokenizer.from_pretrained(config.qwen_tokenizer, trust_remote_code=False)
            self.policy = "qwen_chat_template:" + config.qwen_tokenizer

    def count(self, items):
        if self.tokenizer:
            return len(self.tokenizer.apply_chat_template(items, tokenize=True, add_generation_prompt=True))
        return len(json.dumps(items, ensure_ascii=False).encode("utf-8")) + 128

    def fits(self, items):
        return self.count(items) <= self.limit

    def baseline(self, question, package):
        files = sorted(package.documents)
        # Metadata and every filename remain intact even when document text is truncated.
        text = "\n\n".join(f"FILE {f}\n{package.documents[f]}" for f in files)
        def build(n):
            return messages(question, files, [{"text": text[:n]}])
        if not self.fits(build(0)):
            raise ValueError("Question and complete file manifest exceed context window")
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.fits(build(mid)):
                lo = mid
            else:
                hi = mid - 1
        return build(lo), lo < len(text)

    def pack(self, question, files, chunks, instruction="", extra=None):
        batches, current = [], []
        for chunk in chunks:
            row = chunk.data() if hasattr(chunk, "data") else chunk
            if not self.fits(messages(question, files, current + [row], instruction, extra)):
                if current:
                    batches.append(current)
                    current = []
                if not self.fits(messages(question, files, [row], instruction, extra)):
                    raise ValueError("A chunk exceeds context budget; decrease CHUNK_CHARS")
            current.append(row)
        if current:
            batches.append(current)
        return batches
