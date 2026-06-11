"""The manual-dispatch callback pump.

Steam delivers events (lobby joins, async call results, session
requests...) as "callbacks". In C++ a macro system dispatches them; for
every other language Valve provides MANUAL DISPATCH (SDK >= 1.48): you
poll a queue once per frame, on your own thread. No Steam thread ever
calls into Python -- which is exactly why a pure-ctypes binding can
work at all.

Valve's required order, which run_frame() implements (steam_api.h
documents it; note the pseudocode comment there is garbled -- the
ordering rules below come from the docs and are pinned by our tests):

    SteamAPI_ManualDispatch_Init()                    once, after init
    per frame:
        SteamAPI_ManualDispatch_RunFrame(pipe)
        while SteamAPI_ManualDispatch_GetNextCallback(pipe, &msg):
            ... handle msg ...                        (see below)
            SteamAPI_ManualDispatch_FreeLastCallback(pipe)   ALWAYS

    "handle msg" splits in two:
      * msg.m_iCallback == 703 (SteamAPICallCompleted_t): an async call
        finished. Read the INNER struct's m_hAsyncCall / m_iCallback /
        m_cubParam, allocate exactly m_cubParam bytes, and fetch the
        result with GetAPICallResult(pipe, hAsyncCall, buf, m_cubParam,
        inner m_iCallback, &failed). Getting these arguments from the
        OUTER msg instead is the classic manual-dispatch bug (it broke
        mature bindings -- Steamworks.NET issue #413).
      * anything else: a plain broadcast callback; decode by id.

    FreeLastCallback runs in a `finally` so a decoding surprise can
    never leak the callback slot -- the failure mode that wedges the
    whole pipe.

DELIVERY: run_frame() returns the frame's events as a plain list of
(callback_id, payload) tuples -- the Python spelling of the C
"switch (msg.m_iCallback)". No handler registration, no event objects,
no framework. payload is the matching ctypes struct from _structs.py
(copied, safe to keep), or raw bytes if the id is unregistered or the
size disagrees with our struct (nothing is hidden or dropped).

CALL-RESULTS: functions like CreateLobby return a SteamAPICall_t
handle. When its completion arrives, the decoded result ALSO lands in a
small buffer keyed by that handle; pop it with take_call_result(handle).
This mirrors how GetAPICallResult itself is keyed by handle -- it is a
buffer, not a framework. The buffer keeps at most the most recent
_PENDING_CALL_RESULTS_MAX (128) undrained results, evicting the oldest,
so ignoring it entirely is safe; just drain handles you care about
promptly (within 128 async calls, which in practice means "the same
second they complete").

Thread rule: pump one pipe from one thread (Valve's contract --
GetNextCallback/FreeLastCallback are a stateful pair). Call run_frame
from your game's main loop, every frame.
"""

import ctypes

from ._loader import get_lib
from ._structs import CALLBACK_REGISTRY, CallbackMsg_t, SteamAPICallCompleted_t

# Completed-but-not-yet-collected call results:
#   SteamAPICall_t handle -> (callback_id, payload, io_failed)
# Drain handles you care about via take_call_result, or ignore them and
# read everything from run_frame's returned list instead -- ignoring is
# safe because the buffer is BOUNDED: once it holds
# _PENDING_CALL_RESULTS_MAX entries, the oldest entry is evicted to make
# room (each async call has a unique handle, so without a bound a
# caller who never drains would leak one entry per call, forever).
_pending_call_results = {}
_PENDING_CALL_RESULTS_MAX = 128


def _decode(callback_id, source, size):
    """Copy `size` bytes from a ctypes pointer into the struct for this id.

    Returns the registered struct (a safe copy -- the source buffer is
    about to be freed), or plain bytes when the id is unknown or the
    size doesn't match our struct definition. A size mismatch would
    mean silent field corruption if we decoded anyway; handing back the
    raw bytes is honest and keeps the pump running.
    """
    raw = ctypes.string_at(source, size) if size > 0 else b""
    cls = CALLBACK_REGISTRY.get(callback_id)
    if cls is None or ctypes.sizeof(cls) != size:
        return raw
    inst = cls()
    ctypes.memmove(ctypes.byref(inst), raw, size)
    return inst


