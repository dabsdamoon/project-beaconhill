from processor import get_last_n, chunk_list


def test_get_last_n():
    assert get_last_n([1, 2, 3, 4, 5], 3) == [3, 4, 5]
    assert get_last_n([1, 2, 3], 1) == [3]
    assert get_last_n([1, 2, 3], 3) == [1, 2, 3]


def test_chunk_list():
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert chunk_list([1, 2, 3], 3) == [[1, 2, 3]]
