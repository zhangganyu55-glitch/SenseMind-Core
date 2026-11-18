"""Experimental *non-medical* rules; not validated for seizures or patient care.

Event lifecycle is intentionally conservative:

* open requires ``required_samples`` consecutive bad samples *and* both a
  monotonic real-time ``open_dwell_seconds`` window and a valid sample-time
  window;
* close requires consecutive good samples and a longer
  ``close_dwell_seconds`` recovery window on both clocks;
* a data gap resets the candidate counters but never closes an active event;
* historical/backlogged live data is ignored for rule evaluation so it cannot
  masquerade as a real-time anomaly;
* future-dated live samples are rejected before they can update monitoring or
  become a timeline anchor;
* a backwards clock correction may re-anchor only after the same device
  produced an accepted forward clock jump and its sample counter proves the
  correction was produced afterwards; without such proof the sample is
  conservatively rejected until the device timeline catches up;
* each event kind has its own counters, so no global cooldown can suppress an
  independent safety event.

Lifecycle timestamps written to the event store are server UTC.  The original
sample time is kept separately as ``source_started_at``.
"""
from collections import defaultdict
from datetime import datetime
from math import sqrt
from threading import RLock

from . import monitoring
from .clock import Clock, SystemClock, utc
from .models import Telemetry
from .storage import Storage


