"""Two users confirming orders for the same limited stock at the same time (Part 6).

Each thread uses its own application context, so it gets its own SQLAlchemy session and
its own MySQL connection, exactly like two simultaneous web requests.
"""
import threading
import time

from app.errors import Conflict
from app.extensions import db
from app.models import User
from app.services import orders


def _confirm_in_thread(app, user_id, order_id, results, barrier=None, after_lock=None):
    def work():
        with app.app_context():
            user = db.session.get(User, user_id)
            db.session.commit()  # end the read so the barrier wait doesn't hold a snapshot
            if barrier is not None:
                barrier.wait(timeout=10)
            try:
                orders.confirm_order(user, order_id, _after_lock=after_lock)
                results.append(("ok", order_id))
            except Conflict as exc:
                results.append((exc.code, order_id))
    return threading.Thread(target=work)


def test_two_users_cannot_oversell_limited_stock(app, make):
    for _ in range(10):  # repeat to give a race many chances to show up
        ravi, meera = make.user(), make.user()
        customer = make.customer()
        product = make.product(stock=5)
        order_a = make.order(ravi, customer, [(product, 4)])
        order_b = make.order(meera, customer, [(product, 4)])

        results = []
        barrier = threading.Barrier(2)
        threads = [_confirm_in_thread(app, ravi, order_a, results, barrier),
                   _confirm_in_thread(app, meera, order_b, results, barrier)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        outcomes = sorted(code for code, _ in results)
        assert outcomes == ["INSUFFICIENT_STOCK", "ok"], results
        assert make.stock(product) == 1
        statuses = sorted([make.status(order_a), make.status(order_b)])
        assert statuses == ["Confirmed", "Draft"]
        assert make.movement_count(product) == 2  # opening stock + exactly one ORDER_CONFIRM


def test_second_confirmation_waits_for_the_lock_then_sees_reduced_stock(app, make):
    """Force the interleaving: A holds the product lock while B tries to confirm."""
    ravi, meera = make.user(), make.user()
    customer = make.customer()
    product = make.product(stock=5)
    order_a = make.order(ravi, customer, [(product, 4)])
    order_b = make.order(meera, customer, [(product, 4)])

    a_has_locks = threading.Event()
    release_a = threading.Event()

    def hold_locks():
        a_has_locks.set()
        assert release_a.wait(timeout=10)

    results = []
    thread_a = _confirm_in_thread(app, ravi, order_a, results, after_lock=hold_locks)
    thread_b = _confirm_in_thread(app, meera, order_b, results)
    thread_a.start()
    assert a_has_locks.wait(timeout=10)
    thread_b.start()
    time.sleep(0.5)
    assert thread_b.is_alive(), "B should be blocked on the product row lock held by A"
    assert results == []

    release_a.set()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)
    assert results == [("ok", order_a), ("INSUFFICIENT_STOCK", order_b)]
    assert make.stock(product) == 1


def test_same_order_confirmed_twice_at_once_deducts_once(app, make):
    user = make.user()
    customer = make.customer()
    product = make.product(stock=10)
    order_id = make.order(user, customer, [(product, 3)])

    results = []
    barrier = threading.Barrier(2)
    threads = [_confirm_in_thread(app, user, order_id, results, barrier) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sorted(code for code, _ in results) == ["ORDER_NOT_DRAFT", "ok"]
    assert make.stock(product) == 7
