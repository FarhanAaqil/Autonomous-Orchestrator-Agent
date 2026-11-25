from eval import run_eval


def test_offline_predictions_do_not_use_expected_labels(monkeypatch):
    monkeypatch.setattr('orchestrator_core.core.router._heuristic_classify', lambda command: {'agent': 'general_chat_agent', 'confidence': 0.9, 'reasoning': 'fixed'})
    dataset = [{'id': 1, 'command': 'same input', 'expected_agent': 'email_agent'}, {'id': 2, 'command': 'same input', 'expected_agent': 'github_agent'}]
    result = run_eval.run_classification(dataset, dry_run=True)
    assert result[0]['predicted'] == result[1]['predicted'] == 'general_chat_agent'
    assert not run_eval.check_ci_gate(run_eval.compute_metrics(result), 'test')[0]


def test_throwing_router_fails_quality_gate(monkeypatch):
    def broken(command, **kwargs):
        raise RuntimeError('fixture failure')
    monkeypatch.setattr(run_eval, 'classify', broken)
    result = run_eval.run_classification([{'id': 1, 'command': 'hello', 'expected_agent': 'general_chat_agent'}])
    assert result[0]['predicted'] is None
    assert not run_eval.check_ci_gate(run_eval.compute_metrics(result), 'test')[0]
