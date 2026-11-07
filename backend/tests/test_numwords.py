import pytest

from app.numwords import word_numbers


@pytest.mark.parametrize("text,expected", [
    ("в размере пятидесяти тысяч рублей", [50000]),
    ("в течение ста двадцати календарных дней", [120]),
    ("семьдесят пять (75) календарных дней", [75]),
    ("два миллиона триста сорок тысяч", [2340000]),
    ("1,5 миллиона рублей", [1500000]),
    ("тысяча рублей", [1000]),
    ("тридцати шести месяцев", [36]),
    ("никаких чисел тут нет", []),
])
def test_word_numbers(text, expected):
    assert word_numbers(text) == expected
