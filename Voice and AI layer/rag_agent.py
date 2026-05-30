"""
rag_agent.py
RAG-агент консультации по правилам РЖД.

Архитектура:
  1. При инициализации загружает текстовые файлы из knowledge_base/
  2. Разбивает на чанки и индексирует в ChromaDB (локально, без сервера)
  3. При вопросе пользователя:
     a. Цепочка 1 (Retrieval) — ищет топ-3 релевантных чанка
     b. Цепочка 2 (QA) — передаёт найденные фрагменты + вопрос в GigaChat
     c. Возвращает ответ со ссылкой на источник
"""

import os
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain_gigachat.chat_models import GigaChat
from langchain.memory import ConversationBufferMemory

KB_DIR     = os.path.join(os.path.dirname(__file__), "knowledge_base")
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")

QA_PROMPT_TEMPLATE = """Ты — вежливый консультант РЖД. Отвечай ТОЛЬКО на основе предоставленного контекста.
Если ответа в контексте нет — скажи: «К сожалению, у меня нет информации по этому вопросу.
Уточните на сайте rzd.ru или по телефону 8-800-775-00-00.»

Отвечай кратко, по делу, на русском языке.

Контекст из документов РЖД:
{context}

Вопрос пользователя: {question}

Ответ:"""

QA_PROMPT = PromptTemplate(
    template=QA_PROMPT_TEMPLATE,
    input_variables=["context", "question"],
)

SOURCE_NAMES = {
    "rzd_rules.txt":   "Правила перевозок",
    "rzd_refund.txt":  "Правила возврата",
    "rzd_faq.txt":     "FAQ",
    "rzd_tariffs.txt": "Тарифная политика",
}


class RagConsultAgent:
    """
    Агент-консультант на основе RAG.
    Использует две LangChain-цепочки:
      - Цепочка 1: Retrieval (поиск по векторной БД ChromaDB)
      - Цепочка 2: RetrievalQA (генерация ответа через GigaChat)
    ConversationBufferMemory хранит контекстное окно диалога.
    """

    def __init__(self, gigachat_credentials: str):

        # Контекстное окно диалога консультации
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
        )

        llm = GigaChat(
            credentials=gigachat_credentials,
            temperature=0.3,
            verify_ssl_certs=False,
        )

        vectorstore = self._build_vectorstore()

        # Цепочка 1: retriever — поиск топ-3 релевантных чанков
        retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3},
        )

        # Цепочка 2: RetrievalQA — генерация ответа на основе найденных документов
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": QA_PROMPT},
        )


    def ask(self, question: str) -> str:
        """
        Задать вопрос агенту-консультанту.
        Возвращает текстовый ответ с указанием источника.
        """
        # Обогащаем вопрос историей диалога для контекстного окна
        history = self.memory.load_memory_variables({}).get("chat_history", [])
        enriched_question = question
        if history:
            history_text = "\n".join(
                f"{'Пользователь' if m.type == 'human' else 'Ассистент'}: {m.content}"
                for m in history[-4:]  # последние 2 обмена
            )
            enriched_question = (
                f"История диалога:\n{history_text}\n\nТекущий вопрос: {question}"
            )

        result = self.qa_chain.invoke({"query": enriched_question})
        answer = result["result"].strip()

        # Добавляем источник для прозрачности RAG
        source_docs = result.get("source_documents", [])
        if source_docs:
            sources = set(
                os.path.basename(doc.metadata.get("source", ""))
                for doc in source_docs
            )
            labels = [SOURCE_NAMES.get(s, s) for s in sources]
            answer += f"\n\n[Источник: {', '.join(labels)}]"

        # Сохраняем в память (контекстное окно)
        self.memory.save_context(
            {"input": question},
            {"output": answer},
        )

        return answer

    def clear_history(self):
        """Сбросить историю консультационного диалога."""
        self.memory.clear()

    # -----------------------------------------------------------------------

    def _build_vectorstore(self) -> Chroma:
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            model_kwargs={"device": "cpu"},
        )

        if os.path.exists(CHROMA_DIR) and os.listdir(CHROMA_DIR):
            return Chroma(
                persist_directory=CHROMA_DIR,
                embedding_function=embeddings,
            )

        documents = self._load_documents()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " "],
        )
        chunks = splitter.split_documents(documents)

        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=CHROMA_DIR,
        )
        return vectorstore

    def _load_documents(self):
        docs = []
        if not os.path.exists(KB_DIR):
            raise FileNotFoundError(f"Папка базы знаний не найдена: {KB_DIR}")
        for filename in sorted(os.listdir(KB_DIR)):
            if filename.endswith(".txt"):
                path = os.path.join(KB_DIR, filename)
                loader = TextLoader(path, encoding="utf-8")
                docs.extend(loader.load())
        if not docs:
            raise ValueError(f"В папке {KB_DIR} нет .txt файлов!")
        return docs