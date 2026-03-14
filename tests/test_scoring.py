from app.scoring import compute_smart_score, grade_and_weight


def test_grade_weight():
    assert grade_and_weight(90) == ("A", 1.0)
    assert grade_and_weight(78) == ("A", 0.7)
    assert grade_and_weight(70) == ("B", 0.4)


def test_score_penalties():
    score = compute_smart_score(80, 80, 80, 80, 80, 80, False, False, False, False, False)
    penalized = compute_smart_score(80, 80, 80, 80, 80, 80, True, True, True, True, True)
    assert score > penalized
