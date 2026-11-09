from tools.file_indexer import FileIndexer

MOVIE = r"D:\Deadpool Wolverine (2024) [1080p]\Deadpool.Wolverine.2024.1080p.WEBRip.mp4"
SUBS = r"D:\Deadpool Wolverine (2024) [1080p]\Subs\English.srt"


def _indexer():
    ix = FileIndexer()
    ix._index = {
        "deadpool.wolverine.2024.1080p.webrip.mp4": [MOVIE],
        "english.srt": [SUBS, r"C:\other\english.srt"],
    }
    return ix


def test_multiword_query_with_filler_words_finds_dotted_filename():
    paths = [r["path"] for r in _indexer().search("Deadpool and Wolverine movie")]
    assert MOVIE in paths


def test_folder_name_words_match_files_inside():
    paths = [r["path"] for r in _indexer().search("deadpool wolverine subs")]
    assert paths == [SUBS]


def test_filename_match_ranks_before_folder_only_match():
    paths = [r["path"] for r in _indexer().search("deadpool wolverine")]
    assert paths[0] == MOVIE


def test_plain_substring_still_works():
    assert [r["path"] for r in _indexer().search("deadpool")] == [MOVIE]


def test_no_match():
    assert _indexer().search("zzzz qqqq") == []