def run_frame(hSteamPipe, lib=None):
    """Pump all pending Steam callbacks. Returns [(callback_id, payload), ...].

    Call once per frame from one thread, with the pipe from
    SteamAPI_GetHSteamPipe(). Before the first call ever, call
    SteamAPI_ManualDispatch_Init() once (right after SteamAPI_InitFlat).

    payload is the decoded ctypes struct for ids in CALLBACK_REGISTRY
    (e.g. LobbyCreated_t -- check payload.k_iCallback or the id), or
    raw bytes for ids we don't define. Completed async calls are
    delivered in the list like everything else AND stored for
    take_call_result(handle).

    The `lib` parameter exists for tests, which inject a scripted fake
    library; real callers leave it None.
    """
    if lib is None:
        lib = get_lib()
    delivered = []
    msg = CallbackMsg_t()

    lib.SteamAPI_ManualDispatch_RunFrame(hSteamPipe)
    while lib.SteamAPI_ManualDispatch_GetNextCallback(hSteamPipe, ctypes.byref(msg)):
        try:
            if (
                msg.m_iCallback == SteamAPICallCompleted_t.k_iCallback  # 703
                and msg.m_cubParam == ctypes.sizeof(SteamAPICallCompleted_t)
            ):
                # An async call finished. Copy the completion notice out
                # first -- the docs allow callbacks to post during
                # GetAPICallResult, which may invalidate msg's payload.
                # (The size check above mirrors _decode's discipline: a
                # short 703 payload would mean reading past the buffer,
                # so it falls through to raw-bytes delivery instead.)
                completed = SteamAPICallCompleted_t()
                ctypes.memmove(
                    ctypes.byref(completed), msg.m_pubParam, ctypes.sizeof(completed)
                )
                # Buffer size and expected id come from the INNER struct.
                buf = (ctypes.c_uint8 * completed.m_cubParam)()
                failed = ctypes.c_bool(False)
                ok = lib.SteamAPI_ManualDispatch_GetAPICallResult(
                    hSteamPipe,
                    completed.m_hAsyncCall,
                    buf,
                    completed.m_cubParam,
                    completed.m_iCallback,
                    ctypes.byref(failed),
                )
                if ok:
                    payload = _decode(completed.m_iCallback, buf, completed.m_cubParam)
                    if len(_pending_call_results) >= _PENDING_CALL_RESULTS_MAX:
                        # Evict the oldest entry (dicts keep insertion
                        # order) so a caller who never drains the buffer
                        # can't grow it forever.
                        _pending_call_results.pop(next(iter(_pending_call_results)))
                    _pending_call_results[completed.m_hAsyncCall] = (
                        completed.m_iCallback, payload, failed.value,
                    )
                    delivered.append((completed.m_iCallback, payload))
            else:
                delivered.append(
                    (msg.m_iCallback, _decode(msg.m_iCallback, msg.m_pubParam, msg.m_cubParam))
                )
        finally:
            # ALWAYS free, even if decoding raised -- a leaked slot
            # wedges the pipe for the rest of the process.
            lib.SteamAPI_ManualDispatch_FreeLastCallback(hSteamPipe)
    return delivered


def take_call_result(hSteamAPICall):
    """Pop the finished result of an async call, or None if still pending.

    hSteamAPICall is the handle returned by CreateLobby / JoinLobby /
    RequestLobbyList / etc. Returns (callback_id, payload, io_failed):

        callback_id  int   -- which result struct this is (e.g. 513)
        payload      struct or bytes -- the decoded result
        io_failed    bool  -- Steam's pbFailed flag; True means the
                              call failed in transit (treat as an error
                              even though a payload is present)

    Results wait here until popped, up to a cap of 128 undrained
    entries (oldest evicted first) -- so poll for your handle promptly
    after the call rather than thousands of async calls later.

    Poll between run_frame() calls:

        call = pysteamnet.SteamAPI_ISteamMatchmaking_CreateLobby(mm, ...)
        while (result := pysteamnet.take_call_result(call)) is None:
            pysteamnet.run_frame(pipe)
            time.sleep(1 / 60)
    """
    return _pending_call_results.pop(hSteamAPICall, None)
