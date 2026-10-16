from stringkit import reverse, is_palindrome, count_vowels

# Test reverse
assert reverse('hello') == 'olleh'
assert reverse('') == ''
assert reverse('a') == 'a'
print('reverse tests passed')

# Test is_palindrome
assert is_palindrome('A man a plan a canal Panama') == True
assert is_palindrome('racecar') == True
assert is_palindrome('hello') == False
assert is_palindrome('') == True
assert is_palindrome('No lemon no melon') == True
print('is_palindrome tests passed')

# Test count_vowels
assert count_vowels('hello') == 2
assert count_vowels('HELLO') == 2
assert count_vowels('xyz') == 0
assert count_vowels('') == 0
assert count_vowels('aeiou') == 5
assert count_vowels('AEIOU') == 5
print('count_vowels tests passed')

# Test type errors
try:
    reverse(123)
    assert False, 'Should raise TypeError'
except TypeError:
    pass

try:
    is_palindrome(123)
    assert False, 'Should raise TypeError'
except TypeError:
    pass

try:
    count_vowels(123)
    assert False, 'Should raise TypeError'
except TypeError:
    pass

print('All tests passed!')