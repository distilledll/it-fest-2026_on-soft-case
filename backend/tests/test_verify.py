from app.ingest import decode
from app.schemas import Answer, Document, Status
from app.verify import guard, numbers, snap_quote

DOC = Document(package="P", file="01.txt", encoding="utf-8",
               text="2.1. Участник предоставляет обеспечение заявки в размере 1 % от НМЦК, что составляет 18 000,00 рублей.")


def test_numbers():
    assert numbers("18 000,00 руб и 5 %") == [18000.0, 5.0]


def test_cp1251():
    text, enc = decode("Извещение".encode("cp1251"))
    assert text == "Извещение" and enc == "cp1251"


def test_fake_quote_becomes_unknown():
    a = Answer(id="x", status=Status.ANSWER, answer="20000", quote="обеспечение заявки 20 000 рублей", file="01.txt")
    assert guard(a, [DOC]).status == Status.UNKNOWN


def test_near_quote_is_snapped():
    assert snap_quote("что составляет 18000,00 рублей", [DOC]) is not None


def test_number_not_in_quote():
    a = Answer(id="x", status=Status.ANSWER, answer="19000", quote="что составляет 18 000,00 рублей", file="01.txt")
    assert guard(a, [DOC], "Какой размер обеспечения заявки?").status == Status.UNKNOWN


def test_good_answer_passes():
    a = Answer(id="x", status=Status.ANSWER, answer="18000", quote="что составляет 18 000,00 рублей", file="01.txt")
    assert guard(a, [DOC], "Какой размер обеспечения заявки?").status == Status.ANSWER


def test_guard_accepts_words_and_years():
    d = Document(package="P", file="01.txt", encoding="utf-8",
                 text="Обеспечение заявки в размере пятидесяти тысяч рублей. Гарантийный срок 2 (два) года.")
    a = Answer(id="x", status=Status.ANSWER, answer="50000", quote="в размере пятидесяти тысяч рублей", file="01.txt")
    assert guard(a, [d], "Размер обеспечения заявки?").status == Status.ANSWER
    b = Answer(id="y", status=Status.ANSWER, answer="24", quote="Гарантийный срок 2 (два) года", file="01.txt")
    assert guard(b, [d], "Гарантийный срок, в месяцах?").status == Status.ANSWER
