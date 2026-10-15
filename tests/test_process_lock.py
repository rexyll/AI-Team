import multiprocessing

from runtime.process_lock import exclusive_process_lock


def _critical_section(root, entered, release):
    from pathlib import Path
    import time

    with exclusive_process_lock(Path(root) / ".shared.lock"):
        entered.set()
        release.wait(timeout=5)
        time.sleep(0.05)


def test_process_lock_serializes_independent_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered_a = context.Event()
    release_a = context.Event()
    entered_b = context.Event()

    first = context.Process(target=_critical_section, args=(str(tmp_path), entered_a, release_a))
    second = context.Process(target=_critical_section, args=(str(tmp_path), entered_b, context.Event()))

    first.start()
    assert entered_a.wait(timeout=5)
    second.start()

    assert not entered_b.wait(timeout=0.25)
    release_a.set()
    assert entered_b.wait(timeout=5)

    first.join(timeout=5)
    second.terminate() if second.is_alive() else None
    second.join(timeout=5)
    assert first.exitcode == 0
