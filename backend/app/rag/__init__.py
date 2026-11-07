"""RAG: чанкинг, эмбеддинги, ретривер, реранкер, промпты.

Ожидаемый интерфейс для агента:
    retrieve(question: str, docs: list[Document], ctx: Context, k: int = 8) -> list[Chunk]
Модели для эмбеддингов и реранкера берутся из ctx.model("embed") / ctx.model("rerank").
"""
