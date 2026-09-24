import numpy as np

from webcam_bot.audio import SlidingWindow


def test_windows_overlap_like_yamnet():
    ventanas = SlidingWindow(window=4, hop=2)
    senal = np.arange(10, dtype=np.float32)

    resultado = ventanas.push(senal)

    assert [list(v) for v in resultado] == [
        [0, 1, 2, 3], [2, 3, 4, 5], [4, 5, 6, 7], [6, 7, 8, 9],
    ]


def test_windows_across_several_pushes():
    ventanas = SlidingWindow(window=4, hop=2)

    assert ventanas.push(np.arange(3, dtype=np.float32)) == []
    resultado = ventanas.push(np.arange(3, 6, dtype=np.float32))

    assert [list(v) for v in resultado] == [[0, 1, 2, 3], [2, 3, 4, 5]]


def test_clear_discards_pending_audio():
    ventanas = SlidingWindow(window=4, hop=2)
    ventanas.push(np.arange(3, dtype=np.float32))

    ventanas.clear()

    assert ventanas.push(np.arange(3, dtype=np.float32)) == []