class DetectionEngine:
    # Values intentionally demo-only: these are NOT medical advice or clinical cutoffs.
    def __init__(self, storage: Storage, allow_real_rules: bool = False,
                 required_samples: int = 3,
                 open_dwell_seconds: float = 2.0,
                 close_dwell_seconds: float = 10.0,
                 max_sample_gap_seconds: float = 5.0,
                 max_sample_lag_seconds: float = 5.0,
                 max_future_skew_seconds: float = 5.0,
                 monitoring_stale_seconds: float = 30.0,
                 clock: Clock | None = None):
        if required_samples < 1:
            raise ValueError("required_samples must be positive")
        if not 0 <= open_dwell_seconds <= 30:
            raise ValueError("open_dwell_seconds must be 0-30")
        if not 1 <= close_dwell_seconds <= 120:
            raise ValueError("close_dwell_seconds must be 1-120")
        if not 1 <= max_sample_gap_seconds <= 60:
            raise ValueError("max_sample_gap_seconds must be 1-60")
        if not 0 <= max_sample_lag_seconds <= 300:
            raise ValueError("max_sample_lag_seconds must be 0-300")
        if not 0 <= max_future_skew_seconds <= 30:
            raise ValueError("max_future_skew_seconds must be 0-30")
        self.storage = storage
        self.allow_real_rules = allow_real_rules
        self.required_samples = required_samples
        self.open_dwell_seconds = open_dwell_seconds
        self.close_dwell_seconds = close_dwell_seconds
        self.max_sample_gap_seconds = max_sample_gap_seconds
        self.max_sample_lag_seconds = max_sample_lag_seconds
        self.max_future_skew_seconds = max_future_skew_seconds
        self.monitoring_stale_seconds = monitoring_stale_seconds
        self.clock = clock or SystemClock()
        self.counters = defaultdict(self._empty)
        self._last_sample: dict[str, datetime] = {}
        self._last_monotonic: dict[str, float] = {}
        self._last_received: dict[str, datetime] = {}
        # Per-device clock anomaly state.  A rollback may only re-anchor after
        # this device produced an accepted forward clock jump.  The pre-jump
        # anchor prevents a duplicate/backlog packet from being mistaken for a
        # correction.
        self._clock_jump_state: dict[str, dict] = {}
        self.lock = RLock()

    @staticmethod
    def _empty():
        return {
            "bad": 0, "good": 0,
            "bad_since_mono": None, "bad_since_sample": None,
            "good_since_mono": None, "good_since_sample": None,
        }

    def reset_state(self) -> None:
        """Clear all in-memory dwell candidates and per-device clock state.

        A process restart constructs a fresh engine, so an unfinished dwell
        never survives a restart.  This explicit method is used by tests and
        any future hot-reload path.
        """
        with self.lock:
            self.counters.clear()
            self._last_sample.clear()
            self._last_monotonic.clear()
            self._last_received.clear()
            self._clock_jump_state.clear()

    def _continuity(self, t: Telemetry, received: datetime, monotonic: float,
                    sample_delta: float | None, arrival_delta: float | None,
                    receipt_delta: float | None, *, gap: bool = False,
                    clock_jump: bool = False, clock_rollback: bool = False,
                    clock_uncertain: bool = False, delayed: bool = False,
                    out_of_order: bool = False, future_skew: bool = False) -> dict:
        return {
            "sample_time": t.timestamp.isoformat(),
            "received_at": received.isoformat(),
            "monotonic": monotonic,
            "sample_delta_seconds": (round(sample_delta, 3)
                                     if sample_delta is not None else None),
            "arrival_delta_seconds": (round(arrival_delta, 3)
                                      if arrival_delta is not None else None),
            "receipt_delta_seconds": (round(receipt_delta, 3)
                                      if receipt_delta is not None else None),
            "sample_age_seconds": round((received - t.timestamp).total_seconds(), 3),
            "gap_detected": gap,
            "clock_jump": clock_jump,
            "clock_rollback": clock_rollback,
            "clock_uncertain": clock_uncertain,
            "future_skew": future_skew,
            "delayed_sample": delayed,
            "out_of_order": out_of_order,
        }

    @staticmethod
    def _sample_counter(t: Telemetry) -> int | None:
        # Telemetry has no generic stream sequence or boot/session id.  The
        # H1 DeviceStatus counter is the only authoritative 32-bit sequence
        # carried into the rule engine.  APK vendor_sequence stays in the APK
        # raw row and is not promoted to Telemetry, so APK/ring paths use the
        # conservative no-counter policy.
        status = t.device_status
        return status.sample_counter if status is not None else None

    @staticmethod
    def _counter_after(counter: int | None, reference: int | None) -> bool:
        """Return True only when a 32-bit counter proves forward progress."""
        if counter is None or reference is None:
            return False
        delta = (counter - reference) & 0xffffffff
        return 0 < delta < 0x80000000

    def _is_clock_rollback(self, device_id: str, t: Telemetry,
                           sample_time: datetime,
                           sample_delta: float | None,
                           arrival_delta: float | None,
                           receipt_delta: float | None,
                           sample_age: float) -> bool:
        """Recognise a fresh clock correction, not a late/duplicate sample.

        A rollback is only eligible when this device previously produced an
        accepted forward clock jump *and* the device's own sample counter
        proves the candidate was produced after that jump.  A single timestamp
        plus server receipt is not enough: a late pre-jump packet can look
        exactly like a correction.  Server receipt and monotonic time must
        strictly advance; equal ticks are rejected.
        """
        state = self._clock_jump_state.get(device_id)
        if state is None:
            return False
        if not self._counter_after(
                self._sample_counter(t), state.get("jump_counter")):
            return False
        if sample_time <= state["previous_sample"]:
            return False
        if sample_delta is None or sample_delta >= -self.max_sample_gap_seconds:
            return False
        if not -self.max_future_skew_seconds <= sample_age <= self.max_sample_lag_seconds:
            return False
        if arrival_delta is None or arrival_delta <= 0:
            return False
        if receipt_delta is None or receipt_delta <= 0:
            return False
        return True

    @staticmethod
    def _result(evaluation: str, transitions: list[dict], continuity: dict,
                *, rule_evaluated: bool = True, signals: list[str] | None = None,
                **extra) -> dict:
        return {
            "evaluation": evaluation,
            "signals": signals or [],
            "transitions": transitions,
            "rule_evaluated": rule_evaluated,
            "continuity": continuity,
            **extra,
        }

    def analyze(self, t: Telemetry, *, now: datetime | None = None,
                received_at: datetime | None = None,
                monotonic: float | None = None):
        moment = utc(now) if now is not None else utc(self.clock.now())
        received = utc(received_at) if received_at is not None else moment
        mono = float(monotonic) if monotonic is not None else float(self.clock.monotonic())
        transitions: list[dict] = []

        with self.lock:
            last_sample = self._last_sample.get(t.device_id)
            last_mono = self._last_monotonic.get(t.device_id)
            last_received = self._last_received.get(t.device_id)
            sample_delta = ((t.timestamp - last_sample).total_seconds()
                            if last_sample is not None else None)
            arrival_delta = (mono - last_mono
                             if last_mono is not None else None)
            receipt_delta = ((received - last_received).total_seconds()
                             if last_received is not None else None)

            sample_age = (received - t.timestamp).total_seconds()
            data_mode = t.data_mode or ("replay" if t.source == "simulator" else "live")
            delayed = (sample_age > self.max_sample_lag_seconds
                       and data_mode != "replay")
            # Live data uses the strict 5 s future bound.  Replay data may use
            # a virtual schedule up to the model-level 30 s tolerance; it is
            # still prevented from updating live monitoring below.
            future_limit = (30.0 if data_mode == "replay"
                            else self.max_future_skew_seconds)
            future_skew = sample_age < -future_limit

            # Detect a forward clock jump before the future check so the
            # diagnostic still reports both conditions on the same packet.
            gap_detected = False
            clock_jump = False
            if (last_sample is not None and sample_delta is not None
                    and sample_delta > 0):
                sample_advanced = sample_delta > self.max_sample_gap_seconds
                arrival_advanced = (arrival_delta is not None
                                    and arrival_delta > self.max_sample_gap_seconds)
                receipt_advanced = (receipt_delta is not None
                                    and receipt_delta > self.max_sample_gap_seconds)
                if sample_advanced and not arrival_advanced and not receipt_advanced:
                    # The device timestamp jumped while the server was receiving
                    # normally.  Treat it as a clock event, not as 5+ seconds of
                    # observed physiology.
                    clock_jump = True
                    self._reset_counters(t.device_id)
                elif arrival_advanced or receipt_advanced:
                    gap_detected = True
                    self._reset_counters(t.device_id)

            # A rejected future timestamp must not touch monitoring/last_valid
            # or become a new timeline anchor.  This check runs before the
            # real-rule gate so passive real-device monitoring is safe too.
            if future_skew:
                self._reset_counters(t.device_id)
                return self._result(
                    "clock_skew_ignored", transitions,
                    self._continuity(
                        t, received, mono, sample_delta, arrival_delta,
                        receipt_delta, gap=gap_detected,
                        clock_jump=clock_jump, delayed=delayed,
                        future_skew=True),
                    rule_evaluated=False)

            # Once the device timeline passes the temporary jump anchor, the
            # anomaly is over: normal ordering resumes and the pending state
            # is cleared.  A duplicate exactly at the anchor does not clear it.
            prior_state = self._clock_jump_state.get(t.device_id)
            if prior_state is not None and t.timestamp > prior_state["jump_sample"]:
                self._clock_jump_state.pop(t.device_id, None)

            if clock_jump and last_sample is not None:
                # Remember the pre-jump anchor and the device counter for this
                # device.  A later rollback is eligible only against this
                # recorded anomaly and only with counter-proven ordering.
                self._clock_jump_state[t.device_id] = {
                    "previous_sample": last_sample,
                    "jump_sample": t.timestamp,
                    "jump_counter": self._sample_counter(t),
                }

            clock_rollback = False
            if sample_delta is not None and sample_delta <= 0:
                if self._is_clock_rollback(
                        t.device_id, t, t.timestamp, sample_delta,
                        arrival_delta, receipt_delta, sample_age):
                    # The device returned to its normal timeline after a
                    # forward jump.  Re-anchor instead of rejecting every
                    # normal sample until the temporary anchor is reached.
                    clock_rollback = True
                    self._clock_jump_state.pop(t.device_id, None)
                    self._reset_counters(t.device_id)
                else:
                    # Late/duplicate/rollback data must not touch monitoring
                    # or the live candidate counters.  If a jump is still
                    # pending, report the uncertainty and wait for counter
                    # proof or the device timeline to catch up.
                    return self._result(
                        "out_of_order_ignored", transitions,
                        self._continuity(
                            t, received, mono, sample_delta, arrival_delta,
                            receipt_delta, delayed=delayed,
                            clock_uncertain=(
                                self._clock_jump_state.get(t.device_id)
                                is not None),
                            out_of_order=True),
                        rule_evaluated=False)

            continuity = self._continuity(
                t, received, mono, sample_delta, arrival_delta, receipt_delta,
                gap=gap_detected, clock_jump=clock_jump,
                clock_rollback=clock_rollback, delayed=delayed)

            self._last_sample[t.device_id] = t.timestamp
            self._last_monotonic[t.device_id] = mono
            self._last_received[t.device_id] = received

            # Monitoring tracks the latest accepted sample even when the
            # real-device rule path is disabled.  Future/out-of-order samples
            # returned above and never reach this point.  Delayed samples are
            # recorded as stale input.
            monitoring.record(
                self.storage, t.device_id, t, now=moment,
                stale_seconds=self.monitoring_stale_seconds,
                max_future_seconds=self.max_future_skew_seconds)

            # The real-device safety gate takes precedence over freshness: a
            # disabled real-device rule path must keep reporting the same
            # evaluation regardless of whether the packet is also delayed.
            # Replay/test compatibility is intentionally left to T12-4.
            if t.source in ("stm32", "ring", "esp32") and not self.allow_real_rules:
                return self._result(
                    "real_data_rules_disabled", transitions, continuity,
                    rule_skipped="real_data_rules_disabled")

            if delayed:
                # Backlog uploads are stored, but they are not live evidence.
                # Reset candidates so a later real-time sample starts clean.
                self._reset_counters(t.device_id)
                return self._result(
                    "delayed_sample_ignored", transitions, continuity,
                    rule_evaluated=False)

            quality_good = t.reading_valid and t.signal_quality == "good"
            observed = {
                "high_heart_rate": t.heart_rate is not None,
                "low_spo2": t.spo2 is not None,
                "unusual_motion": None not in (t.acc_x, t.acc_y, t.acc_z),
            }
            observed["concurrent_signals"] = all(observed.values())
            observed["data_quality"] = True
            signals = []
            if quality_good:
                if t.heart_rate is not None and t.heart_rate >= 120:
                    signals.append("high_heart_rate")
                if t.spo2 is not None and t.spo2 <= 93:
                    signals.append("low_spo2")
                if None not in (t.acc_x, t.acc_y, t.acc_z):
                    mag = sqrt(t.acc_x ** 2 + t.acc_y ** 2 + t.acc_z ** 2)
                    if mag >= 2.5:
                        signals.append("unusual_motion")
                if len(signals) >= 2:
                    signals.append("concurrent_signals")
                    observed["concurrent_signals"] = True
                if not all(observed.values()):
                    signals.append("data_quality")
            else:
                signals.append("data_quality")

            keys = ("high_heart_rate", "low_spo2", "unusual_motion",
                    "concurrent_signals", "data_quality")
            # Unknown/poor signal may never resolve an existing physiological event.
            for key in keys:
                if key != "data_quality" and (not quality_good or not observed[key]):
                    self.counters[(t.device_id, key)] = self._empty()
                    continue
                counts = self.counters[(t.device_id, key)]
                if key in signals:
                    if counts["bad"] == 0:
                        counts["bad_since_mono"] = mono
                        counts["bad_since_sample"] = t.timestamp
                    counts["bad"] += 1
                    counts["good"] = 0
                    counts["good_since_mono"] = None
                    counts["good_since_sample"] = None
                    elapsed_mono = mono - counts["bad_since_mono"]
                    elapsed_sample = (
                        t.timestamp - counts["bad_since_sample"]).total_seconds()
                    if (counts["bad"] >= self.required_samples
                            and elapsed_mono >= self.open_dwell_seconds
                            and elapsed_sample >= self.open_dwell_seconds):
                        transition = self.storage.event_open(
                            t.device_id, key, received,
                            "DEMO ONLY: unvalidated signal rule; investigate "
                            "source/quality; not diagnosis",
                            source_started_at=counts["bad_since_sample"])
                        if transition:
                            transitions.append(transition)
                        counts["bad"] = 0
                        counts["bad_since_mono"] = None
                        counts["bad_since_sample"] = None
                else:
                    if counts["good"] == 0:
                        counts["good_since_mono"] = mono
                        counts["good_since_sample"] = t.timestamp
                    counts["good"] += 1
                    counts["bad"] = 0
                    counts["bad_since_mono"] = None
                    counts["bad_since_sample"] = None
                    elapsed_mono = mono - counts["good_since_mono"]
                    elapsed_sample = (
                        t.timestamp - counts["good_since_sample"]).total_seconds()
                    if (counts["good"] >= self.required_samples
                            and elapsed_mono >= self.close_dwell_seconds
                            and elapsed_sample >= self.close_dwell_seconds):
                        transition = self.storage.event_close(
                            t.device_id, key, received)
                        if transition:
                            transitions.append(transition)
                        counts["good"] = 0
                        counts["good_since_mono"] = None
                        counts["good_since_sample"] = None
            return self._result(
                "demo_experimental_rules", transitions, continuity,
                signals=signals)

    def _reset_counters(self, device_id: str) -> None:
        for key in ("high_heart_rate", "low_spo2", "unusual_motion",
                    "concurrent_signals", "data_quality"):
            self.counters[(device_id, key)] = self._empty()
