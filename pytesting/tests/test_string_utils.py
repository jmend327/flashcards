from pytesting.string_utils import reverse_string, is_palindrome, count_vowels


class TestReverseString:
    def test_simple(self):
        assert reverse_string("hello") == "olleh"

    def test_empty(self):
        assert reverse_string("") == ""

    def test_single_char(self):
        assert reverse_string("a") == "a"


class TestIsPalindrome:
    def test_palindrome(self):
        assert is_palindrome("racecar") is True

    def test_not_palindrome(self):
        assert is_palindrome("hello") is False

    def test_with_spaces(self):
        assert is_palindrome("taco cat") is True

    def test_mixed_case(self):
        assert is_palindrome("Madam") is True


class TestCountVowels:
    def test_mixed(self):
        assert count_vowels("hello") == 2

    def test_no_vowels(self):
        assert count_vowels("gym") == 0

    def test_all_vowels(self):
        assert count_vowels("aeiou") == 5
