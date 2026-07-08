"""Background worker tests (Session 7). Run headless with QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from duw.data.loader import load_seed_counterparties
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.pipeline.orchestrator import RunConfig
from duw.pipeline.worker import PipelineWorker, create_worker_thread

AS_OF = date(2025, 6, 30)
FAST = RunConfig(n_paths=300, n_steps=4, seed=2024)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _counterparty():
    return {c.counterparty_id: c for c in load_seed_counterparties()}["CP001"]


def _proposed() -> IRS:
    return IRS(
        trade_id="NEW1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )


def _empty_set() -> NettingSet:
    return NettingSet(netting_set_id="NS1", counterparty_id="CP001", trades=())


def test_worker_run_emits_progress_and_finished() -> None:
    _app()
    worker = PipelineWorker(_counterparty(), _empty_set(), _proposed(), FAST)
    progress: list[float] = []
    captured: dict[str, object] = {}
    worker.progress.connect(lambda f, _m: progress.append(f))
    worker.finished.connect(lambda r: captured.__setitem__("results", r))
    worker.failed.connect(lambda m: captured.__setitem__("error", m))

    worker.run()  # synchronous invocation of the slot

    assert "error" not in captured
    results = captured["results"]
    assert results.exposure is not None
    assert results.cva is not None
    assert results.limits is not None
    assert len(progress) == 12
    assert progress[-1] == 1.0


def test_worker_completes_on_a_qthread() -> None:
    app = _app()
    worker = PipelineWorker(_counterparty(), _empty_set(), _proposed(), FAST)
    thread = create_worker_thread(worker)
    loop = QEventLoop()
    captured: dict[str, object] = {}

    worker.finished.connect(lambda r: captured.__setitem__("results", r))
    worker.finished.connect(loop.quit)
    worker.failed.connect(lambda m: captured.__setitem__("error", m))
    worker.failed.connect(loop.quit)
    QTimer.singleShot(60_000, loop.quit)  # safety timeout

    thread.start()
    loop.exec()
    thread.wait(2_000)

    assert "error" not in captured
    assert "results" in captured
    assert captured["results"].exposure is not None
    app.processEvents()


def test_worker_reports_failure_on_bad_input() -> None:
    _app()
    # A trade type the engine cannot price would raise inside run(); here we
    # force an error by handing the orchestrator a proposed trade whose currency
    # has no curve, exercising the failed() path rather than a raised exception.
    _app()
    bad_trade = IRS(
        trade_id="BAD",
        counterparty_id="CP001",
        notional=1_000_000.0,
        currency="ZZZ",  # no curve for this currency in the snapshot
        trade_date=AS_OF,
        maturity_date=date(2028, 6, 30),
        fixed_rate=0.04,
        direction=SwapDirection.PAY_FIXED,
    )
    worker = PipelineWorker(_counterparty(), _empty_set(), bad_trade, FAST)
    captured: dict[str, object] = {}
    worker.finished.connect(lambda r: captured.__setitem__("results", r))
    worker.failed.connect(lambda m: captured.__setitem__("error", m))

    worker.run()

    assert "error" in captured
    assert isinstance(captured["error"], str)
